"""Immutable local run evidence and inspection; never execution authorization."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import stat
import uuid
if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.validate_json import ROOT, SCHEMA_DIR, build_validator, load_json
from scripts.check_integrity import STAGES as DOCUMENT_STAGES, check_documents

STAGES = ('manifest', 'resolved-profile', 'analysis-request', 'analysis', 'transcript', 'selects', 'story-plan', 'edit-plan', 'review', 'subtitle-map', 'export')
PARENTS = {'analysis-request': ['manifest'], 'analysis': ['analysis-request'], 'transcript': ['manifest'], 'selects': ['analysis', 'resolved-profile'], 'story-plan': ['selects'], 'edit-plan': ['manifest'], 'review': ['edit-plan'], 'subtitle-map': ['edit-plan', 'transcript'], 'export': ['edit-plan', 'review']}

class StateError(ValueError):
    """Incomplete, conflicting, or invalid local run evidence."""


def _validate(value, name):
    if name in ('manifest', 'locks'):
        version = value.get('schema_version') if isinstance(value, dict) else None
        if version not in ('2.0.0', '3.0.0'):
            raise StateError(f'Unsupported {name} schema version')
        schema = ROOT / 'schemas' / version / f'{name}.schema.json'
        validator = build_validator(schema, ROOT / 'schemas')
    else:
        validator = build_validator(SCHEMA_DIR / f'{name}.schema.json')
    errors = list(validator.iter_errors(value))
    if errors:
        raise StateError(f'{name}: {errors[0].message}')


def _hash(path):
    path = Path(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise StateError(f'Unsupported file: {path}')
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def _metadata(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode) or details.st_size > 8 * 1024 * 1024:
            raise StateError(f'Unsupported or oversized metadata: {path}')
        with os.fdopen(os.dup(descriptor), 'rb') as stream:
            raw = stream.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise StateError('Metadata exceeds 8 MiB')
        from scripts.validate_json import _unique_object, _reject_constant
        return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    finally:
        os.close(descriptor)


def _bindings(paths):
    return [{'name': name, 'path': str(Path(path).absolute()), 'sha256': _hash(path)} for name, path in sorted(paths.items())]


def _job_dir(state_dir, job_id):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', job_id):
        raise StateError('Invalid job ID')
    candidate = Path(state_dir).resolve() / job_id
    if candidate.is_symlink():
        raise StateError('Job directory symlinks are unsupported')
    directory = candidate.resolve()
    if directory.is_relative_to(ROOT):
        if not any(directory.is_relative_to(ROOT / kind / job_id) for kind in ('work', 'artifacts')):
            raise StateError('Repository state must be under work/<job_id> or artifacts/<job_id>')
    return directory


@contextmanager
def _lock(directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / '.writer.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StateError('Concurrent job writer') from exc
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _index(directory):
    path = directory / 'latest.json'
    if not path.exists():
        return {}
    value = _metadata(path)
    if not isinstance(value, dict) or any(k not in STAGES or not isinstance(v, str) or not re.fullmatch(r'[a-f0-9]{32}.json', v) for k, v in value.items()):
        raise StateError('Corrupt latest index')
    return value


def _record(directory, filename):
    value = _metadata(directory / filename)
    _validate(value, 'run-record')
    return value


def _canonical(paths, job_id):
    documents = {}
    for name, path in paths.items():
        if (SCHEMA_DIR / f'{name}.schema.json').exists() and name != 'common':
            value = _metadata(path)
            _validate(value, name)
            if value.get('job_id') != job_id:
                raise StateError(f'{name}: job mismatch')
            if name in DOCUMENT_STAGES:
                documents[name] = value
    if documents:
        issues = check_documents(documents)
        if issues:
            raise StateError(f'{issues[0].code}: {issues[0].message}')


def _fresh(directory, index, stage, seen=None):
    seen = set() if seen is None else seen
    if stage in seen:
        return 'STALE'
    if stage not in index:
        return 'MISSING'
    try:
        record = _record(directory, index[stage])
        if record['stage'] != stage or record['job_id'] != directory.name:
            return 'STALE'
        if record['status'] != 'PASS':
            return record['status']
        for binding in record['inputs'] + record['outputs'] + record['sources'] + record['tools']:
            if _hash(binding['path']) != binding['sha256']:
                return 'STALE'
        if not record['outputs']:
            return 'STALE'
        for dependency in record['dependencies']:
            upstream = dependency['stage']
            if upstream not in index or _hash(directory / index[upstream]) != dependency['sha256'] or _fresh(directory, index, upstream, seen | {stage}) != 'FRESH':
                return 'STALE'
        return 'FRESH'
    except (OSError, ValueError, TypeError, KeyError):
        return 'STALE'


def record_run(state_dir, job_id, stage, inputs, outputs, status='PASS'):
    """Record supplied artifacts only. PASS records consistency, not authority."""
    if stage not in STAGES or status not in ('PASS', 'FAIL', 'NOT_RUN', 'NOT_IMPLEMENTED', 'INTERRUPTED'):
        raise StateError('Unknown stage or status')
    directory = _job_dir(state_dir, job_id)
    with _lock(directory):
        index = _index(directory)
        paths = dict(inputs)
        paths.update(outputs)
        if set(inputs) & set(outputs):
            raise StateError('Input/output names must be distinct')
        if status == 'PASS':
            if not outputs or (stage != 'export' and stage not in outputs):
                raise StateError('Canonical stage output required')
        input_bindings, output_bindings = _bindings(inputs), _bindings(outputs)
        if status == 'PASS':
            _canonical(paths, job_id)
        if 'resolved-profile' in paths:
            profile = _metadata(paths['resolved-profile'])
            _validate(profile, 'resolved-profile')
            supplied_hashes = {b['sha256'] for b in input_bindings}
            if any(p['sha256'] not in supplied_hashes for p in profile['chain']):
                raise StateError('Every profile chain file must be supplied as an input')
        sources = {}
        if 'manifest' in paths:
            manifest = _metadata(paths['manifest'])
            _validate(manifest, 'manifest')
            for item in manifest['sources']:
                sources[item['source_id']] = Path(item['path'])
        source_bindings = _bindings(sources)
        if 'manifest' in paths:
            hashes = {b['name']: b['sha256'] for b in source_bindings}
            for item in manifest['sources']:
                if item.get('content_sha256') is not None and hashes[item['source_id']] != item['content_sha256']:
                    raise StateError('Manifest source hash mismatch')
        if status == 'PASS' and stage == 'selects':
            if 'resolved-profile' not in inputs:
                raise StateError('Selects require exact resolved-profile input')
            selects = _metadata(outputs['selects'])
            resolved = _metadata(inputs['resolved-profile'])
            if any(selects[key] != resolved[key] for key in ('job_id', 'profile', 'profile_version')):
                raise StateError('Selects profile binding mismatch')
        dependencies = []
        required = set(PARENTS.get(stage, [])) | (set(inputs) & set(STAGES))
        required.discard(stage)
        for upstream in sorted(required):
            if status == 'PASS' and _fresh(directory, index, upstream) != 'FRESH':
                raise StateError(f'Missing/stale dependency: {upstream}')
            if upstream in index:
                if status == 'PASS' and upstream in inputs:
                    previous = _record(directory, index[upstream])
                    matching = [b for b in previous['outputs'] if b['name'] == upstream]
                    if len(matching) != 1 or matching[0]['sha256'] != _hash(inputs[upstream]):
                        raise StateError(f'Input differs from recorded dependency: {upstream}')
                dependencies.append({'stage': upstream, 'sha256': _hash(directory / index[upstream])})
        tool_paths = {p.name: p for p in SCHEMA_DIR.glob('*.schema.json')}
        if 'manifest' in paths and manifest['schema_version'] == '3.0.0':
            tool_paths['3.0.0-manifest.schema.json'] = ROOT / 'schemas/3.0.0/manifest.schema.json'
        if 'locks' in paths and _metadata(paths['locks']).get('schema_version') == '3.0.0':
            tool_paths['3.0.0-locks.schema.json'] = ROOT / 'schemas/3.0.0/locks.schema.json'
        tool_paths.update({p.name: p for p in (ROOT / 'scripts').glob('*.py')})
        record = {'schema_version': '2.0.0', 'job_id': job_id, 'run_id': uuid.uuid4().hex, 'stage': stage, 'status': status, 'recorded_at': datetime.now(timezone.utc).isoformat(), 'inputs': input_bindings, 'outputs': output_bindings, 'sources': source_bindings, 'tools': _bindings(tool_paths), 'dependencies': dependencies}
        _validate(record, 'run-record')
        # Check again before publication so inputs changed during validation cannot appear fresh.
        for binding in input_bindings + output_bindings + source_bindings:
            if _hash(binding['path']) != binding['sha256']:
                raise StateError('Files changed during recording')
        filename = record['run_id'] + '.json'
        with (directory / filename).open('x') as stream:
            json.dump(record, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        index[stage] = filename
        temporary = directory / ('.latest-' + uuid.uuid4().hex)
        with temporary.open('x') as stream:
            json.dump(index, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(directory / 'latest.json')
        return record


def inspect_job(state_dir, job_id):
    directory = _job_dir(state_dir, job_id)
    try:
        index = _index(directory)
        statuses = {stage: _fresh(directory, index, stage) for stage in STAGES}
    except (OSError, ValueError):
        statuses = {stage: 'STALE' for stage in STAGES}
    return {'job_id': job_id, 'stages': statuses, 'next_stage': next((s for s in STAGES if statuses[s] != 'FRESH'), None), 'execution_authorized': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['inspect', 'resume', 'record'])
    parser.add_argument('state_dir', type=Path)
    parser.add_argument('job_id')
    parser.add_argument('--stage', choices=STAGES)
    parser.add_argument('--status', default='PASS', choices=['PASS', 'FAIL', 'NOT_RUN', 'NOT_IMPLEMENTED', 'INTERRUPTED'])
    parser.add_argument('--input', action='append', default=[], metavar='NAME=PATH')
    parser.add_argument('--output', action='append', default=[], metavar='NAME=PATH')
    args = parser.parse_args(argv)
    try:
        if args.operation == 'record':
            result = record_run(args.state_dir, args.job_id, args.stage, dict(x.split('=', 1) for x in args.input), dict(x.split('=', 1) for x in args.output), args.status)
        else:
            result = inspect_job(args.state_dir, args.job_id)
        print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(f'STATE_ERROR: {exc}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())

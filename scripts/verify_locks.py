"""Preserve observed human locks; stored flags and records alone are not authority."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat

try:
    from .validate_json import SCHEMA_DIR, build_validator, load_json
    from .verify_approval import _read
    from .validate_json import _unique_object, _reject_constant
except ImportError:
    from validate_json import SCHEMA_DIR, build_validator, load_json
    from verify_approval import _read
    from validate_json import _unique_object, _reject_constant


@dataclass(frozen=True)
class LockDecision:
    stage: str
    item_id: str
    action: str
    user_message: str
    context_reference: str


@dataclass(frozen=True)
class TrustedLockContext:
    """Trusted caller attests to authentic historical decisions at this digest.

    This is an application trust assumption, not cryptographic human identity.
    Never reconstruct this context automatically from a disk receipt.
    """
    record_sha256: str
    context_reference: str


def digest(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('A regular source/artifact file is required')
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate(value: dict, stage: str) -> None:
    errors = list(build_validator(SCHEMA_DIR / f'{stage}.schema.json').iter_errors(value))
    if errors:
        raise ValueError(f'Invalid {stage}: {errors[0].message}')


def parse(raw: bytes) -> dict:
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                      parse_constant=_reject_constant)


def documents(paths: dict[str, Path]) -> dict:
    if 'manifest' not in paths or paths.keys() - {'manifest', 'selects', 'edit-plan'}:
        raise ValueError('Manifest and known lock stages required')
    result = {stage: parse(_read(path)) for stage, path in paths.items()}
    for stage, doc in result.items():
        validate(doc, stage)
    if len({doc['job_id'] for doc in result.values()}) != 1:
        raise ValueError('Lock job mismatch')
    for stage in ('selects', 'edit-plan'):
        items = result.get(stage, {}).get('items', [])
        key = 'select_id' if stage == 'selects' else 'edit_id'
        if len({item[key] for item in items}) != len(items):
            raise ValueError('Duplicate locked-stage item IDs')
    sources = result['manifest']['sources']
    if len({s['source_id'] for s in sources}) != len(sources):
        raise ValueError('Duplicate source IDs')
    return result


def _source_hash(documents: dict, source_id: str) -> str:
    source = next((s for s in documents['manifest']['sources'] if s['source_id'] == source_id), None)
    if source is None:
        raise ValueError('Locked source missing from manifest')
    measured = digest(Path(source['path']))
    if source.get('content_sha256') not in (None, measured):
        raise ValueError('Locked source bytes disagree with manifest')
    return measured


def verify_locks(paths: dict[str, Path], record_path: Path,
                 context: TrustedLockContext) -> dict:
    if not isinstance(context, TrustedLockContext) or not context.context_reference.strip():
        raise ValueError('A trusted caller must attest to genuine historical locks')
    raw = _read(record_path)
    actual = hashlib.sha256(raw).hexdigest()
    if actual != context.record_sha256:
        raise ValueError('Historical lock record digest mismatch')
    record = parse(raw)
    validate(record, 'locks')
    docs = documents(paths)
    if record['job_id'] != docs['manifest']['job_id']:
        raise ValueError('Lock record job mismatch')
    protected = set()
    for entry in record['locks']:
        stage, item_id = entry['stage'], entry['item_id']
        key = 'select_id' if stage == 'selects' else 'edit_id'
        identity = (stage, item_id)
        if identity in protected or stage not in docs:
            raise ValueError('Duplicate lock or missing locked stage')
        protected.add(identity)
        item = next((i for i in docs[stage]['items'] if i[key] == item_id), None)
        if item is None or item != entry['item'] or not item['locked']:
            raise ValueError('Locked decision removed or changed; explicit unlock required')
        if item[key] != entry['item_id'] or item['source_id'] != entry['source_id']:
            raise ValueError('Lock identity mismatch')
        if _source_hash(docs, item['source_id']) != entry['source_sha256']:
            raise ValueError('Locked source changed; conflict requires resolution')
    for stage in ('selects', 'edit-plan'):
        key = 'select_id' if stage == 'selects' else 'edit_id'
        for item in docs.get(stage, {}).get('items', []):
            if item['locked'] and (stage, item[key]) not in protected:
                raise ValueError('Unattested locked flag')
    if _read(record_path) != raw:
        raise ValueError('Lock record changed during verification')
    return {'status': 'PASS', 'job_id': record['job_id'], 'record_sha256': actual,
            'protected_items': len(protected),
            'authority': 'Trusted caller attests to observed historical human decisions'}


def capture_locks(paths: dict[str, Path], events: list[LockDecision], *,
                  previous: Path | None = None,
                  context: TrustedLockContext | None = None) -> dict:
    """Trusted host supplies observed events; no CLI imports alleged human events."""
    docs = documents(paths)
    entries = {}
    previous_raw = None
    if previous is not None:
        # Prior snapshots may be unlocked by this batch, but historical bytes must
        # still be authenticated before changing their protection.
        previous_raw = _read(previous)
        if not isinstance(context, TrustedLockContext) or not context.context_reference.strip() or hashlib.sha256(previous_raw).hexdigest() != context.record_sha256:
            raise ValueError('Trusted historical context required')
        old = parse(previous_raw)
        validate(old, 'locks')
        if old['job_id'] != docs['manifest']['job_id']:
            raise ValueError('Historical job mismatch')
        for entry in old['locks']:
            identity = (entry['stage'], entry['item_id'])
            if identity in entries:
                raise ValueError('Duplicate historical lock')
            entries[identity] = entry
    if not events:
        raise ValueError('Observed lock/unlock events required')
    seen = set()
    for event in events:
        if not isinstance(event, LockDecision) or event.stage not in {'selects', 'edit-plan'} or event.action not in {'LOCK', 'UNLOCK'}:
            raise ValueError('Unknown or untrusted lock event')
        expected = f'{event.action} {event.stage} {event.item_id}'
        if event.user_message.strip().rstrip('.').casefold() != expected.casefold() or not event.context_reference.strip():
            raise ValueError('Explicit observed item-specific decision required')
        identity = (event.stage, event.item_id)
        if identity in seen:
            raise ValueError('Duplicate/conflicting events')
        seen.add(identity)
        if event.action == 'UNLOCK':
            if identity not in entries:
                raise ValueError('Cannot unlock an unrecorded decision')
            del entries[identity]
            continue
        key = 'select_id' if event.stage == 'selects' else 'edit_id'
        item = next((i for i in docs.get(event.stage, {}).get('items', []) if i[key] == event.item_id), None)
        if item is None or not item['locked']:
            raise ValueError('Observed lock requires an existing locked item')
        if identity in entries and item != entries[identity]['item']:
            raise ValueError('Unlock before replacing a prior locked decision')
        source_sha256 = _source_hash(docs, item['source_id'])
        if identity in entries and source_sha256 != entries[identity]['source_sha256']:
            raise ValueError('Unlock before replacing a changed locked source')
        entries[identity] = {'stage': event.stage, 'item_id': event.item_id,
                             'item': item, 'source_id': item['source_id'],
                             'source_sha256': source_sha256,
                             'artifact_sha256': digest(paths[event.stage])}
    record = {'schema_version': '2.0.0', 'job_id': docs['manifest']['job_id'],
              'locks': list(entries.values()),
              'events': [vars(event) for event in events],
              'previous_sha256': context.record_sha256 if previous else None}
    validate(record, 'locks')
    # Check every surviving snapshot and every flag before returning a new record.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='footage-lock-check-') as tmp:
        path = Path(tmp) / 'locks.json'
        path.write_text(json.dumps(record) + '\n')
        verify_locks(paths, path, TrustedLockContext(digest(path), 'Observed events in trusted caller'))
    if previous is not None and _read(previous) != previous_raw:
        raise ValueError('Historical lock record changed during capture')
    return record

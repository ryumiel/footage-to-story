"""Resolve closed editorial YAML profiles into a deterministic byte-bound snapshot."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
import sys

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.validate_json import ROOT, SCHEMA_DIR, build_validator, load_json


class ProfileError(ValueError):
    """Invalid profile, inheritance, or snapshot binding."""


class _Loader(yaml.SafeLoader):
    pass


def _mapping(loader, node):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str):
            raise ProfileError('YAML mapping keys must be strings')
        if key in result:
            raise ProfileError(f'Duplicate YAML key: {key}')
        result[key] = loader.construct_object(value_node, deep=True)
    return result


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _validate(value, name):
    errors = list(build_validator(SCHEMA_DIR / f'{name}.schema.json').iter_errors(value))
    if errors:
        raise ProfileError(f'{name}: {errors[0].message}')


def _intervals(settings):
    for section in ('pacing', 'rules'):
        for key, value in settings.get(section, {}).items():
            if isinstance(value, list) and value[0] > value[1]:
                raise ProfileError(f'Reversed interval: {section}.{key}')


def _merge(parent, child):
    result = deepcopy(parent)
    for key, value in child.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _read_profile(path: Path) -> bytes:
    """Read at most 1 MiB + 1 from a nonblocking regular-file descriptor."""
    limit = 1024 * 1024
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ProfileError('Profile must be a regular file')
        if metadata.st_size > limit:
            raise ProfileError('Profile exceeds 1 MiB')
        with os.fdopen(descriptor, 'rb') as stream:
            descriptor = None
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise ProfileError('Profile exceeds 1 MiB')
        return raw
    finally:
        if descriptor is not None:
            os.close(descriptor)


def resolve_profile(profile: str, job_id: str, profiles_dir: Path = ROOT / 'profiles') -> dict:
    """Resolve root-first inheritance. Hash every source's exact stored bytes."""
    # Validate the requested name before deriving any file path.
    _validate({'profile': profile, 'version': 1, 'parent': None}, 'profile')
    chain = []
    seen = set()
    current = profile
    settings = {}
    documents = []
    while current is not None:
        if current in seen:
            raise ProfileError(f'Inheritance cycle at {current}')
        seen.add(current)
        if len(seen) > 128:
            raise ProfileError('Profile inheritance exceeds 128 entries')
        path = profiles_dir / f'{current}.yaml'
        if path.is_symlink():
            raise ProfileError('Profile symlinks are unsupported')
        try:
            raw = _read_profile(path)
            text = raw.decode('utf-8')
            if any(isinstance(event, yaml.events.AliasEvent) for event in yaml.parse(text, Loader=_Loader)):
                raise ProfileError('YAML aliases are unsupported')
            value = yaml.load(text, Loader=_Loader)
            json.dumps(value, allow_nan=False)
        except (OSError, UnicodeError, yaml.YAMLError, TypeError, ValueError, RecursionError) as exc:
            raise ProfileError(f'Cannot read profile {current}: {exc}') from exc
        _validate(value, 'profile')
        if value['profile'] != current:
            raise ProfileError(f'Profile filename/identity mismatch: {current}')
        _intervals(value)
        documents.append(value)
        chain.append({'profile': current, 'version': value['version'], 'sha256': hashlib.sha256(raw).hexdigest()})
        current = value['parent']
    for value in reversed(documents):
        settings = _merge(settings, {k: v for k, v in value.items() if k not in ('profile', 'version', 'parent')})
    result = {'schema_version': '2.0.0', 'job_id': job_id, 'profile': profile,
              'profile_version': documents[0]['version'], 'chain': list(reversed(chain)), 'settings': settings}
    _validate(result, 'resolved-profile')
    return result


def check_selects_binding(selects: dict, resolved: dict, profiles_dir: Path = ROOT / 'profiles') -> None:
    """Validate selects identity and prove the snapshot still matches live profiles."""
    _validate(selects, 'selects')
    _validate(resolved, 'resolved-profile')
    for key, resolved_key in [('job_id', 'job_id'), ('profile', 'profile'), ('profile_version', 'profile_version')]:
        if selects[key] != resolved[resolved_key]:
            raise ProfileError(f'Selects {key} does not match resolved profile')
    if resolve_profile(resolved['profile'], resolved['job_id'], profiles_dir) != resolved:
        raise ProfileError('Resolved profile is stale or altered')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile')
    parser.add_argument('--job-id', required=True)
    parser.add_argument('--profiles-dir', type=Path, default=ROOT / 'profiles')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--selects', type=Path)
    args = parser.parse_args(argv)
    try:
        result = resolve_profile(args.profile, args.job_id, args.profiles_dir)
        if args.selects:
            check_selects_binding(load_json(args.selects), result, args.profiles_dir)
        output = args.output.resolve()
        if output.is_relative_to(ROOT):
            if not any(output.is_relative_to(ROOT / folder / args.job_id) for folder in ('work', 'artifacts')):
                raise ProfileError('Repository outputs must be in work/<job_id> or artifacts/<job_id>')
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + '\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, output)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except (OSError, ValueError) as exc:
        print(f'PROFILE_ERROR: {exc}', file=sys.stderr)
        return 1
    print('PASS: resolved profile snapshot (editorial decisions and export not authorized)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

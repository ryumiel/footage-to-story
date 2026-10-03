"""Fail-closed Antigravity PreToolUse gate for one hash-bound analysis clip."""
from __future__ import annotations
import hashlib
import fcntl
import json
import os
from pathlib import Path
import shlex
import stat
import sys
from jsonschema.exceptions import ValidationError
try:
    from .validate_json import ROOT, build_validator
except ImportError:
    from validate_json import ROOT, build_validator

MAX_INPUT = 65536
RESPONSE_SCHEMAS = {'agy-response.schema.json', 'agy-av-response.schema.json', 'agy-visual-response.schema.json'}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _parse(raw):
    def reject(value):
        raise ValueError('Non-finite JSON')
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=reject)


def file_hash(path: Path, maximum: int = 20 * 1024 * 1024) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError('Unsupported media file')
        digest = hashlib.sha256()
        count = 0
        while chunk := os.read(fd, 1024 * 1024):
            count += len(chunk)
            if count > maximum:
                raise ValueError('Media exceeds guard limit')
            digest.update(chunk)
        after = os.fstat(fd)
        if (info.st_size, info.st_mtime_ns, info.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise ValueError('Media changed during guard check')
        return digest.hexdigest()
    finally:
        os.close(fd)


def evaluate(policy: dict, event: dict) -> dict:
    """Permit the native media read and strict output-only completion."""
    answer = {'tool': None, 'path': None, 'decision': 'deny', 'reason': 'Unsupported tool request'}
    if not isinstance(event, dict) or not isinstance(event.get('toolCall'), dict):
        return answer
    call = event['toolCall']
    name, args = call.get('name'), call.get('args')
    answer['tool'] = name if isinstance(name, str) else None
    if name == 'finish' and isinstance(args, dict):
        try:
            # agy hook transport includes these annotations; structured output does not.
            annotations = {'toolAction', 'toolSummary'}
            if any(not isinstance(args[key], str) or not args[key].strip() or len(args[key]) > 512
                   for key in annotations & args.keys()):
                return answer
            payload = {key: value for key, value in args.items() if key not in annotations}
            schema_name = policy.get('response_schema', 'agy-response.schema.json')
            if schema_name not in RESPONSE_SCHEMAS:
                return answer
            schema_path = ROOT / 'schemas/2.0.0' / schema_name
            if policy.get('response_schema_sha256') != file_hash(schema_path):
                return answer
            build_validator(schema_path).validate(payload)
            answer.update(decision='allow', reason='Strict output-only completion',
                          output_sha256=hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest())
        except (ValidationError, ValueError, TypeError):
            pass
        return answer
    if name != 'view_file' or not isinstance(args, dict):
        return answer
    candidate = args.get('AbsolutePath')
    answer['path'] = candidate if isinstance(candidate, str) else None
    if set(args) - {'AbsolutePath', 'toolAction', 'toolSummary'} or not isinstance(candidate, str):
        return answer
    try:
        permitted = Path(policy['media_path'])
        if candidate != str(permitted) or Path(candidate).is_symlink() or Path(candidate).resolve() != permitted:
            answer['reason'] = 'Media path outside authorized clip'
        elif file_hash(permitted) != policy['media_sha256']:
            answer['reason'] = 'Media bytes changed'
        else:
            answer.update(decision='allow', reason='Exact authorized analysis clip')
    except (OSError, ValueError, KeyError, TypeError):
        answer['reason'] = 'Unreadable or invalid media binding'
    return answer


def write_guard(workspace: Path, media: Path, *, response_schema: str = 'agy-response.schema.json') -> dict:
    workspace = Path(workspace).resolve()
    media = Path(media).absolute()
    if media.is_symlink():
        raise ValueError('Guard media symlinks are unsupported')
    media = media.resolve()
    if media.parent != workspace:
        raise ValueError('Guard requires an exact direct media file in the isolated workspace')
    if response_schema not in RESPONSE_SCHEMAS:
        raise ValueError('Unsupported response schema')
    schema_path = ROOT / 'schemas/2.0.0' / response_schema
    policy = {'media_path': str(media), 'media_sha256': file_hash(media), 'max_media_reads': 1,
              'response_schema': response_schema, 'response_schema_sha256': file_hash(schema_path)}
    agents = workspace / '.agents'
    if agents.exists():
        raise ValueError('Guard configuration already exists')
    agents.mkdir(mode=0o700)
    policy_path, hooks_path, audit_path = agents / 'media-policy.json', agents / 'hooks.json', agents / 'audit.ndjson'
    policy_path.write_text(json.dumps(policy, indent=2) + '\n')
    guard_path = Path(__file__).resolve()
    command = shlex.join([sys.executable, str(guard_path), str(policy_path), str(audit_path)])
    hooks = {'bounded-media-guard': {'PreToolUse': [{'matcher': '*', 'hooks': [
        {'type': 'command', 'command': command, 'timeout': 5}]}]}}
    hooks_path.write_text(json.dumps(hooks, indent=2) + '\n')
    for p in (policy_path, hooks_path):
        p.chmod(0o400)
    media.chmod(0o400)
    return {'policy_path': str(policy_path), 'hooks_path': str(hooks_path), 'audit_path': str(audit_path),
            'policy_sha256': file_hash(policy_path), 'hooks_sha256': file_hash(hooks_path),
            'guard_path': str(guard_path), 'guard_sha256': file_hash(guard_path)}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    answer = {'tool': None, 'path': None, 'decision': 'deny', 'reason': 'Guard input or audit failure'}
    try:
        if len(args) != 2:
            raise ValueError('Expected policy and audit paths')
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        if len(raw) > MAX_INPUT:
            raise ValueError('Oversized hook input')
        policy_path, audit_path = map(Path, args)
        if policy_path.is_symlink() or audit_path.is_symlink():
            raise ValueError('Unsupported guard symlink')
        fd = os.open(policy_path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_size > MAX_INPUT:
                raise ValueError('Unsupported guard policy')
            policy = _parse(os.read(fd, MAX_INPUT + 1))
        finally:
            os.close(fd)
        if not isinstance(policy, dict) or policy.get('max_media_reads') != 1:
            raise ValueError('Unsupported read budget')
        answer = evaluate(policy, _parse(raw))
        fd = os.open(audit_path, os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_NONBLOCK | os.O_NOFOLLOW, 0o600)
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_size > 1024 * 1024:
                raise ValueError('Unsupported or oversized audit')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            history = [_parse(line) for line in os.read(fd, 1024 * 1024 + 1).splitlines() if line.strip()]
            if any(not isinstance(row, dict) for row in history):
                raise ValueError('Invalid audit state')
            allowed = [row for row in history if row.get('decision') == 'allow']
            if answer['decision'] == 'allow':
                if answer['tool'] == 'view_file' and allowed:
                    answer.update(decision='deny', reason='One media read per attempt exhausted')
                elif answer['tool'] == 'finish' and (len(allowed) != 1 or allowed[0].get('tool') != 'view_file'):
                    answer.update(decision='deny', reason='Completion requires exactly one prior media read')
            record = (json.dumps(answer) + '\n').encode()
            if os.write(fd, record) != len(record):
                raise ValueError('Incomplete audit write')
        finally:
            os.close(fd)
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, RecursionError):
        answer['decision'] = 'deny'
        answer['reason'] = 'Guard input or audit failure'
    print(json.dumps({'decision': answer['decision'], 'reason': answer['reason']}))
    return 0  # Explicit deny JSON on every error; never rely on hook exit semantics.


if __name__ == '__main__':
    raise SystemExit(main())

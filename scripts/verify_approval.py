"""Verify exact plan approval using an externally administered OpenSSH trust anchor."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path

try:
    from .validate_json import SCHEMA_DIR, _unique_object, _reject_constant, build_validator
except ImportError:
    from validate_json import SCHEMA_DIR, _unique_object, _reject_constant, build_validator

TRUST_FILE = Path('/etc/footage-to-story/allowed_signers')
SSH_KEYGEN = Path('/usr/bin/ssh-keygen')
NAMESPACE = 'footage-to-story-review'
MAX_BYTES = 8 * 1024 * 1024


def _read(path: Path) -> bytes:
    # O_NONBLOCK avoids hanging while opening a FIFO supplied as an input.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Approval inputs must be regular files')
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Approval input exceeds 8 MiB')
    return data


def _trusted_bytes(path: Path) -> bytes:
    """Require an admin-owned anchor outside the invoking user's write authority."""
    if os.geteuid() == 0:
        raise ValueError('Approval verification must run as a non-root user')
    resolved = path.resolve(strict=True)
    for entry in (resolved, *resolved.parents):
        metadata = entry.stat()
        if metadata.st_uid != 0 or metadata.st_mode & 0o022 or os.access(entry, os.W_OK):
            raise ValueError(f'Unprotected approval trust dependency: {entry}')
    if not stat.S_ISREG(resolved.stat().st_mode):
        raise ValueError('Approval trust dependency must be a regular file')
    # Check the original path too: an unprotected symlink parent could redirect it.
    for entry in (path.absolute(), *path.absolute().parents):
        metadata = entry.lstat()
        if metadata.st_uid != 0 or (not stat.S_ISLNK(metadata.st_mode) and
                                   (metadata.st_mode & 0o022 or os.access(entry, os.W_OK))):
            raise ValueError(f'Unprotected approval trust path: {entry}')
    return _read(resolved)


def _document(raw: bytes, stage: str) -> dict:
    document = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    errors = list(build_validator(SCHEMA_DIR / f'{stage}.schema.json').iter_errors(document))
    if errors:
        raise ValueError(f'Invalid {stage}: {errors[0].message}')
    return document



@dataclass(frozen=True)
class ConversationApproval:
    """Live authorization supplied by a trusted caller observing actual user input.

    This is not a cryptographic credential. Never construct it from a job file,
    model-generated approval, or saved PASS report. The caller owns authenticity.
    """
    job_id: str
    revision: str
    plan_sha256: str
    reviewed_by: str
    user_message: str
    context_reference: str


def approval_binding(plan_bytes: bytes, review_bytes: bytes) -> tuple[dict, dict, str]:
    plan, review = _document(plan_bytes, 'edit-plan'), _document(review_bytes, 'review')
    digest = hashlib.sha256(plan_bytes).hexdigest()
    if review['reviewer_type'] != 'HUMAN' or review['status'] != 'APPROVED':
        raise ValueError('A HUMAN APPROVED review is required')
    if review['job_id'] != plan['job_id'] or review['edit_plan_revision'] != plan['revision']:
        raise ValueError('Approval job/revision mismatch')
    if review['edit_plan_sha256'] != digest:
        raise ValueError('Approval does not bind the exact stored plan bytes')
    if datetime.fromisoformat(review['reviewed_at'].upper().replace('Z', '+00:00')) > datetime.now(timezone.utc):
        raise ValueError('Approval timestamp is in the future')
    edit_ids = [item['edit_id'] for item in plan['items']]
    if len(set(edit_ids)) != len(edit_ids):
        raise ValueError('Duplicate edit IDs')
    if any(issue.get('edit_id') is not None and issue['edit_id'] not in edit_ids for issue in review['issues']):
        raise ValueError('Review references an unknown edit ID')
    return plan, review, digest


def verify_conversation_approval(plan_path: Path, review_path: Path,
                                 event: ConversationApproval) -> dict:
    if not isinstance(event, ConversationApproval):
        raise ValueError('Live trusted conversation approval is required')
    raw = [_read(plan_path), _read(review_path)]
    plan, review, digest = approval_binding(*raw)
    if (event.job_id, event.revision, event.plan_sha256, event.reviewed_by) != (
            plan['job_id'], plan['revision'], digest, review['reviewed_by']):
        raise ValueError('Conversation approval job/revision/hash/reviewer mismatch')
    if event.user_message.strip().casefold().rstrip('.') not in {
            'i approve', 'i approve this plan and its export/import',
            'i approve this synthetic test plan and its export/import'}:
        raise ValueError('Explicit affirmative user approval is required')
    if not event.context_reference.strip():
        raise ValueError('Actual approval context must be recorded')
    if _read(plan_path) != raw[0] or _read(review_path) != raw[1]:
        raise ValueError('Approval inputs changed during verification')
    return {'status': 'PASS', 'job_id': plan['job_id'], 'revision': plan['revision'],
            'edit_plan_sha256': digest, 'review_sha256': hashlib.sha256(raw[1]).hexdigest(),
            'approval_method': 'TRUSTED_CONVERSATION', 'reviewed_by': event.reviewed_by,
            'user_message': event.user_message, 'context_reference': event.context_reference,
            'authority_assumption': 'Trusted caller observed explicit human approval of this exact plan; saved records alone are not authorization',
            'not_checked': ['independent cryptographic identity', 'media validity',
                            'timeline/audio integrity', 'prior locks', 'export readiness']}


def verify_approval(plan_path: Path, review_path: Path, signature_path: Path) -> dict:
    """Verify stored bytes; never create approvals, keys, signatures, or trust policy."""
    paths = [plan_path, review_path, signature_path]
    raw = [_read(path) for path in paths]
    plan, review, digest = approval_binding(raw[0], raw[1])
    principal = review['reviewed_by']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.@+-]{0,254}', principal):
        raise ValueError('reviewed_by must be a literal registered signing principal')
    policy = _trusted_bytes(TRUST_FILE)
    executable = _trusted_bytes(SSH_KEYGEN)
    with tempfile.TemporaryDirectory(prefix='footage-approval-') as temporary:
        directory = Path(temporary)
        policy_path, sig_path = directory / 'allowed_signers', directory / 'review.sig'
        policy_path.write_bytes(policy)
        sig_path.write_bytes(raw[2])
        command = [str(SSH_KEYGEN), '-Y', 'verify', '-f', str(policy_path),
                   '-I', principal, '-n', NAMESPACE, '-s', str(sig_path)]
        # No shell, SSH agent, user configuration, or job-supplied executable/key.
        completed = subprocess.run(command, input=raw[1], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=15,
                                   env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        if completed.returncode:
            raise ValueError('Signature not authorized by the external trust policy')
    if any(_read(path) != data for path, data in zip(paths, raw)):
        raise ValueError('Approval inputs changed during verification')
    if _trusted_bytes(TRUST_FILE) != policy or _trusted_bytes(SSH_KEYGEN) != executable:
        raise ValueError('Approval trust dependencies changed during verification')
    return {'status': 'PASS', 'job_id': plan['job_id'], 'revision': plan['revision'],
            'edit_plan_sha256': digest, 'review_sha256': hashlib.sha256(raw[1]).hexdigest(),
            'signature_sha256': hashlib.sha256(raw[2]).hexdigest(), 'principal': principal,
            'trust_policy_sha256': hashlib.sha256(policy).hexdigest(), 'namespace': NAMESPACE,
            'not_checked': ['media validity', 'timeline/audio integrity', 'prior locks', 'export readiness'],
            'authority_assumption': 'Administrator enrolled a human-controlled signing key; signature does not prove physical human presence'}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edit-plan', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--signature', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = verify_approval(args.edit_plan, args.review, args.signature)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'APPROVAL_ERROR: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

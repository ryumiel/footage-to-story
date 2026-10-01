"""Synthetic signing identities only; these tests never enroll real approvers."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from scripts import verify_approval as gate
from scripts.validate_json import load_json

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def signed(tmp_path, monkeypatch):
    plan = load_json(ROOT / 'examples/contracts/edit-plan.json')
    plan_path, review_path = tmp_path / 'plan.json', tmp_path / 'review.json'
    plan_path.write_text(json.dumps(plan))
    review = {'schema_version': '2.0.0', 'job_id': plan['job_id'],
              'edit_plan_revision': plan['revision'],
              'edit_plan_sha256': hashlib.sha256(plan_path.read_bytes()).hexdigest(),
              'reviewer_type': 'HUMAN', 'reviewed_by': 'synthetic-test-only',
              'reviewed_at': '2026-01-01T00:00:00Z', 'status': 'APPROVED', 'issues': []}
    review_path.write_text(json.dumps(review))
    key = tmp_path / 'synthetic-key'
    subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
    policy = ('synthetic-test-only namespaces="footage-to-story-review" ' +
              key.with_suffix('.pub').read_text()).encode()
    # Explicit synthetic substitution at the admin trust boundary. Production has
    # no CLI/env trust override, and no test key is installed in /etc.
    monkeypatch.setattr(gate, '_trusted_bytes', lambda path: policy if path == gate.TRUST_FILE else b'synthetic-executable-evidence')
    subprocess.run(['/usr/bin/ssh-keygen', '-Y', 'sign', '-f', str(key), '-n', gate.NAMESPACE,
                    str(review_path)], check=True, capture_output=True)
    return plan_path, review_path, Path(str(review_path) + '.sig'), key, policy


def check(signed):
    return gate.verify_approval(*signed[:3])


def test_synthetic_registered_signature_passes_exact_bindings(signed):
    report = check(signed)
    assert report['status'] == 'PASS'
    assert report['edit_plan_sha256'] == hashlib.sha256(signed[0].read_bytes()).hexdigest()
    assert report['review_sha256'] == hashlib.sha256(signed[1].read_bytes()).hexdigest()
    assert 'export readiness' in report['not_checked']
    assert 'does not prove physical human presence' in report['authority_assumption']


@pytest.mark.parametrize('field,value', [
    ('job_id', 'different-job'), ('edit_plan_revision', 'different-revision'),
    ('edit_plan_sha256', '0' * 64), ('reviewed_by', 'other-principal'),
    ('reviewed_by', '*'), ('reviewed_by', '-argument'),
    ('reviewed_at', '2099-01-01T00:00:00Z'), ('status', 'CHANGES_REQUIRED'),
    ('reviewer_type', 'AI'), ('unknown_field', 'not permitted'),
    ('issues', [{'severity': 'WARN', 'message': 'Synthetic reference', 'edit_id': 'missing'}]),
])
def test_review_mutation_fails(signed, field, value):
    review = json.loads(signed[1].read_text())
    review[field] = value
    signed[1].write_text(json.dumps(review))
    with pytest.raises(ValueError):
        check(signed)


@pytest.mark.parametrize('target', [0, 1, 2])
def test_byte_tampering_fails(signed, target):
    signed[target].write_bytes(signed[target].read_bytes() + b'\n')
    # SSH armored signature trailing whitespace may be accepted: replace its
    # actual signed material rather than assume its textual whitespace matters.
    if target == 2:
        signed[target].write_bytes(b'not an SSH signature')
    with pytest.raises(ValueError):
        check(signed)


@pytest.mark.parametrize('namespace', ['other-workflow', 'file'])
def test_wrong_signature_namespace_fails(signed, namespace):
    signed[2].unlink()
    subprocess.run(['/usr/bin/ssh-keygen', '-Y', 'sign', '-f', str(signed[3]), '-n', namespace,
                    str(signed[1])], check=True, capture_output=True)
    with pytest.raises(ValueError, match='Signature not authorized'):
        check(signed)


def test_job_self_supplied_key_is_not_trusted(signed, monkeypatch):
    monkeypatch.setattr(gate, '_trusted_bytes', lambda path: b'' if path == gate.TRUST_FILE else b'executable')
    with pytest.raises(ValueError, match='Signature not authorized'):
        check(signed)


def test_expired_admin_key_fails_at_current_time(signed, monkeypatch):
    policy = signed[4].replace(b'namespaces="footage-to-story-review"', b'namespaces="footage-to-story-review",valid-before="20200101"')
    monkeypatch.setattr(gate, '_trusted_bytes', lambda path: policy if path == gate.TRUST_FILE else b'executable')
    with pytest.raises(ValueError, match='Signature not authorized'):
        check(signed)


def test_duplicate_json_is_rejected_before_signature(signed):
    signed[1].write_bytes(b'{"job_id":"one","job_id":"two"}')
    with pytest.raises(ValueError, match='Duplicate JSON'):
        check(signed)


def test_input_change_during_signature_check_fails(signed, monkeypatch):
    run = subprocess.run
    def mutate(*args, **kwargs):
        result = run(*args, **kwargs)
        signed[0].write_bytes(signed[0].read_bytes() + b'\n')
        return result
    monkeypatch.setattr(gate.subprocess, 'run', mutate)
    with pytest.raises(ValueError, match='changed during'):
        check(signed)


def test_trust_change_during_verification_fails(signed, monkeypatch):
    calls = 0
    def trust(path):
        nonlocal calls
        if path == gate.TRUST_FILE:
            calls += 1
            return signed[4] if calls == 1 else b'changed'
        return b'executable'
    monkeypatch.setattr(gate, '_trusted_bytes', trust)
    with pytest.raises(ValueError, match='trust dependencies changed'):
        check(signed)


def test_timeout_propagates_and_cli_reports_error(signed, monkeypatch, capsys):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 15)
    monkeypatch.setattr(gate.subprocess, 'run', timeout)
    assert gate.main(['--edit-plan', str(signed[0]), '--review', str(signed[1]),
                      '--signature', str(signed[2])]) == 2
    assert 'APPROVAL_ERROR' in capsys.readouterr().err


def test_user_owned_trust_is_rejected(tmp_path):
    path = tmp_path / 'synthetic-policy'
    path.write_text('untrusted')
    with pytest.raises(ValueError):
        gate._trusted_bytes(path)


def test_root_invocation_is_rejected(monkeypatch):
    monkeypatch.setattr(gate.os, 'geteuid', lambda: 0)
    with pytest.raises(ValueError, match='non-root'):
        gate._trusted_bytes(gate.TRUST_FILE)


def test_no_job_trust_override_available():
    with pytest.raises(SystemExit):
        gate.main(['--allowed-signers', 'job-created-policy'])


def test_oversized_input_fails(tmp_path):
    path = tmp_path / 'oversized'
    path.write_bytes(b' ' * (gate.MAX_BYTES + 1))
    with pytest.raises(ValueError, match='8 MiB'):
        gate._read(path)


def test_signed_lowercase_rfc3339_timestamp(signed):
    review = json.loads(signed[1].read_text())
    review['reviewed_at'] = '2026-01-01t00:00:00z'
    signed[1].write_text(json.dumps(review))
    signed[2].unlink()
    subprocess.run(['/usr/bin/ssh-keygen', '-Y', 'sign', '-f', str(signed[3]), '-n', gate.NAMESPACE,
                    str(signed[1])], check=True, capture_output=True)
    assert check(signed)['status'] == 'PASS'


def test_fifo_input_rejected_without_blocking(tmp_path):
    import os
    path = tmp_path / 'fifo'
    os.mkfifo(path)
    with pytest.raises(ValueError, match='regular files'):
        gate._read(path)


@pytest.mark.parametrize('fault', ['none', 'file-owner', 'parent-owner', 'file-mode',
                                   'parent-mode', 'acl-write', 'symlink-owner'])
def test_admin_trust_path_checks_with_synthetic_metadata(tmp_path, monkeypatch, fault):
    """Model admin filesystem metadata without changing real ownership or ACLs."""
    import os
    import stat
    policy = tmp_path / 'policy'
    policy.write_bytes(b'synthetic policy')
    link = tmp_path / 'link'
    link.symlink_to(policy)
    real_stat, real_lstat = Path.stat, Path.lstat
    def metadata(path, original, is_link=False):
        values = list(original(path))
        values[4] = 0  # Synthetic root-owned object.
        values[0] &= ~0o022
        if fault == 'file-owner' and path == policy:
            values[4] = 123
        if fault == 'parent-owner' and path == tmp_path:
            values[4] = 123
        if fault == 'file-mode' and path == policy:
            values[0] |= 0o020
        if fault == 'parent-mode' and path == tmp_path:
            values[0] |= 0o002
        if fault == 'symlink-owner' and path == link and is_link:
            values[4] = 123
        return os.stat_result(values)
    monkeypatch.setattr(Path, 'stat', lambda path, **kwargs: metadata(path, real_stat))
    monkeypatch.setattr(Path, 'lstat', lambda path, **kwargs: metadata(path, real_lstat, True))
    monkeypatch.setattr(gate.os, 'geteuid', lambda: 501)
    monkeypatch.setattr(gate.os, 'access', lambda path, mode: fault == 'acl-write' and path == tmp_path)
    if fault == 'none':
        assert gate._trusted_bytes(link) == b'synthetic policy'
    else:
        with pytest.raises(ValueError, match='Unprotected'):
            gate._trusted_bytes(link)


def conversation_event(signed):
    plan = json.loads(signed[0].read_text())
    review = json.loads(signed[1].read_text())
    return gate.ConversationApproval(plan['job_id'], plan['revision'],
                                     hashlib.sha256(signed[0].read_bytes()).hexdigest(),
                                     review['reviewed_by'], 'I approve',
                                     'Synthetic trusted user event; not real human approval')


def test_trusted_conversation_binding_requires_no_keys(signed, monkeypatch):
    monkeypatch.setattr(gate, '_trusted_bytes', lambda path: pytest.fail('Conversation approval must not read keys'))
    report = gate.verify_conversation_approval(*signed[:2], conversation_event(signed))
    assert report['status'] == 'PASS'
    assert report['approval_method'] == 'TRUSTED_CONVERSATION'
    assert 'saved records alone are not authorization' in report['authority_assumption']


@pytest.mark.parametrize('field,value', [('job_id', 'other-job'), ('revision', 'other-r'),
                                        ('plan_sha256', '0' * 64), ('reviewed_by', 'someone-else'),
                                        ('user_message', 'I reject'), ('context_reference', '')])
def test_conversation_event_does_not_repair_binding(signed, field, value):
    from dataclasses import replace
    event = replace(conversation_event(signed), **{field: value})
    with pytest.raises(ValueError): gate.verify_conversation_approval(*signed[:2], event)


def test_saved_record_is_not_live_authorization(signed):
    from dataclasses import asdict
    with pytest.raises(ValueError, match='Live trusted'):
        gate.verify_conversation_approval(*signed[:2], asdict(conversation_event(signed)))


def test_plan_changes_invalidate_conversation_approval(signed):
    event = conversation_event(signed)
    signed[0].write_bytes(signed[0].read_bytes() + b'\n')
    with pytest.raises(ValueError): gate.verify_conversation_approval(*signed[:2], event)

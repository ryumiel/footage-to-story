"""Synthetic human lock events test preservation, never actual user authority."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_locks import LockDecision, TrustedLockContext, capture_locks, digest, verify_locks


@pytest.fixture
def job(tmp_path):
    source = tmp_path / 'synthetic.bin'
    source.write_bytes(b'Synthetic source only')
    root = Path('examples/contracts')
    docs = {stage: json.loads((root / f'{stage}.json').read_text()) for stage in ['manifest', 'edit-plan']}
    for entry in docs['manifest']['sources']:
        entry['path'] = str(source)
        entry['content_sha256'] = digest(source)
    docs['edit-plan']['items'][0]['locked'] = True
    paths = {stage: tmp_path / f'{stage}.json' for stage in docs}
    for stage, path in paths.items():
        path.write_text(json.dumps(docs[stage]))
    item_id = docs['edit-plan']['items'][0]['edit_id']
    event = LockDecision('edit-plan', item_id, 'LOCK', f'LOCK edit-plan {item_id}', 'SYNTHETIC_TEST_ONLY')
    record = tmp_path / 'locks.json'
    record.write_text(json.dumps(capture_locks(paths, [event])))
    context = TrustedLockContext(digest(record), 'SYNTHETIC_TEST_ONLY')
    return paths, docs, record, context, source


def test_preserves_snapshot_and_source(job):
    paths, docs, record, context, _ = job
    assert verify_locks(paths, record, context)['protected_items'] == 1


@pytest.mark.parametrize('fault', ['remove', 'range', 'flag', 'audio', 'id', 'reason'])
def test_locked_changes_fail(job, fault):
    paths, docs, record, context, _ = job
    item = docs['edit-plan']['items'][0]
    if fault == 'remove': docs['edit-plan']['items'].pop(0)
    if fault == 'range': item['source_out_frame'] -= 1
    if fault == 'flag': item['locked'] = False
    if fault == 'audio': item['audio_policy'] = 'MUTE'
    if fault == 'id': item['edit_id'] += '-new'
    if fault == 'reason': item['reason'] += ' changed'
    paths['edit-plan'].write_text(json.dumps(docs['edit-plan']))
    with pytest.raises(ValueError): verify_locks(paths, record, context)


def test_source_change_and_receipt_alone_fail(job):
    paths, _, record, context, source = job
    with pytest.raises(ValueError): verify_locks(paths, record, vars(context))
    source.write_bytes(b'Different synthetic bytes')
    with pytest.raises(ValueError): verify_locks(paths, record, context)


def test_unlock_is_explicit_and_bound(job):
    paths, docs, record, context, _ = job
    item = docs['edit-plan']['items'][0]
    item['locked'] = False
    paths['edit-plan'].write_text(json.dumps(docs['edit-plan']))
    event = LockDecision('edit-plan', item['edit_id'], 'UNLOCK', f"UNLOCK edit-plan {item['edit_id']}", 'SYNTHETIC_TEST_ONLY')
    new = capture_locks(paths, [event], previous=record, context=context)
    assert not new['locks']
    assert new['previous_sha256'] == context.record_sha256
    with pytest.raises(ValueError): capture_locks(paths, [event], previous=record)


def test_changed_historical_bytes_fail(job):
    paths, _, record, context, _ = job
    record.write_text(record.read_text() + '\n')
    with pytest.raises(ValueError): verify_locks(paths, record, context)


def test_parses_authenticated_bytes_without_second_record_read(job, monkeypatch):
    import scripts.verify_locks as module
    paths, docs, record, context, _ = job
    docs['edit-plan']['items'][0]['locked'] = False
    paths['edit-plan'].write_text(json.dumps(docs['edit-plan']))
    original = module.load_json
    forged = json.loads(record.read_text())
    forged['locks'] = []
    monkeypatch.setattr(module, 'load_json', lambda path: forged if path == record else original(path))
    with pytest.raises(ValueError, match='removed or changed'):
        verify_locks(paths, record, context)


def test_changed_source_cannot_be_relocked_without_unlock(job):
    paths, docs, record, context, source = job
    source.write_bytes(b'Changed synthetic source')
    for entry in docs['manifest']['sources']:
        entry['content_sha256'] = digest(source)
    paths['manifest'].write_text(json.dumps(docs['manifest']))
    item_id = docs['edit-plan']['items'][0]['edit_id']
    event = LockDecision('edit-plan', item_id, 'LOCK', f'LOCK edit-plan {item_id}', 'SYNTHETIC_TEST_ONLY')
    with pytest.raises(ValueError, match='changed locked source'):
        capture_locks(paths, [event], previous=record, context=context)


def test_unattested_flags_and_duplicate_events_fail(job):
    paths, docs, _, _, _ = job
    item_id = docs['edit-plan']['items'][0]['edit_id']
    event = LockDecision('edit-plan', item_id, 'LOCK', f'LOCK edit-plan {item_id}', 'SYNTHETIC_TEST_ONLY')
    with pytest.raises(ValueError): capture_locks(paths, [event, event])
    docs['edit-plan']['items'][1]['locked'] = True
    paths['edit-plan'].write_text(json.dumps(docs['edit-plan']))
    with pytest.raises(ValueError, match='Unattested'): capture_locks(paths, [event])


def test_unrelated_item_changes_do_not_release_lock(job):
    paths, docs, record, context, _ = job
    docs['edit-plan']['items'][1]['reason'] += ' adjusted'
    paths['edit-plan'].write_text(json.dumps(docs['edit-plan']))
    assert verify_locks(paths, record, context)['status'] == 'PASS'


def test_synthetic_authority_requires_observed_exact_event(job):
    paths, docs, _, _, _ = job
    item_id = docs['edit-plan']['items'][0]['edit_id']
    with pytest.raises(ValueError):
        capture_locks(paths, [LockDecision('edit-plan', item_id, 'LOCK', 'Agent says lock', 'SYNTHETIC')])

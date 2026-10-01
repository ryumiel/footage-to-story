"""Synthetic local state consistency, interruption, and dependency checks."""
import copy
import fcntl
import json
from pathlib import Path
import pytest
from scripts.job_state import StateError, inspect_job, record_run
from scripts.validate_json import ROOT, build_validator


def manifest(tmp_path):
    value = json.loads((ROOT / 'examples/contracts/manifest.json').read_text())
    for number, item in enumerate(value['sources']):
        source = tmp_path / f'synthetic-{number}.bin'
        source.write_bytes(b'synthetic bytes')
        item['path'] = str(source)
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(value))
    return path


def test_manifest_fresh_and_source_mutation(tmp_path):
    path = manifest(tmp_path)
    record_run(tmp_path / 'state', 'synthetic-demo', 'manifest', {}, {'manifest': path})
    report = inspect_job(tmp_path / 'state', 'synthetic-demo')
    assert report['stages']['manifest'] == 'FRESH'
    assert report['execution_authorized'] is False
    (tmp_path / 'synthetic-0.bin').write_bytes(b'changed bytes')
    assert inspect_job(tmp_path / 'state', 'synthetic-demo')['stages']['manifest'] == 'STALE'


def test_missing_corrupt_output_and_immutable_records(tmp_path):
    path = manifest(tmp_path)
    state = tmp_path / 'state'
    first = record_run(state, 'synthetic-demo', 'manifest', {}, {'manifest': path})
    second = record_run(state, 'synthetic-demo', 'manifest', {}, {'manifest': path})
    assert first['run_id'] != second['run_id']
    assert len(list((state / 'synthetic-demo').glob('[0-9a-f]*.json'))) == 2
    path.unlink()
    assert inspect_job(state, 'synthetic-demo')['stages']['manifest'] == 'STALE'


def test_failed_and_interrupted_records(tmp_path):
    state = tmp_path / 'state'
    record_run(state, 'synthetic-demo', 'analysis', {}, {}, 'INTERRUPTED')
    assert inspect_job(state, 'synthetic-demo')['stages']['analysis'] == 'INTERRUPTED'
    record_run(state, 'synthetic-demo', 'analysis', {}, {}, 'FAIL')
    assert inspect_job(state, 'synthetic-demo')['stages']['analysis'] == 'FAIL'


def test_unknown_fields_job_and_concurrent_writer(tmp_path):
    path = manifest(tmp_path)
    data = json.loads(path.read_text())
    data['unexpected'] = True
    path.write_text(json.dumps(data))
    with pytest.raises(StateError):
        record_run(tmp_path / 'state', 'synthetic-demo', 'manifest', {}, {'manifest': path})
    data.pop('unexpected')
    data['job_id'] = 'another-job'
    path.write_text(json.dumps(data))
    with pytest.raises(StateError, match='job mismatch'):
        record_run(tmp_path / 'state', 'synthetic-demo', 'manifest', {}, {'manifest': path})
    directory = tmp_path / 'state' / 'synthetic-demo'
    with (directory / '.writer.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(StateError, match='Concurrent'):
            record_run(tmp_path / 'state', 'synthetic-demo', 'analysis', {}, {}, 'FAIL')


def test_corrupt_index_and_unpublished_orphan(tmp_path):
    path = manifest(tmp_path)
    state = tmp_path / 'state'
    record_run(state, 'synthetic-demo', 'manifest', {}, {'manifest': path})
    directory = state / 'synthetic-demo'
    (directory / 'orphan.json').write_text('{}')
    assert inspect_job(state, 'synthetic-demo')['stages']['manifest'] == 'FRESH'
    (directory / 'latest.json').write_text('{')
    assert inspect_job(state, 'synthetic-demo')['stages']['manifest'] == 'STALE'


def test_request_dependency_and_source_invalidation(tmp_path):
    path = manifest(tmp_path)
    state = tmp_path / 'state'
    record_run(state, 'synthetic-demo', 'manifest', {}, {'manifest': path})
    request = tmp_path / 'request.json'
    request.write_bytes((ROOT / 'examples/contracts/analysis-request.json').read_bytes())
    record_run(state, 'synthetic-demo', 'analysis-request', {'manifest': path}, {'analysis-request': request})
    assert inspect_job(state, 'synthetic-demo')['stages']['analysis-request'] == 'FRESH'
    record_run(state, 'synthetic-demo', 'manifest', {}, {'manifest': path})
    assert inspect_job(state, 'synthetic-demo')['stages']['analysis-request'] == 'STALE'


def test_strict_record_schema(tmp_path):
    record = record_run(tmp_path, 'synthetic-demo', 'analysis', {}, {}, 'FAIL')
    record['authorization'] = True
    assert list(build_validator(ROOT / 'schemas/2.0.0/run-record.schema.json').iter_errors(record))


def test_runtime_restriction_and_not_implemented(tmp_path):
    with pytest.raises(StateError, match='Repository state'):
        record_run(ROOT / 'tests' / 'state', 'synthetic-demo', 'analysis', {}, {}, 'FAIL')
    record_run(tmp_path, 'synthetic-demo', 'analysis', {}, {}, 'NOT_IMPLEMENTED')
    assert inspect_job(tmp_path, 'synthetic-demo')['stages']['analysis'] == 'NOT_IMPLEMENTED'


def test_manifest_declared_hash_mismatch(tmp_path):
    path = manifest(tmp_path)
    value = json.loads(path.read_text())
    value['sources'][0]['content_sha256'] = '0' * 64
    path.write_text(json.dumps(value))
    with pytest.raises(StateError, match='source hash mismatch'):
        record_run(tmp_path / 'state', 'synthetic-demo', 'manifest', {}, {'manifest': path})


def test_job_directory_symlink_refused(tmp_path, monkeypatch):
    import scripts.job_state as state
    monkeypatch.setattr(state, 'ROOT', tmp_path)
    documents = tmp_path / 'docs'
    documents.mkdir()
    work = tmp_path / 'work'
    work.mkdir()
    (work / 'synthetic-demo').symlink_to(documents, target_is_directory=True)
    with pytest.raises(StateError, match='symlinks'):
        record_run(work, 'synthetic-demo', 'analysis', {}, {}, 'FAIL')
    external = tmp_path.parent / f'alias-{tmp_path.name}'
    external.mkdir()
    try:
        (external / 'synthetic-demo').symlink_to(documents, target_is_directory=True)
        with pytest.raises(StateError, match='symlinks'):
            record_run(external, 'synthetic-demo', 'analysis', {}, {}, 'FAIL')
    finally:
        (external / 'synthetic-demo').unlink()
        external.rmdir()
    assert list(documents.iterdir()) == []

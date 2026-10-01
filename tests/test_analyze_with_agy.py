"""Synthetic runner controls; no real provider or upload is used."""
import hashlib
import json
from pathlib import Path

import pytest

from scripts import analyze_with_agy as runner
from scripts.validate_json import ROOT


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


@pytest.fixture
def setup(tmp_path, monkeypatch):
    manifest = tmp_path / 'manifest.json'
    manifest.write_bytes((ROOT / 'examples/contracts/manifest.json').read_bytes())
    request = tmp_path / 'request.json'
    doc = json.loads((ROOT / 'examples/contracts/analysis-request.json').read_text())
    doc['cloud_upload_allowed'] = True
    doc['authorization_ref'] = 'synthetic-observed-consent'
    doc['requested_categories'] = ['speech']
    doc['sources'] = [doc['sources'][0]]
    request.write_text(json.dumps(doc))
    source = tmp_path / 'synthetic-source.mp3'
    source.write_bytes(b'synthetic source bytes')
    auth = {'observed': True, 'manifest_sha256': digest(manifest.read_bytes()),
            'request_sha256': digest(request.read_bytes()),
            'authorization_ref': doc['authorization_ref']}

    def staged(manifest_path, request_path, output_dir, **kwargs):
        assert kwargs['max_total_seconds'] >= 1
        output_dir.mkdir()
        audio = output_dir / 'sample.mp3'
        audio.write_bytes(b'synthetic staged mp3 bytes')
        return {'job_id': doc['job_id'], 'request_id': doc['request_id'],
                'manifest_sha256': digest(manifest.read_bytes()),
                'request_sha256': digest(request.read_bytes()),
                'clips': [{'clip_id': 'clip-01', 'source_id': 'src-001',
                           'source_start_ms': 0, 'source_end_ms': 1000,
                           'local_start_ms': 0, 'local_end_ms': 1000,
                           'source_path': str(source), 'source_sha256': digest(source.read_bytes()),
                           'audio_path': 'sample.mp3', 'audio_sha256': digest(audio.read_bytes())}]}

    monkeypatch.setattr(runner, 'stage_media', staged)
    return manifest, request, source, auth


def fake_agy(tmp_path, mode='success'):
    script = tmp_path / f'fake-agy-{mode}'
    script.write_text('''#!/usr/bin/env python3
import hashlib, json, os, pathlib, sys, time
mode = ''' + repr(mode) + '''
cwd = pathlib.Path.cwd()
media = cwd / 'sample.mp3'
if '/hooks' in sys.argv:
    hookfile = cwd / '.agents' / 'hooks.json'
    config = json.loads(hookfile.read_text())['bounded-media-guard']['PreToolUse'][0]['hooks'][0]
    inventory = {'status':'SUCCESS','usage':{'input_tokens':0,'output_tokens':0,
        'thinking_tokens':0,'total_tokens':0}, 'command':{'name':'hooks','data':{'hooks':[
        {'name':'bounded-media-guard','enabled':True,'source':str(hookfile),
         'actions':[{'event':'PreToolUse','matcher':'*','type':'command',
                     'command':config['command'],'timeout_seconds':5}]}]}}}
    if mode == 'missing-hook': inventory['command']['data']['hooks'] = []
    print(json.dumps(inventory))
    if mode == 'blank-hook': print('\\n')
    sys.exit(0)
if mode == 'timeout':
    time.sleep(5)
if mode == 'overflow':
    sys.stdout.write('x' * 100000)
    sys.stdout.flush()
    time.sleep(5)
if mode == 'token-stream':
    print(json.dumps({'event':'step_update','step_update':{'state':'DONE',
        'step_type':'agent_response','usage':{'total_tokens':999999}}}), flush=True)
    time.sleep(5)
assert '--model' in sys.argv and '--json-schema' in sys.argv
assert '--disable-slash-commands' in sys.argv
assert '--print-timeout' in sys.argv
assert '--dangerously-skip-permissions' not in sys.argv
assert (cwd / 'response-schema.json').exists()
audit = {'tool':'view_file','path':str(media),'decision':'allow','reason':'synthetic'}
if mode == 'deny': audit['decision'] = 'deny'
audits = [audit]
if mode == 'repeat-read':
    audits.append({'tool':'view_file','path':str(media),'decision':'deny',
                   'reason':'Synthetic one-read guard blocked repeat'})
(cwd / '.agents' / 'audit.ndjson').write_text(''.join(json.dumps(row) + '\\n' for row in audits))
read_active = {'event':'step_update','step_update':{'step_index':1,'step_type':'tool','state':'ACTIVE',
               'tool_name':'view_file','tool_info':{'parameters':{'AbsolutePath':str(media)}}}}
read_done = {'event':'step_update','step_update':{'step_index':1,'step_type':'tool','state':'DONE',
             'tool_name':'view_file','tool_info':{'parameters':{'AbsolutePath':str(media)}}}}
if mode == 'read-foreign-index': read_done['step_update']['step_index'] = 9
response = {'audio_available':True,'segments':[{'segment_id':'clip-01-seg-1',
            'start_ms':100,'end_ms':900,'summary':'Synthetic spoken phrase',
            'audible_content':'Synthetic speech', 'confidence':0.8,
            'evidence':['Synthetic audible words']}], 'warnings':[]}
if mode == 'unknown': response['segments'][0]['invented'] = 'no'
if mode == 'bounds': response['segments'][0]['end_ms'] = 1001
if mode == 'unavailable': response['audio_available'] = False
finish_hash = hashlib.sha256(json.dumps(response, sort_keys=True, separators=(',', ':'),
                                       ensure_ascii=False).encode()).hexdigest()
finish_audit = {'tool':'finish','path':None,'decision':'allow',
                'reason':'Synthetic schema-valid completion', 'output_sha256':finish_hash}
if mode == 'finish-hash-mismatch': finish_audit['output_sha256'] = '0' * 64
if mode in ('unknown', 'deny', 'finish-denied'):
    finish_audit = {'tool':'finish','path':None,'decision':'deny',
                    'reason':'Synthetic guard rejected completion'}
if mode != 'missing-finish':
    with (cwd / '.agents' / 'audit.ndjson').open('a') as handle:
        handle.write(json.dumps(finish_audit) + '\\n')
finish_active = {'event':'step_update','step_update':{'step_index':2,'step_type':'tool','state':'ACTIVE',
                 'tool_name':'finish','tool_info':{'parameters':response}}}
finish_done = {'event':'step_update','step_update':{'step_index':2,'step_type':'finish','state':'DONE'}}
if mode == 'finish-foreign-index': finish_done['step_update']['step_index'] = 3
if mode in ('unknown', 'deny', 'finish-denied'):
    finish_done = {'event':'step_update','step_update':{'step_index':2,'step_type':'tool',
                   'state':'ERROR','tool_name':'finish'}}
result = {'event':'result','result':{'status':'SUCCESS','structured_output':response,
          'usage':{'input_tokens':40,'output_tokens':10,'thinking_tokens':5,'total_tokens':50}}}
if mode == 'finish-final-mismatch':
    result['result']['structured_output'] = json.loads(json.dumps(response))
    result['result']['structured_output']['segments'][0]['summary'] = 'Different final words'
if mode == 'unknown-usage': del result['result']['usage']
if mode == 'provider-error': result['result']['status'] = 'ERROR'
if mode == 'error-once' and cwd.name.endswith('-01'): result['result']['status'] = 'ERROR'
if mode == 'underreported-final':
    print(json.dumps({'event':'step_update','step_update':{'step_index':1,
        'state':'DONE','step_type':'agent_response','usage':{'total_tokens':60}}}), flush=True)
print(json.dumps(read_active), flush=True)
print(json.dumps(read_done), flush=True)
if mode == 'repeat-read': print(json.dumps(read_done), flush=True)
if mode != 'missing-finish':
    print(json.dumps(finish_active), flush=True)
    if mode != 'finish-missing-done': print(json.dumps(finish_done), flush=True)
print(json.dumps(result), flush=True)
''')
    script.chmod(0o700)
    return str(script)


def call(setup, tmp_path, *, mode='success', **kwargs):
    manifest, request, source, auth = setup
    return runner.run_analysis(manifest, request, tmp_path / 'run',
                               observed_upload_authorization=auth,
                               agy=fake_agy(tmp_path, mode), **kwargs)


def test_success_preserves_provider_and_imports_candidate_offsets(setup, tmp_path):
    report = call(setup, tmp_path)
    assert report['status'] == 'PASS'
    assert report['calls'] == 1 and report['usage_tokens'] == 50
    assert report['speech_accuracy'] == 'NOT_RUN'
    output = tmp_path / 'run'
    assert (output / 'clip-01-attempt-01' / 'response.ndjson').exists()
    analysis = json.loads((output / 'imported' / 'analysis.json').read_text())
    assert analysis['segments'][0]['start_ms'] == 100
    assert analysis['segments'][0]['audible_content'] == 'Synthetic speech'
    assert (output / 'imported' / 'raw-input.bin').read_bytes() == (output / 'analysis.json').read_bytes()


@pytest.mark.parametrize('mode', ['unknown', 'bounds', 'unavailable', 'unknown-usage', 'deny',
                                  'provider-error', 'timeout', 'overflow', 'token-stream',
                                  'underreported-final', 'finish-denied', 'missing-finish',
                                  'finish-hash-mismatch', 'finish-final-mismatch',
                                  'finish-foreign-index', 'finish-missing-done',
                                  'read-foreign-index'])
def test_bad_provider_attempt_keeps_evidence_and_never_imports(setup, tmp_path, mode):
    with pytest.raises(Exception):
        call(setup, tmp_path, mode=mode, timeout=1, max_output_bytes=4096)
    output = tmp_path / 'run'
    report = json.loads((output / 'run-report.json').read_text())
    assert report['status'] == 'FAIL'
    assert not (output / 'imported').exists()
    assert (output / 'clip-01-attempt-01' / 'response.ndjson').exists()
    assert (output / 'clip-01-attempt-01' / '.agents' / 'hooks.json').exists()
    assert (output / 'clip-01-attempt-01' / 'hooks-inspection.json').exists()


def test_missing_loaded_hook_blocks_before_provider_dispatch(setup, tmp_path):
    with pytest.raises(ValueError, match='hook is missing'):
        call(setup, tmp_path, mode='missing-hook')
    output = tmp_path / 'run'
    assert not (output / 'imported').exists()
    assert (output / 'clip-01-attempt-01' / 'hooks-inspection.json').exists()
    assert not (output / 'clip-01-attempt-01' / 'response.ndjson').exists()


def test_saved_permission_without_observed_binding_never_calls(setup, tmp_path):
    manifest, request, source, auth = setup
    with pytest.raises(ValueError, match='observed upload authorization'):
        runner.run_analysis(manifest, request, tmp_path / 'run', observed_upload_authorization=None,
                            agy=fake_agy(tmp_path))
    assert not (tmp_path / 'run').exists()
    bad = {**auth, 'request_sha256': '0' * 64}
    with pytest.raises(ValueError, match='does not bind'):
        runner.run_analysis(manifest, request, tmp_path / 'run', observed_upload_authorization=bad)


def test_source_change_after_staging_blocks_upload(setup, tmp_path, monkeypatch):
    manifest, request, source, auth = setup
    original = runner.stage_media
    def mutate(*args, **kwargs):
        mapping = original(*args, **kwargs)
        source.write_bytes(b'changed source bytes')
        return mapping
    monkeypatch.setattr(runner, 'stage_media', mutate)
    with pytest.raises(ValueError, match='Source or staged media changed'):
        call(setup, tmp_path)
    assert not list((tmp_path / 'run').glob('*/response.ndjson'))


def test_hash_refuses_fifo_without_blocking(tmp_path):
    import os
    fifo = tmp_path / 'fifo'
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match='regular'):
        runner._file_sha(fifo)


def test_one_recorded_retry_consumes_call_and_upload_budgets(setup, tmp_path):
    report = call(setup, tmp_path, mode='error-once', max_retries=1, max_calls=2,
                  max_uploaded_seconds=2)
    assert report['status'] == 'PASS'
    assert report['calls'] == 2 and report['uploaded_seconds'] == 2
    assert report['usage_tokens'] == 100
    assert [a['status'] for a in report['attempts']] == ['PROVIDER_ERROR', 'PASS']
    assert (tmp_path / 'run' / 'clip-01-attempt-02' / 'response.ndjson').exists()


def test_hook_inventory_blank_lines_are_accepted(setup, tmp_path):
    assert call(setup, tmp_path, mode='blank-hook')['status'] == 'PASS'


def test_second_native_read_cannot_share_one_clip_budget(setup, tmp_path):
    with pytest.raises(ValueError, match='one media read followed by one completion'):
        call(setup, tmp_path, mode='repeat-read', max_calls=1, max_uploaded_seconds=1)
    report = json.loads((tmp_path / 'run' / 'run-report.json').read_text())
    assert report['status'] == 'FAIL'
    assert report['calls'] == 1 and report['uploaded_seconds'] == 1
    assert not (tmp_path / 'run' / 'imported').exists()


@pytest.mark.parametrize('leader_exits', [True, False])
def test_process_group_descendants_cannot_continue_after_return(tmp_path, leader_exits):
    import sys
    import time
    script = tmp_path / 'spawn.py'
    marker = tmp_path / 'descendant-survived'
    child_code = f"import pathlib,time;time.sleep(1.3);pathlib.Path({str(marker)!r}).write_text('survived')"
    script.write_text('import subprocess, sys, time\n'
                      f'subprocess.Popen([sys.executable, "-c", {child_code!r}], '
                      'stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n'
                      'print(\'{"event":"result"}\', flush=True)\n'
                      + ('' if leader_exits else 'time.sleep(5)\n'))
    status = runner._run_process([sys.executable, str(script)], tmp_path, 1, 4096,
                                 tmp_path / 'out.ndjson', tmp_path / 'err.bin', 100)
    assert status == ('OK' if leader_exits else 'TIMEOUT')
    time.sleep(1.5)
    assert not marker.exists()


@pytest.mark.parametrize('limits', [{'max_calls': 0}, {'max_uploaded_seconds': 0},
                                    {'max_usage_tokens': 1}, {'max_retries': 2}])
def test_budgets_fail_closed(setup, tmp_path, limits):
    with pytest.raises(ValueError):
        call(setup, tmp_path, **limits)
    assert not (tmp_path / 'run' / 'imported').exists()

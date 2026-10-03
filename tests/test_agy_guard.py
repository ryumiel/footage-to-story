"""Synthetic tests for the fail-closed native media tool boundary."""
import json
from pathlib import Path
import subprocess
import sys
import pytest
from scripts.agy_guard import write_guard, evaluate

@pytest.fixture
def setup(tmp_path):
    media = tmp_path / 'sample.mp3'
    media.write_bytes(b'SYNTHETIC media placeholder; guard hash test only')
    guard = write_guard(tmp_path, media)
    return media, guard, json.loads(Path(guard['policy_path']).read_text())

def test_exact_read_allowed(setup):
    media, _, policy = setup
    assert evaluate(policy, {'toolCall': {'name': 'view_file', 'args': {'AbsolutePath': str(media)}}})['decision'] == 'allow'

@pytest.mark.parametrize('tool', ['run_command', 'write_to_file', 'read_url_content', 'call_mcp_tool', 'invoke_subagent', 'list_dir', 'unknown_future_tool'])
def test_other_tools_denied(setup, tool):
    media, _, policy = setup
    assert evaluate(policy, {'toolCall': {'name': tool, 'args': {'AbsolutePath': str(media)}}})['decision'] == 'deny'

@pytest.mark.parametrize('suffix', ['../secret.mp3', 'other.mp3'])
def test_other_paths_denied(setup, suffix):
    media, _, policy = setup
    assert evaluate(policy, {'toolCall': {'name': 'view_file', 'args': {'AbsolutePath': str(media.parent / suffix)}}})['decision'] == 'deny'

def test_changed_media_denied(setup):
    media, _, policy = setup
    media.chmod(0o600)
    media.write_bytes(b'changed')
    assert evaluate(policy, {'toolCall': {'name': 'view_file', 'args': {'AbsolutePath': str(media)}}})['decision'] == 'deny'

def test_symlink_denied(setup):
    media, _, policy = setup
    other = media.parent / 'other.mp3'
    other.write_bytes(media.read_bytes())
    media.unlink()
    media.symlink_to(other)
    assert evaluate(policy, {'toolCall': {'name': 'view_file', 'args': {'AbsolutePath': str(media)}}})['decision'] == 'deny'

@pytest.mark.parametrize('event', [{}, {'toolCall': []}, {'toolCall': {'name': 'view_file','args': {'AbsolutePath': '/x', 'StartLine': 0}}}])
def test_malformed_or_extended_calls_denied(setup, event):
    assert evaluate(setup[2], event)['decision'] == 'deny'

def test_hook_process_and_audit(setup):
    media, guard, _ = setup
    result = subprocess.run([sys.executable, 'scripts/agy_guard.py', guard['policy_path'], guard['audit_path']],
       input=json.dumps({'toolCall':{'name':'view_file','args':{'AbsolutePath':str(media)}}}), text=True, capture_output=True, check=True)
    assert json.loads(result.stdout)['decision'] == 'allow'
    assert json.loads(Path(guard['audit_path']).read_text())['decision'] == 'allow'

def test_bad_hook_input_denied(setup):
    _, guard, _ = setup
    result = subprocess.run([sys.executable, 'scripts/agy_guard.py',guard['policy_path'],guard['audit_path']],input='{"x":1,"x":2}',text=True,capture_output=True,check=True)
    assert json.loads(result.stdout)['decision'] == 'deny'


def test_deep_bounded_hook_input_returns_explicit_deny(setup):
    _, guard, _ = setup
    raw = '[' * 20000 + '0' + ']' * 20000
    result = subprocess.run([sys.executable, 'scripts/agy_guard.py', guard['policy_path'], guard['audit_path']],
                            input=raw, text=True, capture_output=True, check=True, timeout=5)
    assert json.loads(result.stdout)['decision'] == 'deny'


def test_second_native_read_is_denied_atomically(setup):
    media, guard, _ = setup
    args = [sys.executable, 'scripts/agy_guard.py', guard['policy_path'], guard['audit_path']]
    event = json.dumps({'toolCall': {'name':'view_file','args':{'AbsolutePath':str(media)}}})
    first = subprocess.run(args,input=event,text=True,capture_output=True,check=True)
    second = subprocess.run(args,input=event,text=True,capture_output=True,check=True)
    assert json.loads(first.stdout)['decision'] == 'allow'
    assert json.loads(second.stdout)['decision'] == 'deny'
    assert 'exhausted' in json.loads(second.stdout)['reason']


def test_concurrent_reads_allow_at_most_one(setup):
    media, guard, _ = setup
    args = [sys.executable, 'scripts/agy_guard.py',guard['policy_path'],guard['audit_path']]
    event=json.dumps({'toolCall':{'name':'view_file','args':{'AbsolutePath':str(media)}}}).encode()
    processes=[subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE) for _ in range(4)]
    for p in processes:
        p.stdin.write(event)
        p.stdin.close()
        p.stdin = None
    outputs=[p.communicate(timeout=5)[0] for p in processes]
    assert sum(json.loads(o)['decision']=='allow' for o in outputs)==1


def test_fifo_audit_does_not_hang(setup):
    import os
    media, guard, _ = setup
    os.mkfifo(guard['audit_path'])
    event=json.dumps({'toolCall':{'name':'view_file','args':{'AbsolutePath':str(media)}}})
    result=subprocess.run([sys.executable,'scripts/agy_guard.py',guard['policy_path'],guard['audit_path']],input=event,text=True,capture_output=True,timeout=2,check=True)
    assert json.loads(result.stdout)['decision']=='deny'


def test_completion_requires_read_and_accepts_only_strict_output(setup):
    media, guard, policy = setup
    args = [sys.executable, 'scripts/agy_guard.py', guard['policy_path'], guard['audit_path']]
    payload = {'audio_available': True, 'segments': [], 'warnings': []}
    def call(name, parameters):
        return json.loads(subprocess.run(args, input=json.dumps({'toolCall': {'name': name, 'args': parameters}}), text=True, capture_output=True, check=True).stdout)
    assert call('finish', payload)['decision'] == 'deny'
    assert evaluate(policy, {'toolCall': {'name': 'finish', 'args': dict(payload, command='run something')}})['decision'] == 'deny'
    assert call('view_file', {'AbsolutePath': str(media)})['decision'] == 'allow'
    annotated = dict(payload, toolAction='Completing synthetic analysis', toolSummary='Synthetic test')
    assert call('finish', annotated)['decision'] == 'allow'
    rows = [json.loads(line) for line in Path(guard['audit_path']).read_text().splitlines()]
    import hashlib
    assert rows[-1]['output_sha256'] == hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    assert call('finish', payload)['decision'] == 'deny'
    assert call('view_file', {'AbsolutePath': str(media)})['decision'] == 'deny'


@pytest.mark.parametrize('annotation', [None, {}, '', 'x' * 513])
def test_invalid_completion_transport_annotation_denied(setup, annotation):
    payload = {'audio_available': True, 'segments': [], 'warnings': [], 'toolAction': annotation}
    assert evaluate(setup[2], {'toolCall': {'name': 'finish', 'args': payload}})['decision'] == 'deny'


def test_audiovisual_guard_uses_exact_response_schema(tmp_path):
    media = tmp_path / 'sample.mp4'
    media.write_bytes(b'SYNTHETIC permission-boundary bytes only')
    guard = write_guard(tmp_path, media, response_schema='agy-av-response.schema.json')
    policy = json.loads(Path(guard['policy_path']).read_text())
    visual = {'segment_id':'clip-0001-v1','start_ms':0,'end_ms':1000,
              'observation_type':'visual','summary':'Synthetic red card',
              'visible_content':'A red card','audible_content':None,
              'confidence':0.9,'evidence':['Synthetic visible red card']}
    response = {'video_available':True,'audio_available':True,'segments':[visual],'warnings':[]}
    def finish(payload):
        return evaluate(policy, {'toolCall': {'name':'finish','args':payload}})['decision']
    assert finish(response) == 'allow'
    assert finish(dict(response, invented_link='speaker confirmed')) == 'deny'
    assert finish(dict(response, segments=[dict(visual, audible_content='Invented speech')])) == 'deny'
    policy['response_schema_sha256'] = '0' * 64
    assert finish(response) == 'deny'


def test_response_schema_path_cannot_escape_allowlist(tmp_path):
    media = tmp_path / 'sample.mp4'
    media.write_bytes(b'SYNTHETIC')
    with pytest.raises(ValueError, match='schema'):
        write_guard(tmp_path, media, response_schema='../../outside.schema.json')


def test_visual_guard_rejects_audio_claims_and_dialogue(tmp_path):
    media = tmp_path / 'sample.mp4'
    media.write_bytes(b'SYNTHETIC visual permission boundary')
    guard = write_guard(tmp_path, media, response_schema='agy-visual-response.schema.json')
    policy = json.loads(Path(guard['policy_path']).read_text())
    segment = {'segment_id':'clip-0001-v1','start_ms':0,'end_ms':1000,
               'observation_type':'visual','summary':'Synthetic red card',
               'visible_content':'A red card','audible_content':None,
               'confidence':0.9,'evidence':['Synthetic visible red card']}
    response = {'video_available':True,'segments':[segment],'warnings':[]}
    def finish(payload):
        return evaluate(policy, {'toolCall': {'name':'finish','args':payload}})['decision']
    assert finish(response) == 'allow'
    assert finish(dict(response, audio_available=True)) == 'deny'
    assert finish(dict(response, segments=[dict(segment, observation_type='dialogue', audible_content='speech')])) == 'deny'
    policy['response_schema_sha256'] = '0' * 64
    assert finish(response) == 'deny'

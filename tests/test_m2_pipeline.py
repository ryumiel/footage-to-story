"""Synthetic M2 integration: supplied decisions, provenance, resume, and subtitles."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.import_editorial import import_analysis, import_srt
from scripts.job_state import inspect_job, record_run
from scripts.map_subtitles import map_subtitles
from scripts.probe_manifest import build_manifest
from scripts.resolve_profile import resolve_profile
from scripts.validate_json import ROOT, load_json
from scripts.verify_locks import LockDecision, TrustedLockContext, capture_locks, digest, verify_locks


def test_synthetic_import_resume_profile_change_locks_and_subtitles(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('Synthetic integration requires media tools')
    job = 'synthetic-demo'
    source = tmp_path / 'synthetic.mov'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc2=size=64x48:rate=25:duration=10', '-f', 'lavfi', '-i',
                    'sine=frequency=440:sample_rate=48000:duration=10',
                    '-c:v', 'mpeg4', '-c:a', 'pcm_s16le', str(source)],
                   check=True, capture_output=True, timeout=30)
    second = tmp_path / 'synthetic-second.mov'
    shutil.copyfile(source, second)
    build_manifest(job, [('src-001', source), ('src-002', second)], tmp_path / 'inventory')
    paths = {'manifest': tmp_path / 'inventory/manifest.json'}
    for stage in ['analysis-request', 'analysis', 'selects', 'story-plan', 'edit-plan']:
        paths[stage] = tmp_path / f'{stage}.json'
        paths[stage].write_bytes((ROOT / f'examples/contracts/{stage}.json').read_bytes())
    import_analysis(paths['analysis'], paths['manifest'], paths['analysis-request'],
                    tmp_path / 'observations', supplier='SYNTHETIC_FIXTURE_ONLY')
    assert (tmp_path / 'observations/raw-input.bin').read_bytes() == paths['analysis'].read_bytes()
    paths['analysis'] = tmp_path / 'observations/analysis.json'
    srt = tmp_path / 'synthetic.srt'
    srt.write_text('1\n00:00:01,000 --> 00:00:05,000\nSynthetic quotation only\n')
    import_srt(srt, paths['manifest'], tmp_path / 'transcript-import', source_id='src-001',
               language='en', supplier='SYNTHETIC_FIXTURE_ONLY', content_kind='QUOTATION', time_origin_ms=0)
    transcript = tmp_path / 'transcript-import/transcript.json'
    profiles = tmp_path / 'profiles'
    shutil.copytree(ROOT / 'profiles', profiles)
    resolved = tmp_path / 'resolved-profile.json'
    resolved.write_text(json.dumps(resolve_profile('winery', job, profiles)))
    profile_inputs = {f'profile-{p.stem}': p for p in profiles.glob('*.yaml')}
    plan = load_json(paths['edit-plan'])
    plan['items'][0]['locked'] = True
    paths['edit-plan'].write_text(json.dumps(plan))
    lock_inputs = {s: paths[s] for s in ['manifest', 'edit-plan']}
    event = LockDecision('edit-plan', 'edit-001', 'LOCK', 'LOCK edit-plan edit-001', 'SYNTHETIC_FIXTURE_ONLY')
    locks = tmp_path / 'locks.json'
    locks.write_text(json.dumps(capture_locks(lock_inputs, [event])))
    context = TrustedLockContext(digest(locks), 'SYNTHETIC_FIXTURE_ONLY')
    state = tmp_path / 'state'
    record_run(state, job, 'manifest', {}, {'manifest': paths['manifest']})
    record_run(state, job, 'resolved-profile', profile_inputs, {'resolved-profile': resolved})
    record_run(state, job, 'analysis-request', {'manifest': paths['manifest']}, {'analysis-request': paths['analysis-request']})
    record_run(state, job, 'analysis', {s: paths[s] for s in ['manifest', 'analysis-request']}, {'analysis': paths['analysis']})
    record_run(state, job, 'transcript', {'manifest': paths['manifest'], 'raw-srt': srt}, {'transcript': transcript})
    inputs = {s: paths[s] for s in ['manifest', 'analysis-request', 'analysis']}
    inputs.update(profile_inputs, **{'resolved-profile': resolved})
    record_run(state, job, 'selects', inputs, {'selects': paths['selects']})
    inputs['selects'] = paths['selects']
    record_run(state, job, 'story-plan', inputs, {'story-plan': paths['story-plan']})
    inputs['story-plan'] = paths['story-plan']
    record_run(state, job, 'edit-plan', inputs, {}, 'INTERRUPTED')
    assert inspect_job(state, job)['stages']['edit-plan'] == 'INTERRUPTED'
    inputs['locks'] = locks
    record_run(state, job, 'edit-plan', inputs, {'edit-plan': paths['edit-plan']})
    mapping = map_subtitles(paths, [transcript], tmp_path / 'mapped')
    assert [(c['start_ms'], c['end_ms']) for c in mapping['entries']] == [(0, 4000)]
    subtitle_inputs = {s: paths[s] for s in paths}
    subtitle_inputs['transcript'] = transcript
    record_run(state, job, 'subtitle-map', subtitle_inputs, {'subtitle-map': tmp_path / 'mapped/subtitle-map.json'})
    current = inspect_job(state, job)
    assert all(current['stages'][s] == 'FRESH' for s in ['analysis', 'selects', 'edit-plan', 'subtitle-map'])
    base = profiles / 'base.yaml'
    base.write_text(base.read_text().replace('dialogue: 0.5', 'dialogue: 0.6'))
    stale = inspect_job(state, job)
    assert stale['stages']['analysis'] == stale['stages']['transcript'] == 'FRESH'
    assert stale['stages']['selects'] == stale['stages']['edit-plan'] == stale['stages']['subtitle-map'] == 'STALE'
    assert verify_locks(lock_inputs, locks, context)['status'] == 'PASS'
    assert stale['execution_authorized'] is False
    plan['items'][0]['reason'] = 'Attempted synthetic overwrite'
    paths['edit-plan'].write_text(json.dumps(plan))
    with pytest.raises(ValueError, match='removed or changed'):
        verify_locks(lock_inputs, locks, context)

"""Synthetic exporter verification; no real approval or Resolve project is created."""
from copy import deepcopy
from functools import partial
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest

from scripts import export_fcpxml as ex
from scripts import verify_approval as approval
from scripts.probe_manifest import build_manifest
from scripts.validate_json import load_json

qualified_export = partial(ex.export, media_validation="decoded")


@pytest.mark.parametrize('run', ['operational', 'operational-ntsc', 'operational-aac', 'operational-aac-ntsc'], indirect=True)
def test_routine_export_uses_metadata_without_frame_decode(run, monkeypatch):
    from scripts import verify_operational_media as operational
    commands = []
    original = operational.probe_to_file
    def record(command, *args):
        commands.append(command)
        assert '-show_frames' not in command and '-count_frames' not in command
        return original(command, *args)
    monkeypatch.setattr(operational, 'probe_to_file', record)
    monkeypatch.setattr(ex, 'verify_edit', lambda *a, **k: pytest.fail('Routine export must not run full decode'))
    report = ex.export(run[0], None, run[2], run[3], conversation_approval=live_event(run))
    assert commands
    assert report['status'] == 'PASS'
    assert report['verification_mode'] == 'OPERATIONAL_METADATA_ONLY'
    assert report['decoded_media_verification'] == 'NOT_RUN'
    media = load_json(run[3] / 'check/media/media-report.json')
    assert media['decoded_audio_verification'] == 'NOT_RUN'
    assert 'decoded_frame_count' not in media['sources'][0]['video']
    edit = load_json(run[3] / 'check/edit-report.json')
    assert edit['audio_cut_verification'] == 'NOT_RUN'
    assert edit['timeline_frame_count'] == 15
    assert (run[3] / 'timeline.fcpxml').exists()


@pytest.mark.parametrize('run', ['operational'], indirect=True)
@pytest.mark.parametrize('fault', ['source-hash', 'source-changed-during-probe', 'plan-after-approval'])
def test_routine_export_blocks_current_source_or_approval_changes(run, monkeypatch, fault):
    from scripts import verify_operational_media as operational
    event = live_event(run)
    if fault == 'source-hash':
        run[4].write_bytes(run[4].read_bytes() + b'synthetic mutation')
    elif fault == 'plan-after-approval':
        run[0]['edit-plan'].write_bytes(run[0]['edit-plan'].read_bytes() + b' ')
    else:
        original = operational.probe_to_file
        def changed(*args):
            result = original(*args)
            run[4].write_bytes(run[4].read_bytes() + b'synthetic mutation')
            return result
        monkeypatch.setattr(operational, 'probe_to_file', changed)
    with pytest.raises(ValueError):
        ex.export(run[0], None, run[2], run[3], conversation_approval=event)
    assert not run[3].exists()


@pytest.fixture
def dtd():
    path = Path(os.environ.get('FCPXML_DTD_PATH', 'artifacts/fcpxml-spec/FCPXMLv1_7.dtd'))
    if not path.is_file():
        pytest.skip('Official checksum-pinned DTD must be fetched explicitly for XML integration tests')
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == ex.DTD_SHA256
    return path


@pytest.fixture
def sample():
    plan = {'job_id': 'synthetic-export', 'timeline_name': 'Synthetic <timeline> & Unicode Ω',
            'timeline_fps': {'num': 30000, 'den': 1001}, 'items': [
                {'edit_id': 'cut-1', 'source_id': 'src-1', 'source_in_frame': 5, 'source_out_frame': 10,
                 'timeline_in_frame': 0, 'audio_policy': 'SOURCE', 'locked': False},
                {'edit_id': 'cut-2', 'source_id': 'src-1', 'source_in_frame': 20, 'source_out_frame': 30,
                 'timeline_in_frame': 5, 'audio_policy': 'MUTE', 'locked': False}]}
    media = {'status': 'PASS', 'sources': [{'source_id': 'src-1', 'path': '/synthetic media/a & Ω.mov',
                                         'video': {'decoded_frame_count': 30},
                                         'audio': {'channels': 1, 'sample_rate': 48000}}]}
    edit = {'status': 'PASS', 'timeline_frame_count': 15,
            'source_audio_format': {'sample_rate': 48000, 'channels': 1}}
    return plan, media, edit, {'src-1': (64, 48)}


def test_deterministic_exact_rationals_policy_refs_and_encoded_paths(sample):
    before = deepcopy(sample)
    xml = ex.render(*sample)
    assert xml == ex.render(*sample)
    assert sample == before
    root = ET.fromstring(xml)
    assert root.get('version') == '1.7'
    assert root.find('resources/format').get('frameDuration') == '1001/30000s'
    asset = root.find('resources/asset')
    assert asset.get('src') == 'file:///synthetic%20media/a%20%26%20%CE%A9.mov'
    clips = list(root.find('.//spine'))
    assert clips[0].get('start') == '1001/6000s'
    assert clips[1].get('offset') == '1001/6000s'
    assert clips[0].get('srcEnable') == 'all'
    assert clips[1].tag == 'video'
    assert clips[1].get('srcEnable') is None
    assert clips[0].get('ref') == clips[1].get('ref') == asset.get('id')
    assert root.find('.//project').get('name') == sample[0]['timeline_name']
    assert root.find('.//sequence').get('duration') == '1001/2000s'


def test_same_basename_different_sources_blocks_resolve_audio_aliasing(sample):
    plan, media, edit, rasters = sample
    plan['items'][1]['source_id'] = 'src-2'
    duplicate = deepcopy(media['sources'][0])
    duplicate.update(source_id='src-2', path='/another source/a & Ω.mov')
    media['sources'].append(duplicate)
    rasters['src-2'] = rasters['src-1']
    with pytest.raises(ValueError, match='Distinct source filenames'):
        ex.render(plan, media, edit, rasters)


@pytest.mark.parametrize('fault', ['edit-fail', 'media-fail', 'empty', 'locked', 'audio-rate', 'mixed-raster'])
def test_renderer_rejects_unsupported_verified_scope(sample, fault):
    plan, media, edit, rasters = sample
    if fault == 'edit-fail': edit['status'] = 'FAIL'
    if fault == 'media-fail': media['status'] = 'FAIL'
    if fault == 'empty': plan['items'] = []
    if fault == 'locked': plan['items'][0]['locked'] = True
    if fault == 'audio-rate': edit['source_audio_format']['sample_rate'] = 44100
    if fault == 'mixed-raster':
        plan['items'][1]['source_id'] = 'src-2'
        rasters['src-2'] = (128, 96)
    with pytest.raises(ValueError): ex.render(*sample)


@pytest.fixture
def visual():
    return {'streams': [{'index': 0, 'codec_type': 'video', 'width': 64, 'height': 48, 'sample_aspect_ratio': '1:1'}],
            'frames': [{'stream_index': 0, 'width': 64, 'height': 48, 'interlaced_frame': 0}]}


@pytest.mark.parametrize('fault', ['missing-sar', 'anamorphic', 'missing-width', 'rotation',
                                   'side-data', 'interlaced', 'varying-raster', 'unknown-scan'])
def test_geometry_rejects_unknown_or_unmapped_video(visual, fault):
    stream, frame = visual['streams'][0], visual['frames'][0]
    if fault == 'missing-sar': stream.pop('sample_aspect_ratio')
    if fault == 'anamorphic': stream['sample_aspect_ratio'] = '4:3'
    if fault == 'missing-width': stream.pop('width')
    if fault == 'rotation': stream['tags'] = {'rotate': '0'}
    if fault == 'side-data': stream['side_data_list'] = [{'rotation': 90}]
    if fault == 'interlaced': frame['interlaced_frame'] = 1
    if fault == 'varying-raster': frame['width'] = 128
    if fault == 'unknown-scan': frame.pop('interlaced_frame')
    with pytest.raises(ValueError): ex.geometry(visual, 0)


def test_valid_decoded_raster(visual):
    assert ex.geometry(visual, 0) == (64, 48)


def test_checksum_rejects_untrusted_dtd_before_parser(sample):
    with pytest.raises(ValueError, match='DTD checksum'):
        ex.validate_xml(ex.render(*sample), b'<!ENTITY malicious SYSTEM "file:///etc/passwd">')


def test_xml_official_dtd_validation_and_invalid_reference(sample, dtd):
    xml = ex.render(*sample)
    ex.validate_xml(xml, dtd.read_bytes())
    invalid = xml.replace(b'ref="r2"', b'ref="missing"')
    with pytest.raises(ValueError, match='DTD validation'):
        ex.validate_xml(invalid, dtd.read_bytes())


@pytest.fixture
def run(tmp_path, monkeypatch, dtd, request):
    variant = getattr(request, 'param', '25')
    ntsc = variant in {'ntsc', 'aac-ntsc'} or variant.endswith('-ntsc')
    media_path = tmp_path / 'Synthetic Ω & media.mov'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                    f'testsrc=size=64x48:rate={"30000/1001" if ntsc else "25"}',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000',
                    '-t', '1.001' if ntsc else '1', '-c:v', 'libx264' if variant.startswith('operational') else 'mpeg4', '-pix_fmt', 'yuv420p',
                    '-c:a', 'aac' if variant.startswith(('aac', 'operational-aac')) else 'pcm_s16le', str(media_path)], check=True, capture_output=True, timeout=30)
    build_manifest('synthetic-export', [('src-1', media_path)], tmp_path / 'inventory')
    plan = {'schema_version': '2.0.0', 'job_id': 'synthetic-export', 'revision': 'synthetic-r1',
            'timeline_name': 'Synthetic exporter acceptance', 'edit_mode': 'SEQUENTIAL_CUTS',
            'timeline_fps': {'num': 30000 if ntsc else 25, 'den': 1001 if ntsc else 1},
            'items': []}
    for number, (start, end, timeline, policy) in enumerate(((5, 10, 0, 'SOURCE'), (15, 25, 5, 'MUTE'))):
        plan['items'].append({'edit_id': f'cut-{number}', 'source_id': 'src-1', 'source_in_frame': start,
                              'source_out_frame': end, 'timeline_in_frame': timeline,
                              'audio_policy': policy, 'locked': False, 'reason': 'Synthetic cut'})
    plan_path = tmp_path / 'edit-plan.json'
    plan_path.write_text(json.dumps(plan))
    review = {'schema_version': '2.0.0', 'job_id': plan['job_id'], 'edit_plan_revision': plan['revision'],
              'edit_plan_sha256': hashlib.sha256(plan_path.read_bytes()).hexdigest(),
              'reviewer_type': 'HUMAN', 'reviewed_by': 'synthetic-export-test-only',
              'reviewed_at': '2026-01-01T00:00:00Z', 'status': 'APPROVED', 'issues': []}
    review_path = tmp_path / 'review.json'
    review_path.write_text(json.dumps(review))
    key = tmp_path / 'synthetic-test-key'
    subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True)
    subprocess.run(['/usr/bin/ssh-keygen', '-Y', 'sign', '-f', str(key), '-n', approval.NAMESPACE,
                    str(review_path)], check=True, capture_output=True)
    policy = ('synthetic-export-test-only namespaces="footage-to-story-review" ' + key.with_suffix('.pub').read_text()).encode()
    original = approval._trusted_bytes
    monkeypatch.setattr(approval, '_trusted_bytes', lambda path: policy if path == approval.TRUST_FILE else original(path))
    paths = {'manifest': tmp_path / 'inventory/manifest.json', 'edit-plan': plan_path, 'review': review_path}
    return paths, Path(str(review_path) + '.sig'), dtd, tmp_path / 'export', media_path


@pytest.mark.parametrize('run', ['25', 'ntsc', 'aac', 'aac-ntsc'], indirect=True)
def test_live_signed_synthetic_export_passes_dtd_and_fresh_gates(run):
    original_media_hash = hashlib.sha256(run[4].read_bytes()).hexdigest()
    report = qualified_export(*run[:4])
    assert report['status'] == 'PASS'
    assert report['timeline_frame_count'] == 15
    output = run[3]
    xml = (output / 'timeline.fcpxml').read_bytes()
    assert report['xml_sha256'] == hashlib.sha256(xml).hexdigest()
    ex.validate_xml(xml, run[2].read_bytes())
    root = ET.fromstring(xml)
    assert [item.tag for item in root.find('.//spine')] == ['asset-clip', 'video']
    assert root.find('resources/asset').get('src') == run[4].as_uri()
    assert load_json(output / 'check/edit-report.json')['items'][0]['audio_cut']['status'] == 'PASS'
    assert 'actual Resolve import/relinking/audio playback' in report['not_checked']
    assert hashlib.sha256(run[4].read_bytes()).hexdigest() == original_media_hash
    measured = load_json(output / 'check/media/media-report.json')['sources'][0]['audio']['timing']
    if measured.get('mode') == 'AAC_NATIVE':
        assert measured['application_decode_sync'] == 'NOT_RUN'
        assert not list(output.rglob('*.wav'))


def test_locked_synthetic_export_requires_live_context_and_fresh_binding(run):
    from scripts.verify_locks import LockDecision, TrustedLockContext, capture_locks, digest
    paths, _, dtd_path, output, _ = run
    plan = load_json(paths['edit-plan'])
    plan['items'][0]['locked'] = True
    paths['edit-plan'].write_text(json.dumps(plan))
    review = load_json(paths['review'])
    review['edit_plan_sha256'] = digest(paths['edit-plan'])
    paths['review'].write_text(json.dumps(review))
    event = approval.ConversationApproval(plan['job_id'], plan['revision'], digest(paths['edit-plan']),
                                         review['reviewed_by'], 'I approve', 'SYNTHETIC_TEST_ONLY')
    lock_paths = {s: p for s, p in paths.items() if s != 'review'}
    record = paths['edit-plan'].parent / 'locks.json'
    decision = LockDecision('edit-plan', 'cut-0', 'LOCK', 'LOCK edit-plan cut-0', 'SYNTHETIC_TEST_ONLY')
    record.write_text(json.dumps(capture_locks(lock_paths, [decision])))
    context = TrustedLockContext(digest(record), 'SYNTHETIC_TEST_ONLY')
    with pytest.raises(ValueError, match='locked-decision'):
        qualified_export(paths, None, dtd_path, output, conversation_approval=event)
    report = qualified_export(paths, None, dtd_path, output, conversation_approval=event,
                       lock_record=record, lock_context=context)
    assert report['locks']['protected_items'] == 1


@pytest.mark.parametrize('fault', ['signature', 'plan', 'source', 'dtd', 'existing-output'])
def test_export_refuses_tampering_without_publishing(run, fault):
    paths, signature, dtd, output, media = run
    if fault == 'signature': signature.write_bytes(b'untrusted')
    if fault == 'plan': paths['edit-plan'].write_bytes(paths['edit-plan'].read_bytes() + b'\n')
    if fault == 'source': media.write_bytes(media.read_bytes() + b'changed')
    if fault == 'dtd':
        dtd = output.parent / 'bad.dtd'
        dtd.write_bytes(b'untrusted')
    if fault == 'existing-output': output.mkdir()
    with pytest.raises((ValueError, FileExistsError)):
        qualified_export(paths, signature, dtd, output)
    assert not (output / 'timeline.fcpxml').exists()


@pytest.mark.parametrize('target', ['plan', 'source', 'signature', 'authority'])
def test_publication_boundary_changes_fail(run, monkeypatch, target):
    original = ex.validate_xml
    def mutate(*args):
        original(*args)
        if target == 'plan': run[0]['edit-plan'].write_bytes(run[0]['edit-plan'].read_bytes() + b'\n')
        if target == 'source': run[4].write_bytes(run[4].read_bytes() + b'changed')
        if target == 'signature': run[1].write_bytes(b'changed')
        if target == 'authority': monkeypatch.setattr(approval, '_trusted_bytes', lambda path: b'untrusted')
    monkeypatch.setattr(ex, 'validate_xml', mutate)
    with pytest.raises(ValueError): qualified_export(*run[:4])
    assert not run[3].exists()


def test_cli_does_not_accept_saved_pass_or_bypass_flags():
    with pytest.raises(SystemExit): ex.main(['--skip-approval'])


@pytest.mark.parametrize('scope', ['format-timecode', 'stream-timecode', 'cover-art', 'data-track'])
def test_source_clock_and_track_mappings_not_guessed(visual, scope):
    if scope == 'format-timecode': visual['format'] = {'tags': {'timecode': '01:00:00:00'}}
    if scope == 'stream-timecode': visual['streams'][0]['tags'] = {'timecode': '01:00:00:00'}
    if scope == 'cover-art': visual['streams'][0]['disposition'] = {'attached_pic': 1}
    if scope == 'data-track': visual['streams'].append({'index': 1, 'codec_type': 'data'})
    with pytest.raises(ValueError): ex.geometry(visual, 0)


def test_schema_integer_numeric_spelling_serializes_identically(sample):
    expected = ex.render(*sample)
    plan = sample[0]
    plan['timeline_fps']['num'] = float(plan['timeline_fps']['num'])
    for item in plan['items']:
        for key in ('source_in_frame', 'source_out_frame', 'timeline_in_frame'):
            item[key] = float(item[key])
    assert ex.render(*sample) == expected


def test_frame_display_orientation_is_not_ignored(visual):
    visual['frames'][0]['side_data_list'] = [{'side_data_type': '3x3 displaymatrix', 'rotation': 90}]
    with pytest.raises(ValueError, match='Decoded video frame side data'):
        ex.geometry(visual, 0)


@pytest.mark.parametrize('target', ['plan', 'source', 'authority'])
def test_changes_during_evidence_copy_never_publish_xml(run, monkeypatch, target):
    copy = ex.shutil.copytree
    def mutate(*args, **kwargs):
        result = copy(*args, **kwargs)
        if Path(args[1]) != run[3] / 'check':
            return result
        if target == 'plan': run[0]['edit-plan'].write_bytes(run[0]['edit-plan'].read_bytes() + b'\n')
        if target == 'source': run[4].write_bytes(run[4].read_bytes() + b'changed')
        if target == 'authority': monkeypatch.setattr(approval, '_trusted_bytes', lambda path: b'untrusted')
        return result
    monkeypatch.setattr(ex.shutil, 'copytree', mutate)
    with pytest.raises(ValueError): qualified_export(*run[:4])
    assert not (run[3] / 'timeline.fcpxml').exists()
    assert not (run[3] / 'export-report.json').exists()


def test_actual_frame_orientation_side_data_blocks_geometry(tmp_path):
    from scripts.verify_media import verify_media
    media = tmp_path / 'synthetic-rotated.mp4'
    subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
                    'testsrc=size=64x48:rate=25', '-t', '1', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-bf', '0', '-bsf:v',
                    'h264_metadata=display_orientation=insert:rotate=90',
                    '-movflags', 'frag_keyframe+empty_moov', str(media)],
                   check=True, capture_output=True, timeout=30)
    build_manifest('synthetic-orientation', [('rotated', media)], tmp_path / 'inventory')
    report = verify_media(tmp_path / 'inventory/manifest.json', tmp_path / 'scan')
    assert report['status'] == 'PASS'
    probe = load_json(tmp_path / 'scan/decode-0001.json')
    assert any(side.get('rotation') == 90 for frame in probe['frames'] for side in frame.get('side_data_list', []))
    with pytest.raises(ValueError, match='side data'):
        ex.geometry(probe, report['sources'][0]['video']['stream_index'])


def live_event(run):
    plan = load_json(run[0]['edit-plan'])
    review = load_json(run[0]['review'])
    return approval.ConversationApproval(plan['job_id'], plan['revision'],
                                        hashlib.sha256(run[0]['edit-plan'].read_bytes()).hexdigest(),
                                        review['reviewed_by'], 'I approve', 'Synthetic host event only')


def test_live_conversation_export_without_signing_policy(run, monkeypatch):
    event = live_event(run)
    monkeypatch.setattr(approval, '_trusted_bytes', lambda path: pytest.fail('No SSH trust policy needed'))
    report = qualified_export(run[0], None, run[2], run[3], conversation_approval=event)
    assert report['approval']['approval_method'] == 'TRUSTED_CONVERSATION'
    assert (run[3] / 'timeline.fcpxml').exists()


def test_export_scan_limits_forward_to_real_fresh_verifier(run, monkeypatch):
    observed = []
    verifier = ex.verify_edit
    def record(*args, **kwargs):
        observed.append(kwargs)
        return verifier(*args, **kwargs)
    monkeypatch.setattr(ex, 'verify_edit', record)
    report = qualified_export(run[0], None, run[2], run[3], conversation_approval=live_event(run),
                       media_timeout=30, media_max_bytes=2 * 1024 * 1024, media_workers=2)
    assert observed == [{'timeout': 30, 'max_bytes': 2 * 1024 * 1024, 'workers': 2}]
    assert report['media_scan_limits'] == {'timeout_seconds': 30, 'max_output_bytes': 2 * 1024 * 1024, 'workers': 2}
    assert load_json(run[3] / 'check/media/media-report.json')['status'] == 'PASS'


@pytest.mark.parametrize('limits', [{'media_timeout': 0}, {'media_timeout': -1},
    {'media_timeout': float('inf')}, {'media_timeout': float('nan')},
    {'media_timeout': True}, {'media_timeout': '60'}, {'media_max_bytes': 0},
    {'media_max_bytes': -1}, {'media_max_bytes': True}, {'media_max_bytes': 1.5}])
def test_invalid_export_scan_limits_fail_before_inputs(tmp_path, limits):
    output = tmp_path / 'export'
    with pytest.raises(ValueError, match='media scan limits'):
        qualified_export({}, None, tmp_path / 'missing.dtd', output, **limits)
    assert not output.exists()


@pytest.mark.parametrize('workers', [0, 5, True, 1.5])
def test_invalid_export_worker_budget_blocks_before_inputs(tmp_path, workers):
    with pytest.raises(ValueError, match='Decoder workers'):
        qualified_export({}, None, tmp_path/'missing.dtd', tmp_path/'export', media_workers=workers)


def test_export_without_live_event_or_signature_is_blocked(run):
    with pytest.raises(ValueError, match='Exactly one'):
        qualified_export(run[0], None, run[2], run[3])
    assert not run[3].exists()


def test_conversation_approved_plan_change_blocks_publication(run, monkeypatch):
    event = live_event(run)
    original = ex.validate_xml
    def mutate(*args):
        original(*args)
        run[0]['edit-plan'].write_bytes(run[0]['edit-plan'].read_bytes() + b'\n')
    monkeypatch.setattr(ex, 'validate_xml', mutate)
    with pytest.raises(ValueError, match='changed'):
        qualified_export(run[0], None, run[2], run[3], conversation_approval=event)
    assert not (run[3] / 'timeline.fcpxml').exists()


def test_geometry_rejects_multiple_audio_tracks():
    from scripts.export_fcpxml import geometry
    probe = {"streams": [{"index": 0, "codec_type": "video"},
                         {"index": 1, "codec_type": "audio"},
                         {"index": 2, "codec_type": "audio"}]}
    with pytest.raises(ValueError, match="Multiple audio tracks"):
        geometry(probe, 0)

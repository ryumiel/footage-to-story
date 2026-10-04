"""Stream-copy identity tests use generated media only."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts.prepare_resolve_media import digest, packet_records, prepare


def test_packet_identity_uses_rational_clocks():
    p = {'streams': [{'index': 1, 'start_pts': 0, 'time_base': '1/48000', 'extradata_hash': 'SHA256:abc'}],
         'packets': [{'stream_index': 1, 'pts': -1024, 'dts': -1024, 'duration': 1024,
                      'size': '32', 'data_hash': 'SHA256:def', 'flags': 'K_',
                      'side_data_list': [{'side_data_type': 'Skip Samples', 'skip_samples': 1024}]}]}
    same = deepcopy(p);same['streams'][0]['time_base'] = '1/96000'
    for k in ('pts', 'dts', 'duration'):same['packets'][0][k] *= 2
    assert packet_records(p, 1) == packet_records(same, 1)
    same['packets'][0]['side_data_list'][0]['skip_samples'] = 0
    assert packet_records(p, 1) != packet_records(same, 1)


@pytest.mark.parametrize('fault', ['origin', 'hash', 'missing-clock', 'empty'])
def test_unknown_packet_correspondence_fails(fault):
    p = {'streams': [{'index': 0, 'start_pts': 0, 'time_base': '1/48000', 'extradata_hash': 'SHA256:abc'}],
         'packets': [{'stream_index': 0, 'pts': 0, 'dts': 0, 'duration': 1024,
                      'size': '32', 'data_hash': 'SHA256:def'}]}
    if fault == 'origin':p['streams'][0]['start_pts'] = 1
    if fault == 'hash':p['streams'][0].pop('extradata_hash')
    if fault == 'missing-clock':p['packets'][0].pop('pts')
    if fault == 'empty':p['packets'] = []
    with pytest.raises(ValueError):packet_records(p, 0)


@pytest.fixture
def multiple_audio(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('FFmpeg required')
    source = tmp_path / 'original.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=64x48:rate=25:duration=2',
                    '-f', 'lavfi', '-i', 'sine=frequency=997:sample_rate=48000:duration=2',
                    '-f', 'lavfi', '-i', 'sine=frequency=1499:sample_rate=48000:duration=2',
                    '-map', '0:v', '-map', '1:a', '-map', '2:a', '-c:v', 'libx264', '-bf', '0',
                    '-bsf:v', 'filter_units=remove_types=6', '-c:a', 'aac', '-timecode', '17:31:50:02',
                    str(source)], check=True, capture_output=True)
    return source


@pytest.mark.parametrize('selector', [1, 2])
def test_real_stream_copy_preserves_selected_audio_and_removes_timecode(multiple_audio, tmp_path, selector):
    original = multiple_audio.read_bytes()
    report = prepare(multiple_audio, selector, tmp_path / 'prepared', expected_sha256=digest(multiple_audio))
    assert report['status'] == 'PASS'
    assert report['packet_counts'][0] == 50
    assert multiple_audio.read_bytes() == original
    p = json.loads((tmp_path / 'prepared/prepared-packets.json').read_text())
    assert [s['codec_type'] for s in p['streams']] == ['video', 'audio']
    assert all('timecode' not in s.get('tags', {}) for s in p['streams'])
    with pytest.raises(ValueError, match='already exists'):
        prepare(multiple_audio, selector, tmp_path / 'prepared', expected_sha256=digest(multiple_audio))


def test_invalid_selector_and_hash_leave_no_output(multiple_audio, tmp_path):
    out = tmp_path / 'prepared'
    with pytest.raises(ValueError, match='hash mismatch'):
        prepare(multiple_audio, 1, out, expected_sha256='0' * 64)
    assert not out.exists()
    with pytest.raises(ValueError, match='explicitly selected audio'):
        prepare(multiple_audio, 3, out, expected_sha256=digest(multiple_audio))
    assert not out.exists()


def test_hevc_completeness_normalization_preserves_all_parameter_bytes():
    from scripts.prepare_resolve_media import hevc_configuration
    header = bytes([1]) + bytes(21) + bytes([1])
    incomplete = header + bytes([32, 0, 1, 0, 3, 64, 1, 12])
    complete = header + bytes([160, 0, 1, 0, 3, 64, 1, 12])
    assert hevc_configuration(incomplete) == hevc_configuration(complete)
    changed = complete[:-1] + bytes([13])
    assert hevc_configuration(incomplete) != hevc_configuration(changed)
    with pytest.raises(ValueError):hevc_configuration(complete[:-1])
    with pytest.raises(ValueError):hevc_configuration(complete + bytes([0]))

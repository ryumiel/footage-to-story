"""Small synthetic metadata controls for routine export validation."""
from copy import deepcopy
import pytest
from scripts.verify_operational_media import reported_media, reported_sample_cut
from scripts.export_fcpxml import geometry
from fractions import Fraction


@pytest.fixture
def reported():
    probe = {'format': {'format_name': 'mov,mp4,m4a,3gp,3g2,mj2'}, 'streams': [
        {'index': 0, 'codec_type': 'video', 'codec_name': 'hevc', 'avg_frame_rate': '25/1',
         'r_frame_rate': '25/1', 'nb_frames': '25', 'time_base': '1/1000', 'start_pts': 0,
         'duration_ts': 1000, 'width': 64, 'height': 48, 'sample_aspect_ratio': '1:1',
         'field_order': 'progressive'},
        {'index': 1, 'codec_type': 'audio', 'codec_name': 'aac', 'profile': 'LC',
         'sample_rate': '48000', 'channels': 2, 'time_base': '1/48000',
         'start_pts': 0, 'duration_ts': 48000}]}
    source = {'frame_count': 25, 'fps_num': 25, 'fps_den': 1, 'cfr_status': 'UNKNOWN',
              'time_base': {'num': 1, 'den': 1000}, 'duration_ms': 1000,
              'audio_sample_rate': 48000, 'audio_channels': 2}
    return probe, source


def test_reported_mapping_never_claims_decoded_frames_or_audio(reported):
    result = reported_media(*reported)
    assert result['video']['reported_frame_count'] == 25
    assert result['video']['cfr_status'] == 'REPORTED_COMPATIBLE'
    assert 'decoded_frame_count' not in result['video']
    assert result['audio']['timing']['status'] == 'NOT_RUN'
    assert geometry(reported[0], 0, operational=True) == (64, 48)


@pytest.mark.parametrize('fault', ['origin', 'bool-origin', 'rate', 'count', 'duration', 'codec',
    'vfr', 'selector', 'audio-origin', 'audio-rate', 'audio-profile', 'missing-audio', 'extra-track'])
def test_inconsistent_or_unsupported_reported_mapping_blocks(reported, fault):
    probe, source = deepcopy(reported)
    video, audio = probe['streams']
    if fault == 'origin': video['start_pts'] = 1
    if fault == 'bool-origin': video['start_pts'] = False
    if fault == 'rate': video['r_frame_rate'] = '30/1'
    if fault == 'count': video.pop('nb_frames')
    if fault == 'duration': video['duration_ts'] = 999
    if fault == 'codec': video['codec_name'] = 'unknown'
    if fault == 'vfr': source['cfr_status'] = 'VFR'
    if fault == 'selector': source['audio_stream_index'] = 4
    if fault == 'audio-origin': audio['start_pts'] = 1
    if fault == 'audio-rate': audio['sample_rate'] = '44100'
    if fault == 'audio-profile': audio['profile'] = 'HE-AAC'
    if fault == 'missing-audio': probe['streams'].pop()
    if fault == 'extra-track': probe['streams'].append({'index': 2, 'codec_type': 'data'})
    with pytest.raises(ValueError): reported_media(probe, source)


def test_nominal_audio_geometry_is_metadata_only_and_bounds_checked(reported):
    audio = reported_media(*reported)['audio']
    result = reported_sample_cut(audio, 5, 10, 0, Fraction(25))
    assert result['status'] == 'METADATA_ONLY' and not result['issues']
    assert result['decoded_sample_verification'] == 'NOT_RUN'
    assert reported_sample_cut(audio, 5, 30, 0, Fraction(25))['issues'] == ['REPORTED_AUDIO_BOUND']
    assert 'NONINTEGER_NOMINAL_AUDIO_CUT' in reported_sample_cut(audio, 1, 2, 0, Fraction(30000,1001))['issues']


def test_operational_unspecified_raster_defaults_remain_distinct_from_decoded_proof(reported):
    probe = reported[0]
    probe['streams'][0].pop('sample_aspect_ratio')
    probe['streams'][0].pop('field_order')
    assert geometry(probe, 0, operational=True) == (64, 48)
    with pytest.raises(ValueError): geometry(probe, 0)
    probe['streams'][0]['sample_aspect_ratio'] = '4:3'
    with pytest.raises(ValueError): geometry(probe, 0, operational=True)
    probe['streams'][0]['sample_aspect_ratio'] = '1:1'
    probe['streams'][0]['field_order'] = 'tt'
    with pytest.raises(ValueError): geometry(probe, 0, operational=True)

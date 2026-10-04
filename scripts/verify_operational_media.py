"""Current source identity and reported metadata; never decode frame sequences."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile

try:
    from .check_integrity import check_documents
    from .probe_manifest import check_output_directory, file_signature, positive_integer, positive_rate, run_probe_command
    from .validate_json import load_json
    from .verify_media import decode_to_file as probe_to_file, rational
except ImportError:
    from check_integrity import check_documents
    from probe_manifest import check_output_directory, file_signature, positive_integer, positive_rate, run_probe_command
    from validate_json import load_json
    from verify_media import decode_to_file as probe_to_file, rational


def reported_media(probe: dict, source: dict) -> dict:
    streams = probe.get('streams', [])
    if not isinstance(streams, list) or not all(isinstance(s, dict) for s in streams):
        raise ValueError('Reported streams required')
    indices = [s.get('index') for s in streams]
    if any(type(i) is not int or i < 0 for i in indices) or len(set(indices)) != len(indices):
        raise ValueError('Distinct nonnegative stream indices required')
    videos = [s for s in streams if s.get('codec_type') == 'video']
    audios = [s for s in streams if s.get('codec_type') == 'audio']
    if len(videos) != 1 or len(audios) > 1 or len(streams) != len(videos) + len(audios):
        raise ValueError('Operational mapping requires one video and at most one audio stream')
    if probe.get('format', {}).get('format_name') != 'mov,mp4,m4a,3gp,3g2,mj2':
        raise ValueError('Operational export supports self-contained MOV/MP4 only')
    video = videos[0]
    fps, nominal = positive_rate(video.get('avg_frame_rate')), positive_rate(video.get('r_frame_rate'))
    count, base = positive_integer(video.get('nb_frames')), positive_rate(video.get('time_base'))
    if (video.get('codec_name') not in {'h264', 'hevc'} or fps is None or fps != nominal
            or count is None or base is None or type(video.get('start_pts')) is not int or video['start_pts'] != 0
            or source.get('cfr_status') == 'VFR'):
        raise ValueError('Known zero-origin reported H.264/HEVC frame grid required; no CFR claim is measured')
    if (source.get('frame_count') != count or source.get('fps_num') is None
            or Fraction(int(source['fps_num']), int(source['fps_den'])) != fps
            or source.get('time_base') != rational(base)):
        raise ValueError('Current reported video metadata differs from inventory')
    duration_ticks = positive_integer(video.get('duration_ts'))
    if duration_ticks is None or duration_ticks * base != Fraction(count, 1) / fps:
        raise ValueError('Reported frame count/duration/grid disagree')
    if source.get('duration_ms') != math.ceil(duration_ticks * base * 1000):
        raise ValueError('Current reported video duration differs from inventory')
    if source.get('proxy_path') is not None:
        raise ValueError('Proxy mapping unsupported')
    audio = None
    if audios:
        stream = audios[0]
        if source.get('audio_stream_index', stream['index']) != stream['index']:
            raise ValueError('Selected audio stream differs from prepared single-stream mapping')
        rate, channels = positive_integer(stream.get('sample_rate')), positive_integer(stream.get('channels'))
        audio_base = positive_rate(stream.get('time_base'))
        ticks = positive_integer(stream.get('duration_ts'))
        codec = stream.get('codec_name', '')
        if (rate != 48000 or channels not in (1, 2) or stream.get('start_pts') != 0
                or type(stream.get('start_pts')) is not int or audio_base is None or ticks is None
                or not (codec.startswith('pcm_') or (codec == 'aac' and stream.get('profile') == 'LC'))):
            raise ValueError('Known zero-origin 48 kHz mono/stereo PCM or AAC-LC metadata required')
        if (source.get('audio_sample_rate'), source.get('audio_channels')) != (rate, channels):
            raise ValueError('Current reported audio metadata differs from inventory')
        audio = {'stream_index': stream['index'], 'sample_rate': rate, 'channels': channels,
                 'reported_duration_seconds': rational(ticks * audio_base), 'codec_name': codec,
                 'timing': {'status': 'NOT_RUN', 'mode': 'REPORTED_METADATA'}}
    elif source.get('audio_sample_rate') is not None or source.get('audio_channels') is not None:
        raise ValueError('Inventory audio is absent')
    return {'video': {'stream_index': video['index'], 'reported_frame_count': count,
                      'fps': rational(fps), 'cfr_status': 'REPORTED_COMPATIBLE',
                      'origin_seconds': rational(Fraction(0))},
            'audio': audio, 'issues': [], 'status': 'PASS'}


def verify_operational_media(manifest_path: Path, output: Path, ffprobe: str = 'ffprobe',
                             timeout: float = 60, max_bytes: int = 64 * 1024 * 1024) -> dict:
    if (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0
            or type(max_bytes) is not int or max_bytes <= 0):
        raise ValueError("Finite positive operational probe limits required")
    output = check_output_directory(output)
    manifest_path = manifest_path.expanduser().resolve(strict=True)
    initial = file_signature(manifest_path)
    raw_manifest = manifest_path.read_bytes()
    manifest = load_json(manifest_path)
    errors = check_documents({'manifest': manifest})
    if errors:
        raise ValueError(f'Invalid manifest: {errors[0].message}')
    executable = shutil.which(ffprobe)
    if executable is None:
        raise ValueError('ffprobe unavailable')
    executable = str(Path(executable).resolve())
    version = run_probe_command([executable, '-version'], timeout).stdout
    paths = [Path(s['path']).expanduser() for s in manifest['sources']]
    if any(not p.is_absolute() for p in paths):
        raise ValueError('Absolute source paths required')
    paths = [p.resolve(strict=True) for p in paths]
    signatures = [file_signature(p) for p in paths]
    if any(not p.is_file() for p in paths) or len({s[:2] for s in signatures}) != len(paths):
        raise ValueError('Distinct readable regular media files required')
    report = {'job_id': manifest['job_id'], 'manifest_sha256': hashlib.sha256(raw_manifest).hexdigest(),
              'status': 'PASS', 'verification_mode': 'OPERATIONAL_METADATA_ONLY', 'sources': [],
              'decoded_video_verification': 'NOT_RUN', 'decoded_audio_verification': 'NOT_RUN',
              'not_checked': ['decoded frame count/CFR/raster stability', 'AAC priming and sample continuity',
                              'measured real-source synchronization', 'audible listening', 'approval', 'export']}
    with tempfile.TemporaryDirectory(prefix='footage-operational-check-') as temporary:
        directory = Path(temporary)
        for number, (source, path, before) in enumerate(zip(manifest['sources'], paths, signatures), 1):
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    digest.update(chunk)
            if source.get('content_sha256') != digest.hexdigest():
                raise ValueError('Current source SHA-256 differs from inventory')
            command = [executable, '-v', 'error', '-protocol_whitelist', 'file', '-format_whitelist',
                       'mov', '-enable_drefs', '0', '-show_streams', '-show_format', '-of', 'json', str(path)]
            raw_path = directory / f'probe-{number:04d}.json'
            stderr = probe_to_file(command, raw_path, timeout, max_bytes)
            if stderr:
                raise ValueError('Metadata probe reported an error')
            measured = reported_media(load_json(raw_path), source)
            if file_signature(path) != before:
                raise ValueError('Source changed during operational verification')
            report['sources'].append({'source_id': source['source_id'], 'path': str(path),
                                      'content_sha256': digest.hexdigest(), **measured})
            (directory / f'probe-{number:04d}-provenance.json').write_text(json.dumps({
                'command': command, 'ffprobe_version': version, 'stat_signature': list(before),
                'content_sha256': digest.hexdigest(), 'verification_mode': 'OPERATIONAL_METADATA_ONLY'}, indent=2)+'\n')
        if (file_signature(manifest_path) != initial or manifest_path.read_bytes() != raw_manifest
                or any(file_signature(p) != s for p, s in zip(paths, signatures))):
            raise ValueError('Manifest or media changed during operational checks')
        shutil.copytree(directory, output)
        (output / 'media-report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def reported_sample_cut(audio: dict, source_in: int, source_out: int, timeline_in: int, fps: Fraction) -> dict:
    coordinates = [Fraction(frame * audio['sample_rate'], 1) / fps
                   for frame in (source_in, source_out, timeline_in)]
    duration = audio['reported_duration_seconds']
    issues = []
    if any(c.denominator != 1 for c in coordinates):
        issues.append('NONINTEGER_NOMINAL_AUDIO_CUT')
    if Fraction(source_out, 1) / fps > Fraction(duration['num'], duration['den']):
        issues.append('REPORTED_AUDIO_BOUND')
    return {'status': 'METADATA_ONLY', 'policy': 'SOURCE', 'issues': issues,
            'application_decode_sync': 'NOT_RUN', 'decoded_sample_verification': 'NOT_RUN'}

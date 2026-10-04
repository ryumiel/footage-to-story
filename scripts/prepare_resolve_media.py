"""Prepare bounded, packet-identical Resolve assets without modifying originals.

This removes unused streams and container timecode. It does not authorize an edit,
replace decoded edit gates, or implement arbitrary proxy/timestamp mappings.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

try:
    from .probe_manifest import check_output_directory, file_signature
except ImportError:
    from probe_manifest import check_output_directory, file_signature


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def hevc_configuration(data: bytes) -> str:
    """Ignore only hvcC array-completeness flags; parameter-set bytes stay exact."""
    if len(data) < 23 or data[0] != 1:
        raise ValueError('Known HEVC configuration record required')
    result = bytearray(data)
    cursor = 23
    for _ in range(data[22]):
        if cursor + 3 > len(data) or (data[cursor] & 63) not in (32, 33, 34):
            raise ValueError('Only complete VPS/SPS/PPS array framing supported')
        result[cursor] &= 127
        count = int.from_bytes(data[cursor + 1:cursor + 3], 'big')
        cursor += 3
        for _ in range(count):
            if cursor + 2 > len(data):
                raise ValueError('Truncated HEVC parameter-set length')
            length = int.from_bytes(data[cursor:cursor + 2], 'big')
            cursor += 2
            if not length or cursor + length > len(data):
                raise ValueError('Truncated HEVC parameter-set payload')
            cursor += length
    if cursor != len(data):
        raise ValueError('Unexplained HEVC configuration bytes')
    return hashlib.sha256(result).hexdigest()


def packet_records(probe: dict, index: int) -> tuple[dict, list]:
    """Compare codec configuration, exact presentation/decode clocks and payloads."""
    stream = next(s for s in probe['streams'] if s['index'] == index)
    base = Fraction(stream['time_base'])
    if base <= 0 or stream.get('start_pts') != 0:
        raise ValueError('Only known zero-origin selected streams are supported')
    configuration = {k: stream.get(k) for k in (
        'codec_type', 'codec_name', 'profile', 'width', 'height', 'pix_fmt',
        'sample_aspect_ratio', 'sample_rate', 'channels', 'channel_layout',
        'extradata_size', 'extradata_hash', 'initial_padding')}
    if stream.get('codec_name') == 'hevc':
        configuration['extradata_hash'] = stream.get('hevc_parameter_configuration_sha256')
    if not configuration['extradata_hash']:
        raise ValueError('Known codec configuration hash required')
    packets = []
    for p in probe['packets']:
        if p['stream_index'] != index:
            continue
        if not p.get('data_hash') or any(type(p.get(k)) is not int for k in ('pts', 'dts', 'duration')):
            raise ValueError('Known packet payload hashes and integer clocks required')
        packets.append([str(Fraction(p[k]) * base) for k in ('pts', 'dts', 'duration')] +
                       [p['data_hash'], p['size'], p.get('flags'), p.get('side_data_list', [])])
    if not packets:
        raise ValueError('Selected stream has no packets')
    return configuration, packets


def probe(path: Path, directory: Path, name: str, timeout: float, max_bytes: int) -> dict:
    command = ['ffprobe', '-v', 'error', '-show_streams', '-show_format',
               '-show_packets', '-show_data_hash', 'sha256', '-of', 'json', str(path)]
    target = directory / name
    with target.open('xb') as out, tempfile.TemporaryFile() as err:
        result = subprocess.run(command, stdout=out, stderr=err, timeout=timeout)
        err.seek(0)
        diagnostic = err.read(4096)
    if result.returncode or diagnostic or target.stat().st_size > max_bytes:
        raise ValueError('Packet scan failed or exceeded output budget')
    result = json.loads(target.read_text())
    for stream in result['streams']:
        if stream.get('codec_name') != 'hevc' or stream.get('disposition', {}).get('attached_pic'):
            continue
        raw = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', str(stream['index']),
                                       '-show_entries', 'stream=extradata', '-show_data', '-of', 'json', str(path)],
                                      timeout=timeout)
        if len(raw) > 64 * 1024:
            raise ValueError('HEVC configuration evidence exceeds budget')
        (directory / (name + '.hevc-configuration.json')).write_bytes(raw)
        hexdump = json.loads(raw)['streams'][0]['extradata']
        data = bytes.fromhex(''.join(line.split(':', 1)[1].split('  ')[0].replace(' ', '')
                                    for line in hexdump.splitlines() if ':' in line))
        stream['hevc_parameter_configuration_sha256'] = hevc_configuration(data)
    return result


def prepare(source: Path, audio_index: int, output: Path, *, expected_sha256: str,
            timeout: float = 120, max_bytes: int = 64 * 1024 * 1024) -> dict:
    if type(audio_index) is not int or audio_index < 0:
        raise ValueError('Explicit nonnegative audio stream index required')
    if not math.isfinite(timeout) or timeout <= 0 or type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError('Finite positive resource limits required')
    if len(expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError('Expected source SHA-256 required')
    source = source.resolve(strict=True)
    output = check_output_directory(output)
    if source.is_relative_to(output):
        raise ValueError('Output must not contain source')
    before = file_signature(source)
    if digest(source) != expected_sha256:
        raise ValueError('Original source hash mismatch')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.resolve-media-', dir=output.parent) as tmp:
        directory = Path(tmp)
        original = probe(source, directory, 'original-packets.json', timeout, max_bytes)
        videos = [s for s in original['streams'] if s['codec_type'] == 'video'
                  and not s.get('disposition', {}).get('attached_pic')]
        audio = [s for s in original['streams'] if s['index'] == audio_index and s['codec_type'] == 'audio']
        if len(videos) != 1 or len(audio) != 1 or videos[0]['codec_name'] not in {'h264', 'hevc'}:
            raise ValueError('One H.264/HEVC video and explicitly selected audio required')
        if audio[0]['codec_name'] != 'aac' or audio[0].get('profile') != 'LC' or audio[0].get('sample_rate') != '48000' or audio[0].get('channels') not in (1, 2):
            raise ValueError('Only AAC-LC 48 kHz mono/stereo preparation supported')
        original_records = [packet_records(original, s['index']) for s in (videos[0], audio[0])]
        target = directory / 'resolve-source.mp4'
        command = ['ffmpeg', '-v', 'error', '-nostdin', '-n', '-copyts', '-i', str(source),
                   '-map', f"0:{videos[0]['index']}", '-map', f'0:{audio_index}',
                   '-c', 'copy', '-tag:v', videos[0]['codec_tag_string'], '-map_metadata', '-1', '-map_chapters', '-1',
                   '-metadata:s:v:0', 'timecode=', '-write_tmcd', '0',
                   '-avoid_negative_ts', 'disabled', str(target)]
        result = subprocess.run(command, capture_output=True, timeout=timeout)
        if result.returncode or result.stderr:
            raise ValueError('Stream-copy preparation reported errors')
        staged = probe(target, directory, 'prepared-packets.json', timeout, max_bytes)
        if [s['codec_type'] for s in staged['streams']] != ['video', 'audio']:
            raise ValueError('Prepared asset contains unexpected tracks')
        if any('timecode' in s.get('tags', {}) for s in staged['streams']) or 'timecode' in staged.get('format', {}).get('tags', {}):
            raise ValueError('Prepared asset retained embedded timecode')
        for index, expected in enumerate(original_records):
            if packet_records(staged, index) != expected:
                raise ValueError('Prepared codec configuration, packet bytes or clocks changed')
        if digest(source) != expected_sha256 or file_signature(source) != before:
            raise ValueError('Original source changed during preparation')
        report = {'status': 'PASS', 'scope': 'ZERO_ORIGIN_PACKET_IDENTICAL_STREAM_COPY',
                  'source_path': str(source), 'source_sha256': expected_sha256,
                  'source_video_stream_index': videos[0]['index'], 'source_audio_stream_index': audio_index,
                  'prepared_path': str(output / target.name), 'prepared_sha256': digest(target),
                  'prepared_video_stream_index': 0, 'prepared_audio_stream_index': 1,
                  'packet_counts': [len(r[1]) for r in original_records],
                  'original_timecode_tags': [s.get('tags', {}).get('timecode') for s in original['streams']],
                  'command': command[:-1] + [str(output / target.name)],
                  'hevc_configuration_rule': 'Only array-completeness bits may change; VPS/SPS/PPS and other configuration bytes match',
                  'packet_payload_and_clock_identity': 'PASS', 'original_byte_preservation': 'PASS',
                  'decoded_edit_verification': 'NOT_RUN', 'resolve_playback': 'NOT_RUN',
                  'human_exact_plan_approval': 'NOT_RUN'}
        (directory / 'preparation-report.json').write_text(json.dumps(report, indent=2) + '\n')
        if output.exists():
            raise ValueError('Output appeared during preparation')
        shutil.copytree(directory, output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--audio-stream-index', type=int, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=120)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.audio_stream_index, args.output,
                             expected_sha256=args.source_sha256, timeout=args.timeout), indent=2))


if __name__ == '__main__':
    main()

"""Deterministic bounded FCPXML 1.7 export with fresh edit and signed approval gates."""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

try:
    from .check_integrity import STAGES
    from .fetch_fcpxml_dtd import DTD_SHA256
    from .probe_manifest import check_output_directory, file_signature, positive_integer
    from .validate_json import ROOT, load_json
    from .verify_approval import _read, verify_approval, _trusted_bytes
    from .verify_edit import verify_edit
except ImportError:
    from check_integrity import STAGES
    from fetch_fcpxml_dtd import DTD_SHA256
    from probe_manifest import check_output_directory, file_signature, positive_integer
    from validate_json import ROOT, load_json
    from verify_approval import _read, verify_approval, _trusted_bytes
    from verify_edit import verify_edit

XMLLINT = Path('/usr/bin/xmllint')


def time_value(value: Fraction) -> str:
    return f'{value.numerator}/{value.denominator}s' if value.denominator != 1 else f'{value.numerator}s'


def geometry(probe: dict, stream_index: int) -> tuple[int, int]:
    if any(s.get('codec_type') not in {'video', 'audio'} or s.get('disposition', {}).get('attached_pic')
           for s in probe['streams']):
        raise ValueError('Additional tracks/cover art unsupported by exporter')
    if any('timecode' in s.get('tags', {}) for s in probe['streams']) or 'timecode' in probe.get('format', {}).get('tags', {}):
        raise ValueError('Embedded source timecode mapping unsupported')
    stream = next(s for s in probe['streams'] if s['index'] == stream_index)
    width, height = positive_integer(stream.get('width')), positive_integer(stream.get('height'))
    if width is None or height is None or stream.get('sample_aspect_ratio') != '1:1':
        raise ValueError('Known square-pixel raster required')
    if stream.get('side_data_list') or 'rotate' in stream.get('tags', {}):
        raise ValueError('Video side data/rotation mapping unsupported')
    for frame in probe['frames']:
        if frame['stream_index'] != stream_index:
            continue
        if frame.get('side_data_list'):
            raise ValueError('Decoded video frame side data/rotation mapping unsupported')
        if (frame.get('width'), frame.get('height'), frame.get('interlaced_frame')) != (width, height, 0):
            raise ValueError('Stable decoded progressive raster required')
    return width, height


def render(plan: dict, media: dict, edit: dict, rasters: dict) -> bytes:
    """Internal serializer for trusted fresh gate results, not saved report input."""
    if edit['status'] != 'PASS' or media['status'] != 'PASS' or not plan['items']:
        raise ValueError('Nonempty verified edit required')
    if any(item['locked'] for item in plan['items']):
        raise ValueError('Prior locked-decision verification is not implemented')
    used = list(dict.fromkeys(item['source_id'] for item in plan['items']))
    shapes = {rasters[source_id] for source_id in used}
    if len(shapes) != 1:
        raise ValueError('Mixed source rasters/scaling unsupported')
    width, height = next(iter(shapes))
    rate = Fraction(int(plan['timeline_fps']['num']), int(plan['timeline_fps']['den']))
    audio_format = edit.get('source_audio_format')
    if audio_format and audio_format['sample_rate'] != 48000:
        raise ValueError('Exporter currently supports retained 48000 Hz audio only')
    root = ET.Element('fcpxml', version='1.7')
    resources = ET.SubElement(root, 'resources')
    ET.SubElement(resources, 'format', id='r1', frameDuration=time_value(1 / rate),
                  width=str(width), height=str(height), fieldOrder='progressive', paspH='1', paspV='1')
    measured = {s['source_id']: s for s in media['sources']}
    refs = {source_id: f'r{number + 2}' for number, source_id in enumerate(used)}
    for source_id in used:
        source = measured[source_id]
        attributes = {'id': refs[source_id], 'name': source_id,
                      'src': Path(source['path']).as_uri(), 'start': '0s', 'hasVideo': '1',
                      'format': 'r1', 'duration': time_value(Fraction(source['video']['decoded_frame_count'], 1) / rate),
                      'hasAudio': '1' if source['audio'] else '0'}
        if source['audio']:
            attributes.update(audioSources='1', audioChannels=str(source['audio']['channels']),
                              audioRate=str(source['audio']['sample_rate']))
        ET.SubElement(resources, 'asset', attributes)
    library = ET.SubElement(root, 'library')
    event = ET.SubElement(library, 'event', name=plan['job_id'])
    project = ET.SubElement(event, 'project', name=plan['timeline_name'])
    attributes = {'format': 'r1', 'duration': time_value(Fraction(edit['timeline_frame_count'], 1) / rate),
                  'tcStart': '0s', 'tcFormat': 'NDF'}
    if audio_format:
        attributes.update(audioLayout='mono' if audio_format['channels'] == 1 else 'stereo', audioRate='48k')
    sequence = ET.SubElement(project, 'sequence', attributes)
    spine = ET.SubElement(sequence, 'spine')
    for item in plan['items']:
        ET.SubElement(spine, 'asset-clip', name=item['edit_id'], ref=refs[item['source_id']],
                      offset=time_value(Fraction(int(item['timeline_in_frame']), 1) / rate),
                      start=time_value(Fraction(int(item['source_in_frame']), 1) / rate),
                      duration=time_value(Fraction(int(item['source_out_frame']) - int(item['source_in_frame']), 1) / rate),
                      srcEnable='all' if item['audio_policy'] == 'SOURCE' else 'video')
    ET.indent(root, space='  ')
    return b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + ET.tostring(root, encoding='utf-8') + b'\n'


def validate_xml(xml: bytes, dtd: bytes) -> None:
    if hashlib.sha256(dtd).hexdigest() != DTD_SHA256:
        raise ValueError('DTD checksum mismatch')
    _trusted_bytes(XMLLINT)
    with tempfile.TemporaryDirectory(prefix='footage-xml-') as temporary:
        directory = Path(temporary)
        xml_path, dtd_path = directory / 'timeline.fcpxml', directory / 'spec.dtd'
        xml_path.write_bytes(xml)
        dtd_path.write_bytes(dtd)
        result = subprocess.run([str(XMLLINT), '--nonet', '--noout', '--dtdvalid', str(dtd_path), str(xml_path)],
                                capture_output=True, timeout=15, env={'PATH': '/usr/bin:/bin', 'LC_ALL': 'C'})
        if result.returncode:
            raise ValueError('Generated XML failed official DTD validation')


def export(paths: dict[str, Path], signature: Path, dtd_path: Path, output: Path) -> dict:
    output = check_output_directory(output)
    if not {'manifest', 'edit-plan', 'review'} <= paths.keys() or paths.keys() - set(STAGES):
        raise ValueError('Manifest, edit plan, review, and known stages required')
    raw = {stage: _read(path) for stage, path in paths.items()}
    signature_raw, dtd = _read(signature), _read(dtd_path)
    with tempfile.TemporaryDirectory(prefix='footage-export-') as temporary:
        directory = Path(temporary)
        frozen = {}
        for stage, data in raw.items():
            frozen[stage] = directory / f'{stage}.json'
            frozen[stage].write_bytes(data)
        sig_path = directory / 'review.sig'
        sig_path.write_bytes(signature_raw)
        approval = verify_approval(frozen['edit-plan'], frozen['review'], sig_path)
        if output.is_relative_to(ROOT):
            parts = output.relative_to(ROOT).parts
            if len(parts) < 3 or parts[:2] != ('artifacts', approval['job_id']):
                raise ValueError('Repository exports require artifacts/<job_id>/<new-run>')
        edit = verify_edit(frozen, directory / 'check')
        if edit['status'] != 'PASS':
            raise ValueError('Fresh edit/media checks failed')
        if edit['input_sha256']['edit-plan'] != approval['edit_plan_sha256'] or edit['input_sha256']['review'] != approval['review_sha256']:
            raise ValueError('Approval/edit input binding mismatch')
        media_dir = directory / 'check' / 'media'
        media = load_json(media_dir / 'media-report.json')
        used = {item['source_id'] for item in load_json(frozen['edit-plan'])['items']}
        rasters = {source['source_id']: geometry(load_json(media_dir / f'decode-{number:04d}.json'), source['video']['stream_index'])
                   for number, source in enumerate(media['sources'], 1) if source['source_id'] in used}
        xml = render(load_json(frozen['edit-plan']), media, edit, rasters)
        validate_xml(xml, dtd)
        def publication_guard():
            # Run both before output creation and after potentially long copying.
            if any(_read(paths[stage]) != data for stage, data in raw.items()) or _read(signature) != signature_raw or _read(dtd_path) != dtd:
                raise ValueError('Export inputs changed during execution')
            if verify_approval(frozen['edit-plan'], frozen['review'], sig_path) != approval:
                raise ValueError('Signing authority changed during execution')
            for number, source in enumerate(media['sources'], 1):
                provenance = load_json(media_dir / f'decode-{number:04d}-provenance.json')
                if list(file_signature(Path(source['path']))) != provenance['stat_signature']:
                    raise ValueError('Media changed before export publication')

        publication_guard()
        report = {'status': 'PASS', 'job_id': edit['job_id'], 'revision': edit['revision'],
                  'fcpxml_version': '1.7', 'xml_sha256': hashlib.sha256(xml).hexdigest(),
                  'dtd_sha256': DTD_SHA256, 'approval': approval,
                  'timeline_frame_count': edit['timeline_frame_count'],
                  'not_checked': ['actual Resolve import/relinking/audio playback', 'color management', 'prior locks']}
        output.mkdir(parents=True, exist_ok=False)
        shutil.copytree(directory / 'check', output / 'check')
        report_pending = output / 'export-report.json.tmp'
        report_pending.write_text(json.dumps(report, indent=2) + '\n')
        pending = output / 'timeline.fcpxml.tmp'
        pending.write_bytes(xml)
        publication_guard()
        os.link(report_pending, output / 'export-report.json')
        report_pending.unlink()
        os.link(pending, output / 'timeline.fcpxml')
        pending.unlink()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for stage in STAGES:
        parser.add_argument(f'--{stage}', type=Path, required=stage in {'manifest', 'edit-plan', 'review'})
    parser.add_argument('--signature', type=Path, required=True)
    parser.add_argument('--dtd', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    paths = {stage: path for stage in STAGES if (path := getattr(args, stage.replace('-', '_'))) is not None}
    try:
        report = export(paths, args.signature, args.dtd, args.output_dir)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f'EXPORT_ERROR: {exc}', file=sys.stderr)
        return 2
    print(f"EXPORT_{report['status']}: {args.output_dir.resolve() / 'timeline.fcpxml'}")
    print('Resolve import and color management NOT_CHECKED')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

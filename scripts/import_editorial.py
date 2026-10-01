"""Import supplied analysis/SRT as data, preserving exact bytes and declared origin."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
try:
    from .validate_json import ROOT, build_validator, _unique_object, _reject_constant
    from .check_integrity import check_documents
    from .verify_approval import _read
except ImportError:
    from validate_json import ROOT, build_validator, _unique_object, _reject_constant
    from check_integrity import check_documents
    from verify_approval import _read


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def parse(raw: bytes):
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def validate(name: str, document: dict) -> None:
    build_validator(ROOT / f'schemas/2.0.0/{name}.schema.json').validate(document)


def output_path(output: Path, job_id: str) -> Path:
    output = output.expanduser().resolve()
    if output.exists():
        raise ValueError('Output must be a new directory')
    if output == ROOT or ROOT in output.parents:
        relative = output.relative_to(ROOT)
        if len(relative.parts) < 3 or relative.parts[:2] not in [('work', job_id), ('artifacts', job_id)]:
            raise ValueError('Repository runtime output requires work/job_id or artifacts/job_id')
    return output


def publish(output: Path, job_id: str, files: dict[str, bytes], inputs: dict[Path, bytes], *, final_guard=None) -> None:
    """Publish a complete directory without replacing prior runs; refuse other writers."""
    output = output_path(output, job_id)
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = output.parent / ('.' + output.name + '.lock')
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with tempfile.TemporaryDirectory(prefix='.' + output.name + '-', dir=output.parent) as tmp:
            pending = Path(tmp) / 'run'
            pending.mkdir()
            for name, raw in files.items():
                (pending / name).write_bytes(raw)
            if any(_read(path) != raw for path, raw in inputs.items()):
                raise ValueError('Input changed during operation')
            if output.exists():
                raise ValueError('Output already exists')
            if final_guard is not None:
                final_guard()
            os.rename(pending, output)
    finally:
        os.close(fd)
        lock.unlink()


def encoded(document: dict) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + '\n').encode('utf-8')


def provenance(job, fmt, supplier, raw, bindings):
    document = {'schema_version':'2.0.0','job_id':job,'format':fmt,'supplier':supplier,
                'raw_sha256':sha(raw),'raw_name':'raw-input.bin','inputs':bindings,
                'claim':'SUPPLIER_DECLARED_ORIGIN; NOT AUTHENTICATED'}
    validate('provenance', document)
    return document


def import_analysis(analysis_path: Path, manifest_path: Path, request_path: Path,
                    output: Path, *, supplier: str) -> dict:
    inputs = {Path(p).resolve():_read(Path(p)) for p in [analysis_path,manifest_path,request_path]}
    raw, manifest_raw, request_raw = [inputs[Path(p).resolve()] for p in [analysis_path,manifest_path,request_path]]
    docs = {'analysis':parse(raw),'manifest':parse(manifest_raw),'analysis-request':parse(request_raw)}
    issues = check_documents(docs)
    if issues:
        raise ValueError(f'Invalid canonical observations: {issues[0]}')
    bindings = [{'role':role,'sha256':sha(data),'stored_name':name} for role,data,name in
                [('manifest',manifest_raw,'manifest.json'),('analysis-request',request_raw,'analysis-request.json')]]
    record = provenance(docs['analysis']['job_id'],'CANONICAL_ANALYSIS',supplier,raw,bindings)
    publish(output,record['job_id'],{'raw-input.bin':raw,'analysis.json':raw,'manifest.json':manifest_raw,
                                   'analysis-request.json':request_raw,'provenance.json':encoded(record)},inputs)
    return record


TIME = r'(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})'
TIMING = re.compile('^' + TIME + r' --> ' + TIME + '$')


def parse_srt(raw: bytes) -> list[dict]:
    """Strict UTF-8 SRT, ordered nonoverlapping intervals; preserve cue text."""
    text = raw.decode('utf-8-sig').replace('\r\n','\n')
    if '\r' in text:
        raise ValueError('Unsupported bare carriage return')
    cues = []
    previous = 0
    indices = set()
    for block in re.split(r'\n[ \t]*\n',text.strip('\n')):
        lines = block.split('\n')
        if len(lines)<3 or not re.fullmatch(r'[1-9]\d*',lines[0]):
            raise ValueError('Malformed SRT cue index/text')
        index = int(lines[0])
        match = TIMING.fullmatch(lines[1])
        if not match or index in indices:
            raise ValueError('Malformed SRT timing or duplicate index')
        numbers = list(map(int,match.groups()))
        start,end = [((h*60+m)*60+s)*1000+ms for h,m,s,ms in [numbers[:4],numbers[4:]]]
        cue_text = '\n'.join(lines[2:])
        if start>=end or start<previous or not cue_text.strip():
            raise ValueError('Empty, reversed, unordered, or overlapping SRT cue')
        cues.append({'cue_id':f'cue-{index}','raw_index':index,'start_ms':start,'end_ms':end,'text':cue_text})
        previous=end
        indices.add(index)
    return cues


def import_srt(raw_path: Path, manifest_path: Path, output: Path, *, source_id: str,
               language: str, supplier: str, content_kind: str, time_origin_ms: int) -> dict:
    if type(time_origin_ms) is not int or time_origin_ms != 0:
        raise ValueError('Explicit zero-origin transcript timing is required')
    inputs = {Path(p).resolve():_read(Path(p)) for p in [raw_path,manifest_path]}
    raw, manifest_raw = [inputs[Path(p).resolve()] for p in [raw_path,manifest_path]]
    manifest = parse(manifest_raw)
    issues = check_documents({'manifest':manifest})
    if issues:
        raise ValueError(f'Invalid manifest: {issues[0]}')
    source = next((s for s in manifest['sources'] if s['source_id']==source_id),None)
    if source is None or source['duration_ms'] is None:
        raise ValueError('Explicit known source with declared duration is required')
    cues = parse_srt(raw)
    if any(c['end_ms']>source['duration_ms'] for c in cues):
        raise ValueError('Transcript exceeds declared source duration')
    transcript = {'schema_version':'2.0.0','job_id':manifest['job_id'],'source_id':source_id,
                  'source_sha256':source.get('content_sha256'),'manifest_sha256':sha(manifest_raw),
                  'raw_sha256':sha(raw),'language':language,'content_kind':content_kind,'time_origin_ms':0,'cues':cues}
    validate('transcript',transcript)
    record = provenance(manifest['job_id'],'SRT',supplier,raw,
                        [{'role':'manifest','sha256':sha(manifest_raw),'stored_name':'manifest.json'}])
    publish(output,manifest['job_id'],{'raw-input.bin':raw,'transcript.json':encoded(transcript),
                                      'manifest.json':manifest_raw,'provenance.json':encoded(record)},inputs)
    return transcript


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='format',required=True)
    for name in ['analysis','srt']:
        command=sub.add_parser(name)
        command.add_argument('--input',type=Path,required=True)
        command.add_argument('--manifest',type=Path,required=True)
        command.add_argument('--supplier',required=True)
        command.add_argument('--output-dir',type=Path,required=True)
        if name=='analysis':command.add_argument('--request',type=Path,required=True)
        else:
            for field in ['source-id','language','content-kind']:command.add_argument('--'+field,required=True)
            command.add_argument('--time-origin-ms',type=int,required=True)
    args=parser.parse_args(argv)
    if args.format=='analysis':import_analysis(args.input,args.manifest,args.request,args.output_dir,supplier=args.supplier)
    else:import_srt(args.input,args.manifest,args.output_dir,source_id=args.source_id,language=args.language,
                   supplier=args.supplier,content_kind=args.content_kind,time_origin_ms=args.time_origin_ms)
    return 0

if __name__=='__main__':raise SystemExit(main())

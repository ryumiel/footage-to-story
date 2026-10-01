"""Map imported quotation cues to freshly verified sequential SOURCE cuts."""
from __future__ import annotations
import argparse
from copy import deepcopy
from fractions import Fraction
from pathlib import Path
import tempfile
try:
    from .import_editorial import sha, parse, validate, encoded, publish, parse_srt, _read
    from .check_integrity import check_documents
    from .verify_edit import verify_edit
    from .probe_manifest import file_signature
except ImportError:
    from import_editorial import sha, parse, validate, encoded, publish, parse_srt, _read
    from check_integrity import check_documents
    from verify_edit import verify_edit
    from probe_manifest import file_signature


def rational(value: Fraction) -> dict:
    return {'num':value.numerator,'den':value.denominator}


def map_cues(plan: dict, manifest: dict, transcripts: list[tuple[dict,str]]) -> list[dict]:
    """Pure mapping calculation; does not prove decoded timing or authorize export."""
    validate('edit-plan',plan)
    mapping_plan=deepcopy(plan)
    for item in mapping_plan['items']:
        item.pop('select_ref',None)
    # Mapping geometry is independent of selects; publication checks complete stage inputs.
    issues=check_documents({'manifest':manifest,'edit-plan':mapping_plan})
    if issues:
        raise ValueError(f'Invalid mapping documents: {issues[0]}')
    if plan['job_id']!=manifest['job_id']:
        raise ValueError('Job mismatch')
    fps=Fraction(int(plan['timeline_fps']['num']),int(plan['timeline_fps']['den']))
    sources={s['source_id']:s for s in manifest['sources']}
    transcript_sources=set()
    entries=[]
    for transcript,digest in transcripts:
        validate('transcript',transcript)
        sid=transcript['source_id']
        if transcript['job_id']!=plan['job_id'] or sid not in sources:
            raise ValueError('Transcript job/source mismatch')
        if sid in transcript_sources:
            raise ValueError('Only one transcript per source is supported')
        transcript_sources.add(sid)
        if transcript['content_kind']!='QUOTATION':
            raise ValueError('Only quotation transcripts can generate dialogue subtitles')
        if transcript['source_sha256']!=sources[sid].get('content_sha256'):
            raise ValueError('Transcript source hash differs from manifest')
        previous=0
        identifiers=set()
        for cue in transcript['cues']:
            if cue['cue_id'] in identifiers or cue['start_ms']<previous or cue['start_ms']>=cue['end_ms']:
                raise ValueError('Duplicate, reversed, unordered, or overlapping transcript cue')
            if sources[sid]['duration_ms'] is None or cue['end_ms']>sources[sid]['duration_ms']:
                raise ValueError('Transcript exceeds declared source bound')
            if '\r' in cue['text'] or any(not line.strip() for line in cue['text'].split('\n')):
                raise ValueError('Subtitle text must contain no blank lines or carriage returns')
            previous=cue['end_ms'];identifiers.add(cue['cue_id'])
    cursor=0
    for item in plan['items']:
        if item['source_in_frame']>=item['source_out_frame'] or item['timeline_in_frame']!=cursor:
            raise ValueError('Only contiguous sequential positive cuts are supported')
        cursor+=item['source_out_frame']-item['source_in_frame']
        if item['audio_policy']=='MUTE':continue
        source_start=Fraction(int(item['source_in_frame']),1)/fps
        source_end=Fraction(int(item['source_out_frame']),1)/fps
        timeline_start=Fraction(int(item['timeline_in_frame']),1)/fps
        for transcript,digest in transcripts:
            if transcript['source_id']!=item['source_id']:continue
            for cue in transcript['cues']:
                cue_start=Fraction(int(cue['start_ms']),1000);cue_end=Fraction(int(cue['end_ms']),1000)
                start=max(cue_start,source_start);end=min(cue_end,source_end)
                if start>=end:continue
                mapped_start=timeline_start+start-source_start
                mapped_end=timeline_start+end-source_start
                ms_start=-((-mapped_start.numerator*1000)//mapped_start.denominator)
                ms_end=(mapped_end.numerator*1000)//mapped_end.denominator
                if ms_start>=ms_end:
                    raise ValueError('Subtitle cue collapses under inward millisecond rounding')
                entries.append({'edit_id':item['edit_id'],'source_id':item['source_id'],
                                'transcript_sha256':digest,'cue_id':cue['cue_id'],'language':transcript['language'],
                                'text':cue['text'],'source_start_ms':cue['start_ms'],'source_end_ms':cue['end_ms'],
                                'timeline_start_seconds':rational(mapped_start),'timeline_end_seconds':rational(mapped_end),
                                'start_ms':ms_start,'end_ms':ms_end,'truncated':start!=cue_start or end!=cue_end})
    return entries


def timestamp(ms: int) -> str:
    hours,ms=divmod(ms,3600000);minutes,ms=divmod(ms,60000);seconds,ms=divmod(ms,1000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d},{ms:03d}'


def render_srt(entries: list[dict]) -> bytes:
    return ''.join(f"{number}\n{timestamp(c['start_ms'])} --> {timestamp(c['end_ms'])}\n{c['text']}\n\n"
                   for number,c in enumerate(entries,1)).encode('utf-8')


def map_subtitles(paths: dict[str,Path], transcripts: list[Path], output: Path, *, ffprobe='ffprobe') -> dict:
    """Fresh edit verification plus exact input binding; saved PASS is never sufficient."""
    if not {'manifest','edit-plan'}<=set(paths):raise ValueError('Manifest and edit plan required')
    inputs={Path(p).resolve():_read(Path(p)) for p in [*paths.values(),*transcripts]}
    docs={stage:parse(inputs[Path(p).resolve()]) for stage,p in paths.items()}
    issues=check_documents(docs)
    if issues:raise ValueError(f'Invalid stage documents: {issues[0]}')
    manifest_raw=inputs[Path(paths['manifest']).resolve()]
    bound=[]
    for path in transcripts:
        raw=inputs[Path(path).resolve()];transcript=parse(raw)
        if transcript.get('manifest_sha256')!=sha(manifest_raw):
            raise ValueError('Transcript bound to different manifest bytes')
        bundle=Path(path).resolve().parent
        bundle_paths={name:bundle/name for name in ['raw-input.bin','manifest.json','provenance.json']}
        bundle_raw={name:_read(p) for name,p in bundle_paths.items()}
        inputs.update({bundle_paths[name]:data for name,data in bundle_raw.items()})
        provenance=parse(bundle_raw['provenance.json'])
        validate('provenance',provenance)
        if (provenance['format']!='SRT' or provenance['job_id']!=docs['manifest']['job_id']
                or provenance['raw_name']!='raw-input.bin'
                or provenance['raw_sha256']!=sha(bundle_raw['raw-input.bin'])
                or transcript.get('raw_sha256')!=provenance['raw_sha256']):
            raise ValueError('Transcript raw provenance binding differs')
        expected_binding=[{'role':'manifest','sha256':sha(manifest_raw),'stored_name':'manifest.json'}]
        if provenance['inputs']!=expected_binding or bundle_raw['manifest.json']!=manifest_raw:
            raise ValueError('Transcript stored manifest/provenance binding differs')
        if transcript.get('cues')!=parse_srt(bundle_raw['raw-input.bin']):
            raise ValueError('Transcript cues differ from preserved SRT bytes')
        bound.append((transcript,sha(raw)))
    entries=map_cues(docs['edit-plan'],docs['manifest'],bound)
    source_stats={Path(s['path']):file_signature(Path(s['path'])) for s in docs['manifest']['sources']}
    with tempfile.TemporaryDirectory(prefix='footage-subtitle-check-') as tmp:
        report=verify_edit(paths,Path(tmp)/'edit',ffprobe=ffprobe)
        if report['status']!='PASS':raise ValueError('Fresh edit verification failed')
        expected={stage:sha(inputs[Path(path).resolve()]) for stage,path in paths.items()}
        if report['input_sha256']!=expected:raise ValueError('Edit scan used different input bytes')
        srt=render_srt(entries)
        mapping={'schema_version':'2.0.0','job_id':docs['edit-plan']['job_id'],
                 'plan_sha256':expected['edit-plan'],'manifest_sha256':expected['manifest'],
                 'transcript_sha256':[digest for _,digest in bound],'srt_sha256':sha(srt),
                 'rounding':'CEIL_IN_FLOOR_OUT','entries':entries}
        validate('subtitle-map',mapping)
        if any(file_signature(path)!=sig for path,sig in source_stats.items()):
            raise ValueError('Source changed during subtitle mapping')
        files={'subtitle-map.json':encoded(mapping),'subtitles.srt':srt,
               'edit-report.json':(Path(tmp)/'edit/edit-report.json').read_bytes()}
        for number,path in enumerate(transcripts,1):files[f'transcript-{number:04d}.json']=inputs[Path(path).resolve()]
        def guard():
            if any(file_signature(path)!=sig for path,sig in source_stats.items()):
                raise ValueError('Source changed before subtitle publication')
        publish(output,mapping['job_id'],files,inputs,final_guard=guard)
    return mapping


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    try:
        from .check_integrity import STAGES
    except ImportError:
        from check_integrity import STAGES
    for stage in STAGES:parser.add_argument('--'+stage,type=Path,required=stage in {'manifest','edit-plan'})
    parser.add_argument('--transcript',type=Path,action='append',required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--ffprobe',default='ffprobe')
    args=parser.parse_args(argv)
    paths={stage:getattr(args,stage.replace('-','_')) for stage in STAGES if getattr(args,stage.replace('-','_')) is not None}
    map_subtitles(paths,args.transcript,args.output_dir,ffprobe=args.ffprobe)
    return 0

if __name__=='__main__':raise SystemExit(main())

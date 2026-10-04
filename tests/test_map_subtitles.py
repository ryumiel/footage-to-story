"""Synthetic exact rational cue remapping and fresh publication checks."""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess
import pytest
from scripts import map_subtitles as sub
from scripts import import_editorial as imp
from scripts.validate_json import ROOT,load_json
from scripts.probe_manifest import build_manifest

@pytest.fixture
def fixture():
    manifest=load_json(ROOT/'examples/contracts/manifest.json')
    plan=load_json(ROOT/'examples/contracts/edit-plan.json')
    plan['items']=plan['items'][:1]
    item=plan['items'][0];item.pop('select_ref',None)
    item.update(source_in_frame=10,source_out_frame=35,timeline_in_frame=0,audio_policy='SOURCE')
    transcript={'schema_version':'2.0.0','job_id':manifest['job_id'],'source_id':'src-001','source_sha256':None,
                'manifest_sha256':'a'*64,'raw_sha256':'b'*64,'language':'ko','content_kind':'QUOTATION','time_origin_ms':0,
                'cues':[{'cue_id':'cue-1','raw_index':1,'start_ms':0,'end_ms':1000,'text':'\ud55c\uad6d\uc5b4'}]}
    return plan,manifest,transcript

def calc(f):return sub.map_cues(f[0],f[1],[(f[2],'c'*64)])

def test_intersection_truncation_and_out_exclusive(fixture):
    entries=calc(fixture)
    assert len(entries)==1
    assert (entries[0]['start_ms'],entries[0]['end_ms'])==(0,600)
    assert entries[0]['truncated']
    assert entries[0]['text']=='\ud55c\uad6d\uc5b4'
    fixture[2]['cues'][0].update(start_ms=1400,end_ms=1500)
    assert calc(fixture)==[]

def test_repeat_split_source_and_mute(fixture):
    first=fixture[0]['items'][0]
    second=deepcopy(first);second.update(edit_id='repeated',timeline_in_frame=25)
    muted=deepcopy(first);muted.update(edit_id='muted',timeline_in_frame=50,audio_policy='MUTE')
    fixture[0]['items'] += [second,muted]
    entries=calc(fixture)
    assert [e['start_ms'] for e in entries]==[0,1000]
    assert [e['cue_id'] for e in entries]==['cue-1','cue-1']
    assert all(e['edit_id']!='muted' for e in entries)

def test_fractional_rate_absolute_rationals_no_drift(fixture):
    plan,manifest,t=fixture
    plan['timeline_fps']={'num':30000,'den':1001}
    for source in manifest['sources']:source.update(fps_num=30000,fps_den=1001)
    first=plan['items'][0];first.update(source_in_frame=0,source_out_frame=3)
    plan['items']=[dict(first,edit_id=f'cut-{n}',timeline_in_frame=3*n) for n in range(100)]
    t['cues'][0].update(start_ms=0,end_ms=100)
    entries=calc(fixture)
    assert entries[-1]['start_ms']==9910
    assert entries[-1]['timeline_start_seconds']=={'num':99099,'den':10000}
    assert entries[-1]['end_ms']==10009


def test_rounding_collapse_fails(fixture):
    plan,manifest,t=fixture
    plan['timeline_fps']={'num':30000,'den':1001}
    for source in manifest['sources']:source.update(fps_num=30000,fps_den=1001)
    plan['items'][0].update(source_in_frame=1,source_out_frame=2)
    t['cues'][0].update(start_ms=33,end_ms=34)
    with pytest.raises(ValueError,match='collapses'):calc(fixture)

@pytest.mark.parametrize('fault',['job','source','kind','hash','duplicate','overlap','gap'])
def test_reject_bad_inputs(fixture,fault):
    p,m,t=fixture
    if fault=='job':t['job_id']='other'
    elif fault=='source':t['source_id']='missing'
    elif fault=='kind':t['content_kind']='SUMMARY'
    elif fault=='hash':t['source_sha256']='a'*64
    elif fault=='duplicate':t['cues'].append(deepcopy(t['cues'][0]))
    elif fault=='overlap':t['cues'].append(dict(t['cues'][0],cue_id='cue-2',start_ms=500,end_ms=1500))
    else:p['items'][0]['timeline_in_frame']=1
    with pytest.raises(ValueError):calc(fixture)

@pytest.mark.parametrize('audio_codec', ['pcm_s16le', 'libmp3lame', 'aac'])
def test_live_generated_media_and_raw_binding(tmp_path, audio_codec):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('Requires media tools')
    source=tmp_path/'synthetic.mov'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=64x48:rate=25:duration=2',
                    '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=2','-c:v','mpeg4','-c:a',audio_codec,str(source)],check=True)
    manifest=build_manifest('synthetic-subtitles',[('src-1',source)],tmp_path/'inventory')
    manifest_path=tmp_path/'inventory/manifest.json'
    plan={'schema_version':'2.0.0','job_id':manifest['job_id'],'revision':'r1','timeline_name':'Synthetic subtitles',
          'edit_mode':'SEQUENTIAL_CUTS','timeline_fps':{'num':25,'den':1},'items':[
              {'edit_id':'cut-1','source_id':'src-1','source_in_frame':10,'source_out_frame':35,'timeline_in_frame':0,
               'audio_policy':'SOURCE','reason':'Synthetic','locked':False}]}
    plan_path=tmp_path/'plan.json';plan_path.write_text(json.dumps(plan))
    srt=tmp_path/'source.srt';srt.write_text('1\n00:00:00,000 --> 00:00:01,000\nSynthetic quotation\n')
    imp.import_srt(srt,manifest_path,tmp_path/'import',source_id='src-1',language='en',supplier='Synthetic',content_kind='QUOTATION',time_origin_ms=0)
    paths={'manifest':manifest_path,'edit-plan':plan_path}
    transcript=tmp_path/'import/transcript.json'
    report=sub.map_subtitles(paths,[transcript],tmp_path/'mapped')
    timing = load_json(tmp_path/'mapped/edit-report.json')
    assert timing['scope'] == 'SUBTITLE_TIMING'
    assert timing['audio_cut_verification'] == 'NOT_RUN'
    assert timing['execution_authorized'] is False
    assert timing['items'][0]['audio_cut']['status'] == 'NOT_RUN'
    from scripts.verify_edit import verify_edit
    export_check = verify_edit(paths, tmp_path/'export-check')
    assert export_check['scope'] == 'EDIT_AUDIO_VIDEO'
    assert export_check['status'] == ('PASS' if audio_codec in {'pcm_s16le', 'aac'} else 'FAIL')
    assert not list(tmp_path.rglob('*.wav'))
    assert report['entries'][0]['end_ms']==600
    assert '00:00:00,000 --> 00:00:00,600' in (tmp_path/'mapped/subtitles.srt').read_text()
    modified=load_json(transcript);modified['manifest_sha256']='0'*64;transcript.write_text(json.dumps(modified))
    with pytest.raises(ValueError,match='manifest bytes'):sub.map_subtitles(paths,[transcript],tmp_path/'bad')

def test_integer_valued_json_floats_map_exactly(fixture):
    expected=calc(fixture)
    plan,manifest,transcript=fixture
    plan['timeline_fps']={k:float(v) for k,v in plan['timeline_fps'].items()}
    for item in plan['items']:
        for name in ['source_in_frame','source_out_frame','timeline_in_frame']:item[name]=float(item[name])
    for cue in transcript['cues']:
        for name in ['start_ms','end_ms','raw_index']:cue[name]=float(cue[name])
    assert calc(fixture)==expected

@pytest.mark.parametrize('fault',['missing','raw','cues','provenance-job','provenance-format','provenance-hash','provenance-input','stored-manifest'])
def test_publication_rejects_missing_or_changed_import_bundle(tmp_path,fixture,fault):
    plan,manifest,_=fixture
    manifest_path=tmp_path/'manifest.json';manifest_path.write_text(json.dumps(manifest))
    plan_path=tmp_path/'plan.json';plan_path.write_text(json.dumps(plan))
    raw=tmp_path/'source.srt';raw.write_text('1\n00:00:00,000 --> 00:00:01,000\nSynthetic\n')
    bundle=tmp_path/'import'
    imp.import_srt(raw,manifest_path,bundle,source_id='src-001',language='en',supplier='Synthetic',content_kind='QUOTATION',time_origin_ms=0)
    transcript=bundle/'transcript.json'
    provenance=load_json(bundle/'provenance.json')
    if fault=='missing':(bundle/'raw-input.bin').unlink()
    elif fault=='raw':(bundle/'raw-input.bin').write_bytes(b'changed raw')
    elif fault=='cues':
        data=load_json(transcript);data['cues'][0]['text']='Fabricated';transcript.write_text(json.dumps(data))
    elif fault=='stored-manifest':(bundle/'manifest.json').write_text('{}')
    else:
        if fault=='provenance-job':provenance['job_id']='wrong'
        elif fault=='provenance-format':provenance['format']='CANONICAL_ANALYSIS'
        elif fault=='provenance-hash':provenance['raw_sha256']='0'*64
        elif fault=='provenance-input':provenance['inputs'][0]['sha256']='0'*64
        (bundle/'provenance.json').write_text(json.dumps(provenance))
    with pytest.raises((ValueError,OSError)):
        sub.map_subtitles({'manifest':manifest_path,'edit-plan':plan_path},[transcript],tmp_path/'out')
    assert not (tmp_path/'out').exists()

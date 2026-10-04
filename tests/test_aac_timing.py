"""Synthetic AAC-LC presentation clocks; application playback is a separate check."""
from copy import deepcopy
from fractions import Fraction
import pytest
from scripts.audio_timing import analyze_aac, sample_cut

@pytest.fixture
def aac():
    stream = {'codec_name':'aac','profile':'LC','sample_fmt':'fltp','sample_rate':'48000',
              'channels':2,'time_base':'1/48000','start_pts':0,'duration_ts':3000,'initial_padding':1024}
    frames = [{'pts':p,'duration':n,'nb_samples':n,'channels':2,'sample_fmt':'fltp'}
              for p,n in [(0,1024),(1024,1024),(2048,952)]]
    return stream,frames

def test_priming_removed_and_tail_trimmed_presentation(aac):
    before=deepcopy(aac);result=analyze_aac(*aac)
    assert result['status']=='PASS' and result['sample_count']==3000
    assert result['initial_padding_samples']==1024
    assert result['application_decode_sync']=='NOT_RUN'
    assert sample_cut(result,0,1,0,Fraction(25))['source_out_sample']==1920
    assert aac==before

@pytest.mark.parametrize('case',['profile','rate','channels','padding','padding-bool','origin','origin-bool',
                                  'no-bounds','gap','overlap','negative-pts','duration','untrimmed-tail',
                                  'side-data','format-change','partial-interior','empty'])
def test_unsupported_aac_never_passes(aac,case):
    s,f=aac
    if case=='profile':s['profile']='HE-AAC'
    elif case=='rate':s['sample_rate']='44100'
    elif case=='channels':s['channels']=6
    elif case=='padding':s['initial_padding']=2048
    elif case=='padding-bool':s['initial_padding']=False
    elif case=='origin':s['start_pts']=1024
    elif case=='origin-bool':s['start_pts']=False
    elif case=='no-bounds':s.pop('duration_ts')
    elif case=='gap':f[1]['pts']+=1
    elif case=='overlap':f[1]['pts']-=1
    elif case=='negative-pts':f[0]['pts']=-1024
    elif case=='duration':f[1]['duration']-=1
    elif case=='untrimmed-tail':f[-1]['nb_samples']=1024;f[-1]['duration']=1024
    elif case=='side-data':f[0]['side_data_list']=[{'side_data_type':'Skip Samples'}]
    elif case=='format-change':f[1]['sample_fmt']='s16'
    elif case=='partial-interior':f[0]['nb_samples']=1000
    else:f.clear()
    result=analyze_aac(s,f)
    assert result['status']=='FAIL' and result['issues']
    assert result['sample_count'] is None


def test_real_aac_decode_removes_encoder_delay_and_preserves_channel_times(tmp_path):
    import json
    import shutil
    import struct
    import subprocess
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('Requires real FFmpeg tools')
    media=tmp_path/'synthetic-timed-bursts.mp4'
    expression="aevalsrc='if(between(t,0.20,0.21),0.7*sin(2*PI*997*t),0)|if(between(t,1.20,1.21),0.7*sin(2*PI*1499*t),0)':s=48000:d=2"
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i',expression,'-c:a','aac','-b:a','320k',str(media)],check=True,capture_output=True,timeout=20)
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_frames','-of','json',str(media)],timeout=20))
    measured=analyze_aac(probe['streams'][0],probe['frames'])
    assert measured['status']=='PASS' and measured['sample_count']==96000
    assert measured['initial_padding_samples']==1024
    raw=subprocess.check_output(['ffmpeg','-v','error','-i',str(media),'-c:a','pcm_f32le','-f','f32le','pipe:1'],timeout=20)
    samples=struct.unpack('<'+'f'*(len(raw)//4),raw)
    assert len(samples)==96000*2
    for channel,expected in [(0,.205),(1,1.205)]:
        energy=[samples[n*2+channel]**2 for n in range(96000)]
        center=sum(n*e for n,e in enumerate(energy))/sum(energy)/48000
        # Independent generator oracle: an unremoved 1024-sample encoder delay
        # would shift either burst by 21.33 ms, well outside this tolerance.
        assert abs(center-expected)<.002

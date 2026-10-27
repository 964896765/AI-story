import subprocess
import sys
import time
import pytest
from pydantic import ValidationError
from app.render import RenderOptions, clip_duration, geometry, display_size, validate_srt, execute_ffmpeg, Cancelled

@pytest.mark.parametrize('options',[{'start':-1},{'start':3,'end':2},{'duration':1,'end':2},{'start':float('nan')},{'duration':0},{'aspect':'2:3'},{'format':'mp4;evil'},{'volume':5},{'audio_mode':'replace'},{'audio_asset_id':'unexpected'},{'strategy':'stretch'},{'unknown':'value'}])
def test_reject_invalid_options(options):
    with pytest.raises(ValidationError): RenderOptions(**options)

def test_clip_ranges():
    assert clip_duration(RenderOptions(start=1,end=3),5)==2
    assert clip_duration(RenderOptions(start=1,duration=2),5)==2
    assert clip_duration(RenderOptions(start=1),5)==4
    for options in [RenderOptions(start=5),RenderOptions(start=1,duration=9)]:
        with pytest.raises(ValueError): clip_duration(options,5)

@pytest.mark.parametrize('strategy,size',[('pad',(1080,1920)),('crop',(1080,1920)),('fit',(1080,606))])
def test_geometry(strategy,size):
    vf,actual=geometry(RenderOptions(aspect='9:16',resolution='1080',strategy=strategy),{'width':1920,'height':1080})
    assert actual==size and 'setsar=1' in vf

def test_rotation_and_sar():
    assert display_size({'width':1920,'height':1080,'side_data_list':[{'rotation':90}]})==(1080,1920)
    assert display_size({'width':720,'height':576,'sample_aspect_ratio':'16:15'})==(768,576)
    assert geometry(RenderOptions(),{'width':1920,'height':1080})[1]==(1920,1080)

def test_srt_validation(tmp_path):
    path=tmp_path/'test.srt'
    path.write_text('1\n00:00:00,000 --> 00:00:01,000\n中文测试\n',encoding='utf-8')
    assert '中文' in validate_srt(path)
    for content in ['bad','1\n00:01:00,000 --> 00:00:00,000\nwrong','1\n00:99:00,000 --> 01:00:00,000\nwrong']:
        path.write_text(content)
        with pytest.raises(ValueError): validate_srt(path)

def test_process_timeout_and_cancel(tmp_path):
    args=[sys.executable,'-c','import time;time.sleep(20)']
    before=time.monotonic()
    with pytest.raises(TimeoutError): execute_ffmpeg(args,tmp_path,1,lambda *args:None,timeout=0.2)
    assert time.monotonic()-before<6
    def cancel(*args): raise Cancelled('cancel')
    with pytest.raises(Cancelled): execute_ffmpeg(args,tmp_path,1,cancel)
    with pytest.raises(FileNotFoundError): execute_ffmpeg(['nonexistent-ffmpeg-p2'],tmp_path,1,cancel)

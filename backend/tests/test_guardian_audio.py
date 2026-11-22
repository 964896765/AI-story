from array import array
from hashlib import sha256
import subprocess
from types import SimpleNamespace
import wave

from app import quality
from app.delivery import dialogue_rechecks
from app.guardian_audio import RATE, RULE_VERSION, align_transcript, compare_captions, loudest_block, speech_key


def test_fixed_captions_detect_missing_wrong_and_extra_content():
    lines = [{'shot_number':1,'start_ms':0,'end_ms':500,'text':'守塔人回来了。'},
             {'shot_number':2,'start_ms':1000,'end_ms':1300,'text':'门开了'},
             {'shot_number':3,'start_ms':2000,'end_ms':2600,'text':'灯塔 坐标'}]
    found = [{'start_us':0,'end_us':520000,'text':'守塔人走了。'},
             {'start_us':2000000,'end_us':2600000,'text':'灯塔\n坐标'},
             {'start_us':3000000,'end_us':3400000,'text':'未批准的附加字幕'}]
    issues = []
    result = list(compare_captions(lines,found,lambda *issue:issues.append(issue)))
    assert [line['caption_status'] for line in result]==['different','missing','matched']
    assert [(code,level,start,end) for code,level,_,start,end in issues]==[
        ('subtitle_dialogue_mismatch','error',0,500),
        ('subtitle_dialogue_missing','error',1000,1300),
        ('subtitle_dialogue_extra','error',3000,3400),
    ]


def test_audio_window_loudness_and_asr_alignment(tmp_path):
    pcm = tmp_path/'mix.wav'
    with wave.open(str(pcm),'wb') as output:
        output.setparams((1,2,RATE,0,'NONE','not compressed'))
        output.writeframes(array('h',[0]*(RATE//2)+[1024,-1024]*(RATE//4)).tobytes())
    with wave.open(str(pcm),'rb') as samples:
        assert loudest_block(samples,0,500) is None
        assert loudest_block(samples,500,1000)==-30.1
        assert loudest_block(samples,1000,1200) is None
    line_a={'start_ms':480,'end_ms':660}
    line_b={'start_ms':700,'end_ms':900}
    found=[{'start_us':352000,'end_us':565000,'text':'你好'},
           {'start_us':650000,'end_us':850000,'text':'灯塔'},
           {'start_us':1400000,'end_us':1600000,'text':'无关段落'}]
    assert align_transcript([line_a,line_b],found)==[[found[0]],[found[1]]]
    assert speech_key('Ａ ９，你 好！')=='a9你好'


def test_real_render_with_background_does_not_hide_muted_dialogue(tmp_path, monkeypatch):
    video = tmp_path/'video.mp4'
    subtitles = tmp_path/'captions.srt'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=s=720x720:r=24:d=1',
                    '-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-threads','2',
                    '-c:a','aac',str(video)],check=True,timeout=20)
    subtitles.write_text('1\n00:00:00,125 --> 00:00:00,780\n另一个版本的对白。\n',encoding='utf-8')
    monkeypatch.setattr(quality.storage,'resolve_key',lambda key:tmp_path/key)
    tracks = [{'enabled':True,'role':role,'volume':gain,'clips':[{'id':role,'at':0,'frames':24}]} for role,gain in
              [('main',1),('dialogue',0),('music',1),('caption',1)]]
    render = SimpleNamespace(id='render',story_version_id='fixed-timeline',parameters={'timeline':{
        'frames':24,'frame_rate':24,'profile':'square','tracks':tracks}},output={
        'storage_key':video.name,'sha256':sha256(video.read_bytes()).hexdigest(),
        'caption_storage_key':subtitles.name,'caption_sha256':sha256(subtitles.read_bytes()).hexdigest()})
    policy = {'require_audio':True,'require_subtitles':True,'black_ms':500,'freeze_ms':750,'silence_ms':1000,'silence_db':-45}
    lines = [{'shot_number':1,'start_ms':125,'end_ms':750,'text':'灯塔还亮着。'}]
    report = quality.qa_output(render,policy,lambda *_:None,'qc',1,dialogue={'lines':lines})
    result = report['dialogue']['lines'][0]
    assert result['max_window_rms_dbfs']>-55 and result['audio_status']=='muted'
    assert result['caption_status']=='different'
    assert [(item['code'],item['severity'],item['start_ms'],item['clips']) for item in report['issues']]==[
        ('subtitle_dialogue_mismatch','error',125,['caption']),('dialogue_track_muted','error',125,['dialogue'])]


def test_delivery_requests_recheck_for_legacy_dialogue_only():
    boards = [SimpleNamespace(id=f'board-{number}',content={'shots':[{'dialogue':line}]})
              for number,line in enumerate(['有对白','  ','已通过核验'],1)]
    plan = SimpleNamespace(content={'guardian':{'facts':{}},'episodes':[
        {'storyboard_version_id':board.id} for board in boards]})
    db = SimpleNamespace(get=lambda *_:plan,scalars=lambda _:boards[:2])
    episodes = [{'number':1,'qc':{}},{'number':2,'qc':{}},
                {'number':3,'qc':{'dialogue':{'rule_version':RULE_VERSION}}}]
    assert dialogue_rechecks(db,'plan',episodes)==[1]

import json
import os
from datetime import timedelta
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from app import asr_chunks, worker
from app.asr_chunks import SpeechCheckpoint, merge_chunks, plan_chunks
from app.models import Task, now
from app.perception_asr import normalize_segments, recognizer
from test_media_analysis import analysis, ffmpeg
from test_postgres import database
from test_render_postgres import studio


def test_transcript_clock_validation_and_overlaps():
    result = {'start_us': 610999, 'end_us': 3450000, 'text': '  大家好  ', 'confidence': 0.5473731}
    assert normalize_segments([result], 2000000, 3450000) == [
        {'start_us': 2610000, 'end_us': 5450000, 'text': '大家好', 'confidence': 0.547373},
    ]
    with pytest.raises(ValueError, match='无效时间'):
        normalize_segments([result | {'end_us': 3490000}], 0, 3450000)
    with pytest.raises(ValueError, match='重叠'):
        normalize_segments([result,result], 0, 3450000)


@pytest.fixture
def mandarin_sample(tmp_path):
    try:
        adapter = recognizer('zh-CN')
    except ValueError:
        pytest.skip('Windows desktop Mandarin dictation recognizer unavailable')
    root = Path(__file__).resolve().parents[2]
    powershell = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    voice = 'Microsoft Huihui Desktop'
    script = [str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
              '-File',str(root/'scripts'/'synthesize_dialogue.ps1')]
    voices = json.loads(subprocess.check_output([*script,'-List'], timeout=15))
    if not any(item['name'] == voice for item in voices):
        pytest.skip('Windows Mandarin test fixture voice unavailable')
    (tmp_path/'dialogue-input.json').write_text(json.dumps({'lines': [
        {'voice':voice,'rate':-1,'text':'大家好，欢迎来到灯塔。今天的天气很好。'},
        {'voice':voice,'rate':-1,'text':'请准备出发，我们马上就到海边。'},
    ]},ensure_ascii=False),encoding='utf-8')
    subprocess.run(script,cwd=tmp_path,check=True,timeout=25)
    return adapter


def test_real_windows_asr_selected_stream_source_clock_and_review(analysis, tmp_path, mandarin_sample):
    adapter = mandarin_sample
    client, project, _, upload, task, resolve, _, submit, complete = analysis
    capabilities = client.get('/api/analysis/capabilities').json()['capabilities']
    asr = next(item for item in capabilities if item['id']=='asr')
    assert asr['available'] and 'zh-CN' in asr['languages'] and asr['engine'] == adapter['engine']
    source = tmp_path/'speech.mkv'
    ffmpeg('-f','lavfi','-i','color=white:s=320x240:r=24:d=16',
           '-f','lavfi','-i','anullsrc=r=16000:cl=mono:d=16',
           '-i',tmp_path/'line-001.wav','-i',tmp_path/'line-002.wav',
           '-filter_complex','[2:a]apad=pad_dur=1[first];[first][3:a]concat=n=2:v=0:a=1,adelay=2500,apad=whole_dur=16[out]',
           '-map','0:v:0','-map','1:a:0','-map','[out]','-t','16','-c:v','libx264','-threads','2','-c:a','pcm_s16le',source)
    original = source.read_bytes()
    asset = upload('本机转写样片.mkv', original)
    stream = {'operation':'asr','asr_language':'zh-CN','stream':2,'scan_start_ms':2000,'scan_end_ms':15000}
    assert submit([stream | {'scan_end_ms':1000}],asset['id']).status_code == 422
    assert submit([stream | {'asr_language':'zz-XX'}],asset['id']).status_code == 422
    submitted = submit([stream],asset['id'],key='real-windows-asr')
    assert submitted.status_code == 201, submitted.text
    job = submitted.json()[0]
    assert job['input_snapshot']['asr'] == adapter
    assert submit([stream],asset['id'],key='real-windows-asr').json()[0]['id'] == job['id']
    result = complete(job['id'])
    assert result['speech']['stream_index'] == 2 and result['speech']['status'] == 'recognized'
    assert result['speech']['start_us'] == 2_000_000 and result['speech']['end_us'] == 15_000_000
    cues = result['subtitle_tracks'][0]['cues']
    assert 2_400_000 < cues[0]['start_us'] < 3_200_000
    combined = ''.join(cue['text'].replace(' ','') for cue in cues)
    assert '大家好' in combined and '天气很好' in combined and '我们马上' in combined
    assert all(0 <= cue['confidence'] <= 1 and cue['end_us'] <= 15_000_000 for cue in cues)
    assert [item['role'] for item in result['artifacts']] == ['asr_audio','asr_transcript']
    audio = client.get(f"/api/analysis/tasks/{job['id']}/artifacts/0",headers={'Range':'bytes=0-23'})
    assert audio.status_code == 206 and audio.content[:4] == b'RIFF'
    route = f"/api/analysis/projects/{project}/assets/{asset['id']}/tasks/{job['id']}/subtitle-tracks/2/revisions"
    saved = client.post(route,json={'edits':{'0':{'start_ms':2600,'end_ms':5400,'text':'大家好，欢迎来到灯塔。'}}})
    assert saved.status_code == 201, saved.text
    reviewed = saved.json()
    assert reviewed['media_info']['subtitle_origin'] == 'asr_estimated'
    assert reviewed['media_info']['derived_from_asset'] == asset['id']
    assert reviewed['media_info']['subtitle_source_sha256'] == result['artifacts'][1]['sha256']
    assert client.get(route+'/'+reviewed['id']).json()['cues'][0]['text'] == '大家好，欢迎来到灯塔。'
    assert client.get(route.replace(project,str(uuid4()))+'/'+reviewed['id']).status_code == 404
    assert resolve(asset['storage_key']).read_bytes() == original

    silent = submit([stream | {'stream':1,'scan_end_ms':3500}],asset['id']).json()[0]
    result = complete(silent['id'])
    assert result['speech']['status'] == 'no_speech' and result['subtitle_tracks'][0]['cues'] == []
    assert [item['role'] for item in result['artifacts']] == ['asr_audio']
    missing = submit([stream | {'stream':0}],asset['id']).json()[0]
    assert worker.run_once()
    assert task(missing['id'])['status'] == 'failed'
    assert '流类型不适用' in task(missing['id'])['error']


def test_chunk_merging_uses_common_pause_or_marks_conflicting_seam():
    plan = plan_chunks(193_000_000)
    assert [(c.start_us,c.end_us,c.core_us) for c in plan] == [
        (0,175_000_000,0),(165_000_000,193_000_000,170_000_000),
    ]
    assert all(chunk.end_us-chunk.start_us <= 180_000_000 for chunk in plan_chunks(1_800_000_000))
    cue = lambda a,b,text: {'start_us':a*1_000_000,'end_us':b*1_000_000,'text':text}
    before = cue(168,171,'跨接缝的同一句')
    after = cue(172,174,'下一句')
    merged, seams = merge_chunks(plan, [[before,after],[before,after]], 0)
    assert merged == [before,after]
    assert seams == [{'boundary_us':170_000_000,'merge_us':171_000_000,'needs_review':False}]
    left = cue(163,172,'前半句')
    right = cue(165,178,'不同窗口的文字')
    merged, seams = merge_chunks(plan, [[left],[right]], 0)
    assert merged == [left,cue(172,178,'不同窗口的文字')]
    assert seams == [{'boundary_us':170_000_000,'merge_us':170_000_000,'needs_review':True}]


def test_asr_checkpoint_rejects_changed_signature_window_and_checksum(tmp_path):
    checkpoint = SpeechCheckpoint(tmp_path,'source-hash-and-parameters')
    window = [0,175_000_000]
    checkpoint.write(0,window,[])
    assert checkpoint.read(0,window) == []
    assert checkpoint.read(0,[1000,window[1]]) is None
    assert SpeechCheckpoint(tmp_path,'other-signature').read(0,window) is None
    file = tmp_path/'000.json'
    record = json.loads(file.read_text(encoding='utf-8'))
    record['data']['cues'] = [{'start_us':0,'end_us':1000,'text':'修改'}]
    file.write_text(json.dumps(record),encoding='utf-8')
    assert checkpoint.read(0,window) is None


def test_real_long_asr_reuses_checkpoint_after_worker_lease_expires(analysis, tmp_path, mandarin_sample, monkeypatch):
    client, _, _, upload, task, resolve, factory, submit, complete = analysis
    source = tmp_path/'long-speech.wav'
    ffmpeg('-i',tmp_path/'line-001.wav','-i',tmp_path/'line-002.wav','-filter_complex',
           '[0:a]asplit=2[early][repeat];[repeat]adelay=167500[bridge];[1:a]adelay=182000[late];'
           '[early][bridge][late]amix=inputs=3:normalize=0,apad=whole_dur=193[out]',
           '-map','[out]','-t','193','-ac','1','-ar','16000','-c:a','pcm_s16le',source)
    asset = upload('长音频转写验收.wav',source.read_bytes())
    job = submit([{'operation':'asr','asr_language':'zh-CN'}],asset['id']).json()[0]
    run_asr = asr_chunks.transcribe
    observed = []

    def interrupted(commands, path, adapter, start, duration, progress):
        if start:
            raise KeyboardInterrupt
        observed.append(start)
        return run_asr(commands,path,adapter,start,duration,progress)

    monkeypatch.setattr(asr_chunks,'transcribe',interrupted)
    with pytest.raises(KeyboardInterrupt):
        worker.run_once()
    assert observed == [0] and task(job['id'])['status'] == 'running'
    assert resolve(f"tmp/{job['id']}/asr-checkpoints/000.json").is_file()
    assert client.get(f"/api/analysis/tasks/{job['id']}/result").status_code == 404
    with factory.begin() as db:
        db.get(Task,job['id']).lease_until = now()-timedelta(seconds=1)

    def resumed(commands, path, adapter, start, duration, progress):
        observed.append(start)
        return run_asr(commands,path,adapter,start,duration,progress)

    monkeypatch.setattr(asr_chunks,'transcribe',resumed)
    result = complete(job['id'])
    assert observed == [0,165_000_000] and task(job['id'])['attempt'] == 2
    speech = result['speech']
    assert speech['chunk_count'] == 2 and speech['reused_chunks'] == 1
    assert speech['chunks'][1]['start_us'] == 165_000_000
    cues = result['subtitle_tracks'][0]['cues']
    assert sum('灯塔' in cue['text'] for cue in cues) == 2
    assert any('我们马上' in cue['text'] and cue['start_us'] > 180_000_000 for cue in cues)
    assert all(a['end_us'] <= b['start_us'] for a,b in zip(cues,cues[1:]))

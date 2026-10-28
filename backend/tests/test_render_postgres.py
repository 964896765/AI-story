import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select,delete
from app.main import app
from app import main, storage, worker
from app import render as renderer
from app.models import Project,Asset,Task,TaskEvent,now
from app.media import probe
from test_postgres import database

@pytest.fixture
def studio(database,tmp_path,monkeypatch):
    original=storage.resolve_key
    resolver=lambda key:original(key,tmp_path)
    for module in [storage,main,worker,renderer]:monkeypatch.setattr(module,'resolve_key',resolver)
    client=TestClient(app)
    project=client.post('/api/projects',json={'name':'P2 integration '+str(uuid4())}).json()['id']
    def upload(name,content):
        result=client.post(f'/api/projects/{project}/assets',files={'file':(name,content)},data={'authorization':'FFmpeg 自行生成测试素材'})
        assert result.status_code==201,result.text
        return result.json()
    path=tmp_path/'fixture.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=24','-f','lavfi','-i','sine=frequency=440','-t','2','-c:v','mpeg4','-c:a','aac',str(path)],check=True,timeout=30)
    asset=upload('fixture.mp4',path.read_bytes())
    def submit(params=None,aid=None,key=None):
        result=client.post(f'/api/projects/{project}/tasks',json={'asset_id':aid or asset['id'],'kind':'render','parameters':params or {},'idempotency_key':key or str(uuid4())})
        assert result.status_code==201,result.text
        return result.json()
    def task(tid):
        return next(t for t in client.get(f'/api/projects/{project}/tasks').json() if t['id']==tid)
    yield client,project,asset,upload,submit,task,resolver,database
    with database.begin() as db:
        ids=select(Task.id).where(Task.project_id==project)
        db.execute(delete(TaskEvent).where(TaskEvent.task_id.in_(ids)))
        db.execute(delete(Task).where(Task.project_id==project))
        db.execute(delete(Asset).where(Asset.project_id==project))
        db.execute(delete(Project).where(Project.id==project))

@pytest.mark.parametrize('params,expected,audio',[
    ({'start':0.25,'end':1.25,'aspect':'9:16','resolution':'720','strategy':'pad'},(720,1280),True),
    ({'duration':1,'aspect':'16:9','strategy':'crop','audio_mode':'mute','format':'mkv'},(426,240),False),
    ({'duration':1,'aspect':'1:1','strategy':'fit','volume':0.5},(240,180),True),
])
def test_real_render(studio,params,expected,audio):
    client,project,asset,upload,submit,task,resolve,factory=studio
    original=resolve(asset['storage_key']).read_bytes()
    queued=submit(params,key='same-render')
    assert submit(params,key='same-render')['id']==queued['id']
    conflict=client.post(f'/api/projects/{project}/tasks',json={'asset_id':asset['id'],'kind':'render','parameters':{},'idempotency_key':'same-render'})
    assert conflict.status_code==409
    worker.run_once()
    result=task(queued['id'])
    assert result['status']=='succeeded',result['error']
    output=result['output']
    assert (output['width'],output['height'])==expected and output['has_audio']==audio
    assert 0.8<float(probe(resolve(output['storage_key']))['format']['duration'])<1.3
    assert resolve(asset['storage_key']).read_bytes()==original
    assert result['progress']==100 and result['elapsed_seconds']>0
    assert client.get(f"/api/tasks/{queued['id']}/output?download=true").status_code==200
    assert client.get(f"/api/tasks/{queued['id']}/output",headers={'range':'bytes=0-99'}).status_code==206
    events=client.get(f"/api/tasks/{queued['id']}/events").json()
    assert any('validating' in e['message'] for e in events)
    assert not list(resolve(f"tmp/{queued['id']}/1").glob('partial.*'))

def test_subtitles_audio_and_rotation(studio,tmp_path):
    client,project,asset,upload,submit,task,resolve,factory=studio
    srt=upload('字幕.srt','1\n00:00:00,000 --> 00:00:01,000\nP2 subtitle test 中文\n'.encode())
    audio_path=tmp_path/'voice.wav'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','sine=frequency=880','-t','0.5',str(audio_path)],check=True,timeout=30)
    audio=upload('voice.wav',audio_path.read_bytes())
    base=submit({'duration':1,'audio_mode':'mute'})
    subtitled=submit({'duration':1,'audio_mode':'replace','audio_asset_id':audio['id'],'subtitle_asset_id':srt['id'],'volume':0.7})
    worker.run_once();worker.run_once()
    result=task(subtitled['id'])
    assert result['status']=='succeeded',result['error']
    assert result['output']['has_audio']
    def frame(tid):
        path=resolve(task(tid)['output']['storage_key'])
        return subprocess.run(['ffmpeg','-v','error','-ss','0.4','-i',str(path),'-frames:v','1','-vf','crop=320:80:0:160,format=gray','-f','rawvideo','pipe:1'],capture_output=True,check=True).stdout
    a,b=frame(base['id']),frame(subtitled['id'])
    assert len(a)==len(b) and sum(abs(x-y) for x,y in zip(a,b))/len(a)>0.5
    rotated=tmp_path/'rotated.mp4'
    subprocess.run(['ffmpeg','-v','error','-display_rotation','90','-i',str(resolve(asset['storage_key'])),'-c','copy',str(rotated)],check=True,timeout=30)
    rasset=upload('rotated.mp4',rotated.read_bytes())
    assert any(abs(float(side.get('rotation',0)))==90 for side in probe(rotated)['streams'][0].get('side_data_list',[]))
    rotation_task=submit({'duration':1},rasset['id']);worker.run_once()
    result=task(rotation_task['id'])
    assert result['status']=='succeeded',result['error']
    assert (result['output']['width'],result['output']['height'])==(240,320)

def test_no_audio_invalid_missing_subtitle_and_retry(studio,tmp_path):
    client,project,asset,upload,submit,task,resolve,factory=studio
    path=tmp_path/'silent.mp4'
    subprocess.run(['ffmpeg','-v','error','-i',str(resolve(asset['storage_key'])),'-an','-c:v','copy',str(path)],check=True,timeout=30)
    silent=upload('silent.mp4',path.read_bytes())
    tid=submit({'duration':1},silent['id'])['id'];worker.run_once()
    assert task(tid)['status']=='succeeded' and not task(tid)['output']['has_audio']
    invalid=upload('invalid.mp4',b'invalid');bad=submit({},invalid['id']);worker.run_once()
    assert task(bad['id'])['status']=='failed'
    srt=upload('missing.srt',b'1\n00:00:00,000 --> 00:00:01,000\nTest\n')
    subtitle_bytes=resolve(srt['storage_key']).read_bytes();resolve(srt['storage_key']).unlink()
    missing=submit({'duration':1,'subtitle_asset_id':srt['id']});worker.run_once()
    assert task(missing['id'])['status']=='failed'
    resolve(srt['storage_key']).write_bytes(subtitle_bytes)
    assert client.post(f"/api/tasks/{missing['id']}/retry").status_code==200
    worker.run_once();result=task(missing['id'])
    assert result['status']=='succeeded' and result['attempt']==2,result['error']
    assert len(list(resolve(f"outputs/{missing['id']}").glob('video.*')))==1

def test_cancel_and_restart_reconcile(studio,monkeypatch):
    client,project,asset,upload,submit,task,resolve,factory=studio
    queued=submit({'duration':1})
    assert client.post(f"/api/tasks/{queued['id']}/cancel").json()['status']=='cancelled'
    assert not worker.run_once()
    running=submit({'duration':1})
    actual=renderer.execute_ffmpeg
    def cancel_during(args,work,duration,update,timeout=21600):
        client.post(f"/api/tasks/{running['id']}/cancel")
        return actual(args,work,duration,update,timeout)
    monkeypatch.setattr(renderer,'execute_ffmpeg',cancel_during)
    worker.run_once()
    assert task(running['id'])['status']=='cancelled'
    assert not resolve(f"outputs/{running['id']}/video.mp4").exists()
    monkeypatch.setattr(renderer,'execute_ffmpeg',actual)
    assert client.post(f"/api/tasks/{running['id']}/retry").status_code==200
    worker.run_once();result=task(running['id']);assert result['status']=='succeeded',result['error']
    path=resolve(result['output']['storage_key']);digest=hashlib.sha256(path.read_bytes()).hexdigest()
    with factory.begin() as db:
        row=db.get(Task,running['id'])
        row.status='running';row.output={};row.cancel_requested=False;row.lease_until=now()-timedelta(seconds=1)
    # Simulate death after publish before DB commit: recover without re-encoding/overwriting.
    worker.run_once();result=task(running['id'])
    assert result['status']=='succeeded' and result['output']['recovered']
    assert hashlib.sha256(path.read_bytes()).hexdigest()==digest

def test_encoding_failure_and_disk_space(studio,monkeypatch):
    client,project,asset,upload,submit,task,resolve,factory=studio
    original=renderer.execute_ffmpeg
    def fail(args,work,duration,update,timeout=21600):
        args[args.index('libx264')]='invalid_encoder_p2'
        return original(args,work,duration,update,timeout)
    monkeypatch.setattr(renderer,'execute_ffmpeg',fail)
    tid=submit({'duration':1})['id'];worker.run_once()
    assert task(tid)['status']=='failed' and 'FFmpeg' in task(tid)['error']
    monkeypatch.setattr(renderer,'execute_ffmpeg',original)
    client.post(f'/api/tasks/{tid}/retry');worker.run_once()
    assert task(tid)['status']=='succeeded'
    from collections import namedtuple
    monkeypatch.setattr(renderer.shutil,'disk_usage',lambda path:namedtuple('usage','total used free')(100,100,0))
    full=submit({'duration':1});worker.run_once()
    assert task(full['id'])['status']=='failed' and '磁盘' in task(full['id'])['error']

@pytest.mark.parametrize('mode',['invalid','wrong_duration'])
def test_exit_zero_is_not_success_without_output_validation(studio,monkeypatch,mode):
    client,project,asset,upload,submit,task,resolve,factory=studio
    def false_success(args,work,duration,update,timeout=21600):
        if mode=='invalid':Path(args[-1]).write_bytes(b'invalid output')
        else:Path(args[-1]).write_bytes(resolve(asset['storage_key']).read_bytes())
    monkeypatch.setattr(renderer,'execute_ffmpeg',false_success)
    tid=submit({'duration':1})['id'];worker.run_once()
    assert task(tid)['status']=='failed'
    assert not resolve(f'outputs/{tid}/video.mp4').exists()
    assert client.get(f'/api/tasks/{tid}/output').status_code==409

def test_migration_refuses_unsafe_downgrade(studio):
    client,project,asset,upload,submit,task,resolve,factory=studio
    submit({'duration':1})
    result=subprocess.run([sys.executable,'-m','alembic','downgrade','0001'],env={**os.environ,'DATABASE_URL':os.environ['TEST_DATABASE_URL']},capture_output=True,text=True)
    assert result.returncode!=0 and ('refusing unsafe P1 downgrade' in result.stderr or 'P3 audit records exist' in result.stderr or 'Active tasks exist' in result.stderr)
    from sqlalchemy import text
    with factory() as db:
        assert db.scalar(text('SELECT version_num FROM alembic_version'))=='0004'

from datetime import timedelta
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app import worker
from app.models import AnalysisRevision, Asset, MediaAnalysis, StoryEntity, Task
from app.perception_ocr import installed_languages
from test_render_postgres import studio
from test_postgres import database


def ffmpeg(*args):
    subprocess.run(['ffmpeg','-v','error','-y',*map(str,args)], check=True, timeout=35)


@pytest.fixture
def analysis(studio):
    client, project, asset, upload, _, task, resolve, factory = studio
    def submit(steps, asset_id=asset['id'], key=None):
        return client.post(f'/api/analysis/projects/{project}/tasks',
                           json={'asset_id':asset_id,'steps':steps,'idempotency_key':key or str(uuid4())})
    def complete(task_id):
        assert worker.run_once()
        state = task(task_id)
        assert state['status'] == 'succeeded', state['error']
        result = client.get(f'/api/analysis/tasks/{task_id}/result')
        assert result.status_code == 200, result.text
        return result.json()
    yield client, project, asset, upload, task, resolve, factory, submit, complete
    with factory.begin() as db:
        db.execute(delete(StoryEntity).where(StoryEntity.project_id == project))
        db.execute(delete(AnalysisRevision).where(AnalysisRevision.asset_id.in_(
            select(Asset.id).where(Asset.project_id == project))))
        db.execute(delete(MediaAnalysis).where(MediaAnalysis.task_id.in_(
            select(Task.id).where(Task.project_id == project))))


def test_real_multistream_analysis(analysis, tmp_path):
    client, _, _, upload, _, resolve, _, submit, complete = analysis
    srt=tmp_path/'local.srt'
    srt.write_text('1\n00:00:00,500 --> 00:00:01,500\n自行编写的字幕\n',encoding='utf-8')
    source=tmp_path/'multi.mkv'
    ffmpeg('-f','lavfi','-i','color=c=black:s=320x240:r=24:d=1',
           '-f','lavfi','-i','color=c=white:s=320x240:r=24:d=1',
           '-f','lavfi','-i','color=c=black:s=320x240:r=24:d=1',
           '-f','lavfi','-i','aevalsrc=if(lt(t\\,1)\\,0\\,0.4*sin(2*PI*440*t)):s=48000:d=3',
           '-f','lavfi','-i','sine=frequency=880:sample_rate=48000:duration=3',
           '-i',srt,'-filter_complex','[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]',
           '-map','[v]','-map','3:a','-map','4:a','-map','5:s','-c:v','libx264','-c:a','pcm_s16le',
           '-metadata:s:a:0','language=zho','-metadata:s:a:1','language=eng','-c:s','srt',source)
    asset=upload('授权样本.mkv',source.read_bytes())
    steps=[{'operation':op} for op in ('inspect','split','remux','transcode','frames','scenes','subtitles','waveform')]
    response=submit(steps,asset['id'],'full-flow')
    assert response.status_code == 201, response.text
    jobs=response.json()
    assert [j['id'] for j in submit(steps,asset['id'],'full-flow').json()] == [j['id'] for j in jobs]
    assert submit(steps[:-1],asset['id'],'full-flow').status_code == 409
    results={j['parameters']['operation']:complete(j['id']) for j in jobs}
    streams=results['inspect']['media']['streams']
    assert [s['codec_type'] for s in streams] == ['video','audio','audio','subtitle']
    assert [s['language'] for s in streams[1:3]] == ['zho','eng']
    assert results['inspect']['cadence']['0']['status'] == 'constant_sample'
    assert [a['source_streams'] for a in results['split']['artifacts']] == [[0],[1],[2],[3]]
    assert len(results['remux']['artifacts'][0]['streams']) == 4
    proxy=results['transcode']['artifacts'][0]
    assert [s['codec_name'] for s in proxy['streams']] == ['h264','aac']
    assert client.get(f"/api/analysis/tasks/{results['transcode']['task_id']}/artifacts/0",
                      headers={'Range':'bytes=0-99'}).status_code == 206
    assert results['frames']['artifacts'][0]['time_us'] == 0
    shots=results['scenes']['shots']
    assert [s['start_us'] for s in shots] == [0,1_000_000,2_000_000]
    assert abs(shots[-1]['end_us']-3_000_000) < 20_000
    assert all(s['score'] > .3 for s in shots[1:])
    cue=results['subtitles']['subtitle_tracks'][0]['cues'][0]
    assert cue == {'start_us':500_000,'end_us':1_500_000,'text':'自行编写的字幕'}
    wave=results['waveform']
    assert wave['bins'][0] == 0 and max(wave['bins']) > .3
    assert 990_000 <= wave['silences'][0]['end_us'] <= 1_010_000
    assert hashlib.sha256(resolve(asset['storage_key']).read_bytes()).hexdigest() == asset['sha256']
    assert client.get(f"/api/analysis/tasks/{results['scenes']['task_id']}/logs/1").json()['files']


def test_vfr_rotation_and_no_audio(analysis, tmp_path):
    _, _, _, upload, _, _, _, submit, complete = analysis
    base, rotated=tmp_path/'vfr.mp4',tmp_path/'rotated.mp4'
    ffmpeg('-f','lavfi','-i','testsrc2=size=360x240:rate=24:duration=2',
           '-vf',"select='lte(n,12)+not(mod(n,3))'",'-fps_mode','vfr','-c:v','libx264',base)
    ffmpeg('-display_rotation','90','-i',base,'-c','copy',rotated)
    asset=upload('rotated.mp4',rotated.read_bytes())
    jobs=submit([{'operation':op} for op in ('inspect','waveform','subtitles','transcode','frames')],asset['id']).json()
    data={j['parameters']['operation']:complete(j['id']) for j in jobs}
    assert abs(data['inspect']['media']['streams'][0]['rotation']) == 90
    assert data['inspect']['cadence']['0']['status'] == 'variable_sample'
    assert data['waveform']['audio_status'] == 'no_audio'
    assert data['subtitles']['subtitle_tracks'] == []
    stream=data['transcode']['artifacts'][0]['streams'][0]
    assert (stream['width'],stream['height']) == (240,360)


def test_cache_verification_and_additive_retry(analysis):
    client, _, _, _, task, resolve, factory, submit, complete=analysis
    job=submit([{'operation':'frames'}]).json()[0]
    first=complete(job['id'])
    reuse=submit([{'operation':'frames'}]).json()[0]
    assert complete(reuse['id'])['reused_from_task_id'] == job['id']
    with factory() as db:
        path=resolve(db.get(MediaAnalysis,job['id']).payload['artifacts'][0]['storage_key'])
    path.write_bytes(bytes(path.stat().st_size))
    regenerated=submit([{'operation':'frames'}]).json()[0]
    result=complete(regenerated['id'])
    assert not result.get('reused_from_task_id')
    assert result['artifacts'][0]['sha256'] == first['artifacts'][0]['sha256']
    failed=submit([{'operation':'waveform','stream':27}]).json()[0]
    assert worker.run_once()
    assert task(failed['id'])['status']=='failed'
    assert client.get(f"/api/analysis/tasks/{failed['id']}/result").status_code==404
    assert client.post(f"/api/tasks/{failed['id']}/retry").status_code==200
    assert worker.run_once()
    assert task(failed['id'])['attempt']==2 and task(regenerated['id'])['attempt']==1


def test_bad_input_and_queued_cancel(analysis):
    client, _, _, upload, task, _, _, submit, _=analysis
    bad=upload('broken.mp4',b'this does not contain a video')
    job=submit([{'operation':'inspect'}],bad['id']).json()[0]
    assert worker.run_once()
    assert task(job['id'])['status']=='failed'
    queued=submit([{'operation':'scenes'}]).json()[0]
    assert client.post(f"/api/tasks/{queued['id']}/cancel").status_code==200
    assert worker.run_once() is False and task(queued['id'])['status']=='cancelled'


def test_analysis_task_deep_link_is_scoped_to_asset_and_project(analysis):
    client, project, asset, _, _, _, _, submit, complete = analysis
    job = submit([{'operation':'inspect'}]).json()[0]
    path = f'/api/analysis/projects/{project}/assets/{asset["id"]}/tasks/{job["id"]}'
    assert client.get(path).json()['status'] == 'queued'
    complete(job['id'])
    assert client.get(path).json()['status'] == 'succeeded'
    assert client.get(path.replace(project, str(uuid4()))).status_code == 404
    assert client.get(path.replace(asset['id'], str(uuid4()))).status_code == 404


def test_review_snapshot_alignment_source_isolation_and_adoption(analysis):
    client, project, asset, upload, _, _, _, submit, complete = analysis
    jobs = submit([{'operation':'inspect'},{'operation':'scenes'}]).json()
    inspect, scenes = [complete(job['id']) for job in jobs]
    revision_path = f"/api/analysis/assets/{asset['id']}/revisions"
    candidate = {'kind':'scene','title':'自有场景采样','task_id':scenes['task_id'],'artifact':0}
    body = {
        'expected_version':0,'result_task_ids':[inspect['task_id'],scenes['task_id']],
        'cuts_us':[1_000_000],'note':'按原始媒体和固定关键帧进行人工审核',
        'evidence':[{'kind':'transcript','start_us':800_000,'end_us':1_200_000,'text':'自编对白'}],
        'candidates':[candidate],'idempotency_key':'first-review',
    }
    result=client.post(revision_path,json=body)
    assert result.status_code==201,result.text
    saved=result.json()
    assert saved['payload']['evidence'][0]['shots']==[1,2]
    assert saved['payload']['source_sha256']==asset['sha256']
    assert client.post(revision_path,json=body).json()['id']==saved['id']
    assert client.post(revision_path,json={**body,'idempotency_key':'stale'}).status_code==409
    other=upload('other.mp4',b'separate source')
    assert client.post(f"/api/analysis/assets/{other['id']}/revisions",json=body).status_code==422

    adopt_path=f"/api/analysis/revisions/{saved['id']}/adopt"
    response=client.post(adopt_path,json={
        'kind':'scene','candidate':0,'title':candidate['title'],
        'note':'批准用于自有测试项目','idempotency_key':'scene',
    })
    assert response.status_code==201,response.text
    scene=response.json()
    assets=client.get(f'/api/projects/{project}/assets').json()
    reference=next(item for item in assets if item['id']==scene['content']['reference_asset_ids'][0])
    assert reference['media_info']['derived_from_asset']==asset['id']
    assert reference['authorization']==asset['authorization']
    updated=client.post(revision_path,json={
        **body,'expected_version':1,'candidates':[{**candidate,'fixed_version_id':scene['version_id']}],
        'idempotency_key':'second-review',
    }).json()
    assert updated['number']==2
    script=client.post(f"/api/analysis/revisions/{updated['id']}/adopt",json={
        'kind':'script','title':'人工核验剧本','body':'自编对白',
        'note':'批准用于自有测试项目','idempotency_key':'script',
    })
    assert script.status_code==201,script.text
    assert script.json()['content']['scene_version_ids']==[scene['version_id']]
    assert script.json()['provenance']['analysis_sha256']==updated['content_hash']
    assert client.get(f"/api/analysis/revisions/{saved['id']}").json()==saved
    capabilities=client.get('/api/analysis/capabilities').json()['capabilities']
    assert len(capabilities)==5 and not any(item['available'] for item in capabilities if item['id']!='ocr')
    ocr=next(item for item in capabilities if item['id']=='ocr')
    assert ocr['available']==bool(ocr['languages'])


def test_windows_ocr_timestamps_original_hash_cache_and_review(analysis, tmp_path):
    font=Path(os.environ.get('SystemRoot','C:/Windows'))/'Fonts'/'simhei.ttf'
    if 'zh-Hans-CN' not in installed_languages() or not font.is_file():
        pytest.skip('Windows simplified-Chinese OCR recognizer and SimHei test font are required')
    client, _, _, upload, _, resolve, _, submit, complete=analysis
    shutil.copyfile(font,tmp_path/'fixture-font.ttf')
    source=tmp_path/'burned.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=white:s=960x540:r=24:d=1',
        '-f','lavfi','-i','color=c=black:s=960x540:r=24:d=1','-filter_complex',
        "[0:v]drawtext=fontfile=fixture-font.ttf:text='灯塔坐标':fontsize=105:fontcolor=black:x=(w-tw)/2:y=(h-th)/2[a];"
        '[a][1:v]concat=n=2:v=1:a=0[v]','-map','[v]','-c:v','libx264','-threads','2',str(source)],
        check=True,timeout=60,cwd=tmp_path)
    asset=upload('自制画面文字.mp4',source.read_bytes())
    assert submit([{'operation':'ocr','ocr_language':'xx-Absent'}],asset['id']).status_code==422
    steps=[{'operation':'scenes'},{'operation':'ocr','frame_interval':1,'ocr_language':'zh-Hans-CN'}]
    submitted=submit(steps,asset['id'],'ocr-test')
    assert submitted.status_code==201,submitted.text
    assert submitted.json()[1]['input_snapshot']['ocr']['language']=='zh-Hans-CN'
    job_ids=[job['id'] for job in submitted.json()]
    assert [job['id'] for job in submit(steps,asset['id'],'ocr-test').json()]==job_ids
    scenes, result=map(complete,job_ids)
    ocr=result['ocr']
    assert ocr['engine']=='windows-ocr-v1' and ocr['language']=='zh-Hans-CN'
    assert [frame['time_us'] for frame in ocr['frames']]==[0,1_000_000]
    assert ''.join(ocr['frames'][0]['text'].split())=='灯塔坐标'
    assert ocr['frames'][1]['text']=='' and ocr['frames'][1]['lines']==[]
    download=client.get(f"/api/analysis/tasks/{result['task_id']}/artifacts/0")
    assert download.status_code==200
    assert hashlib.sha256(download.content).hexdigest()==result['artifacts'][0]['sha256']
    replay=complete(submit(steps[1:],asset['id']).json()[0]['id'])
    assert replay['reused_from_task_id']==result['task_id']
    revision_request=client.post(f"/api/analysis/assets/{asset['id']}/revisions",json={
        'expected_version':0,'result_task_ids':[scenes['task_id'],result['task_id']],
        'note':'人工核对自制画面文字','idempotency_key':'ocr-review',
        'evidence':[{'kind':'screen_text','start_us':0,'end_us':1_000_000,'text':'灯塔坐标'}],
    })
    assert revision_request.status_code==201,revision_request.text
    snapshot=revision_request.json()['payload']
    assert snapshot['ocr_samples']==[{'start_us':0,'end_us':1,'artifact':0,'text':ocr['frames'][0]['text'],
        'task_id':result['task_id'],'origin':'ocr_sample','shots':[1]}]
    assert snapshot['evidence'][0]['origin']=='human' and snapshot['evidence'][0]['shots']==[1]
    assert snapshot['source_sha256']==hashlib.sha256(resolve(asset['storage_key']).read_bytes()).hexdigest()

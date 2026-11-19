import subprocess
from time import monotonic

import pytest
from sqlalchemy import delete, select

from app import worker
from app.models import ProductionRun, QualityReview, Task
from test_creative import creative
from test_postgres import database
from test_render_postgres import studio


@pytest.fixture
def series_fixture(creative):
    studio,create=creative
    client,project,video,upload,_,task,resolve,factory=studio
    root=f'/api/production/projects/{project}/runs'

    def prep(count,seconds=1):
        main=create('script','海港生产样本',{'body':'自编节目在港口完成短镜头制作。'})
        episodes=[]
        for index in range(1,count+1):
            episode=create('episode',f'海港 {index}',{'number':index,'body':'港口出现光线。','source_version_id':main['version_id']})
            board=create('storyboard',f'港口分镜 {index}',{'source_version_id':episode['version_id'],
                'shots':[{'number':1,'description':'港口画面','planned_duration':seconds}]})
            episodes.append({'episode_version_id':episode['version_id'],'storyboard_version_id':board['version_id'],
                             'target_duration_ms':round(seconds*1000)})
        bible=create('story_bible','海港生产计划',{'script_version_id':main['version_id'],'theme':'光线',
            'world':'虚构港口','episodes':episodes})
        approval=client.post(f"/api/series/entities/{bible['id']}/approve",json={
            'expected_version':1,'note':'完成样本审核','idempotency_key':'approved'})
        assert approval.status_code==201,approval.text
        return approval.json()['version_id']

    def timeline(plan,number,frames=24,linked=None,with_audio=True):
        linked=linked or video
        tracks=[{'id':'main','role':'main','clips':[{'id':'visual','asset_id':linked['id'],'at':0,'frames':frames}]}]
        if with_audio:
            tracks.append({'id':'voice','role':'dialogue','clips':[{'id':'audio','asset_id':video['id'],'at':0,'frames':frames}]})
        data=create('timeline',f'分集时间轴 {number}',{'source_version_id':plan,'profile':'square','frames':frames,'tracks':tracks})
        return {'number':number,'timeline_version_id':data['version_id']}

    yield studio,root,prep,timeline
    with factory.begin() as db:
        db.execute(delete(QualityReview).where(QualityReview.qc_task_id.in_(select(Task.id).where(Task.project_id==project))))
        db.execute(delete(ProductionRun).where(ProductionRun.project_id==project))


def test_series_qc_and_local_rework(series_fixture):
    studio,path,prep,timeline=series_fixture
    client,project,*_=studio
    plan=prep(3)
    entries=[timeline(plan,n,with_audio=n!=2) for n in range(1,4)]
    body={'plan_version_id':plan,'timelines':entries,'policy':{'require_audio':True},'idempotency_key':'normal'}
    response=client.post(path,json=body)
    assert response.status_code==201,response.text
    run=response.json()
    assert client.post(path,json=body).json()['id']==run['id']
    assert run['status']=='processing'
    for _ in range(6):
        assert worker.run_once()
    result_path='/api/production/runs/'+run['id']
    initial=client.get(result_path).json()
    assert initial['status']=='needs_rework'
    assert [entry['status'] for entry in initial['episodes']]==['passed','needs_rework','passed']
    blocked=initial['episodes'][1]
    assert blocked['qc']['issues'][0]['code']=='missing_audio'
    waiver={'expected_sha256':blocked['qc']['output_sha256'],'note':'Waive this failure','idempotency_key':'blocked'}
    assert client.post(result_path+'/episodes/2/review',json=waiver).status_code==409
    repair=client.post(path,json={**body,'previous_run_id':run['id'],'idempotency_key':'repair',
                                  'timelines':[timeline(plan,2)]})
    assert repair.status_code==201,repair.text
    repaired=repair.json()
    assert [item['reused'] for item in repaired['episodes']]==[True,False,True]
    assert worker.run_once() and worker.run_once()
    assert not worker.run_once()
    final=client.get('/api/production/runs/'+repaired['id']).json()
    assert final['status']=='passed' and final['passed']==3
    assert client.get(result_path).json()['status']=='needs_rework'


def test_dependency_failure_worker_and_cancel(series_fixture):
    studio,path,prep,timeline=series_fixture
    client,_,_,upload,_,task,*_=studio
    plan=prep(1)
    broken=upload('broken-input.mp4',b'not-a-video')
    broken_request={'plan_version_id':plan,'timelines':[timeline(plan,1,linked=broken)],
                    'idempotency_key':'broken'}
    first=client.post(path,json=broken_request).json()
    assert worker.run_once() and not worker.run_once()
    episode=client.get('/api/production/runs/'+first['id']).json()['episodes'][0]
    assert episode['render_status']=='failed' and episode['qc_stage']=='dependency_failed'
    assert task(episode['qc_task_id'])['attempt']==0
    queued=client.post(path,json={**broken_request,'idempotency_key':'queued',
                                 'timelines':[timeline(plan,1)]}).json()
    stopped=client.post('/api/production/runs/'+queued['id']+'/cancel').json()
    assert stopped['episodes'][0]['render_status']==stopped['episodes'][0]['qc_status']=='cancelled'
    assert not worker.run_once()


def test_real_twenty_episode_batch(series_fixture):
    studio,path,prep,timeline=series_fixture
    client,*_=studio
    plan=prep(20,seconds=.5)
    items=[timeline(plan,n,frames=12) for n in range(1,21)]
    submitted=client.post(path,json={'plan_version_id':plan,'timelines':items,'idempotency_key':'twenty'})
    assert submitted.status_code==201,submitted.text
    started=monotonic()
    for _ in range(40):
        assert worker.run_once()
    result=client.get('/api/production/runs/'+submitted.json()['id']).json()
    assert result['passed']==20,result
    assert not worker.run_once()
    print(f'20 actual 0.5-second episodes rendered and QC verified in {monotonic()-started:.2f}s')


def test_timed_black_warning_requires_explicit_review(series_fixture,tmp_path):
    studio,path,prep,timeline=series_fixture
    client,_,_,upload,*_=studio
    black=tmp_path/'black.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=black:s=320x240:rate=24:duration=1',
        '-c:v','libx264','-threads','1',str(black)],check=True,timeout=25)
    asset=upload('black.mp4',black.read_bytes())
    plan=prep(1)
    created=client.post(path,json={'plan_version_id':plan,'timelines':[timeline(plan,1,linked=asset,with_audio=False)],
                                  'idempotency_key':'deliberate-black'})
    assert created.status_code==201,created.text
    assert worker.run_once() and worker.run_once()
    route='/api/production/runs/'+created.json()['id']
    run=client.get(route).json()
    assert run['status']=='needs_review',run
    report=run['episodes'][0]['qc']
    warning=next(issue for issue in report['issues'] if issue['code']=='black_frames')
    assert warning['start_ms']==0 and warning['end_ms']>=900
    assert warning['clips']==['visual']
    ack={'expected_sha256':report['output_sha256'],'note':'片头黑场为人工确认的创作安排','idempotency_key':'approved'}
    response=client.post(route+'/episodes/1/review',json=ack)
    assert response.status_code==201 and response.json()['status']=='passed',response.text

import subprocess
from datetime import timedelta
from time import monotonic
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select

from app import quality, worker
from app.analysis_service import fingerprint
from app.models import ProductionRun, QualityReview, Task, now
from app.quality import audio_measurements, check_captions
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

    def timeline(plan,number,frames=24,linked=None,with_audio=True,caption=None):
        linked=linked or video
        tracks=[{'id':'main','role':'main','clips':[{'id':'visual','asset_id':linked['id'],'at':0,'frames':frames}]}]
        if with_audio:
            tracks.append({'id':'voice','role':'dialogue','clips':[{'id':'audio','asset_id':video['id'],'at':0,'frames':frames}]})
        if caption:
            tracks.append({'id':'subtitles','role':'caption','clips':[{'id':'subtitle','asset_id':caption['id'],'at':0,'frames':frames}]})
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


def test_recheck_reuses_render_and_records_measured_quality(series_fixture,monkeypatch):
    studio,path,prep,timeline=series_fixture
    client,project,_,upload,_,task,resolve,factory=studio
    plan=prep(1)
    subtitle=upload('自编字幕.srt','1\n00:00:00,000 --> 00:00:00,850\n自编港口画面\n'.encode())
    default={'require_audio':True,'require_subtitles':True,'black_ms':500,'freeze_ms':750,'silence_ms':1000,'silence_db':-45}
    body={'plan_version_id':plan,'timelines':[timeline(plan,1,caption=subtitle)],'policy':default,'idempotency_key':'measured'}
    made=client.post(path,json=body)
    assert made.status_code==201,made.text
    run=made.json()
    with factory() as db:
        old_signature={'plan_version_id':plan,'previous_run_id':None,'timelines':body['timelines'],'policy':default}
        assert db.get(ProductionRun,run['id']).request_hash==fingerprint(old_signature)
    assert worker.run_once() and worker.run_once()
    first=client.get(path+'/'+run['id']).json()['episodes'][0]
    assert first['status']=='passed'
    assert first['qc']['captions']['cue_count']==1 and first['qc']['captions']['status']=='verified'
    assert first['qc']['video']=={'width':720,'height':720,'frames':24,'frame_rate':'24/1'}
    assert first['qc']['captions']['sha256']==task(first['render_task_id'])['output']['caption_sha256']
    assert first['qc']['audio']['status']=='measured'
    assert -40<first['qc']['audio']['integrated_lufs']<-12
    assert -40<first['qc']['audio']['true_peak_dbtp']<0
    replay=client.post(path,json={**body,'recheck_quality':False,'policy':{**default,'min_integrated_lufs':None}})
    assert replay.status_code==201 and replay.json()['id']==run['id']
    assert client.post(path,json={**body,'idempotency_key':'empty','timelines':[]}).status_code==422

    strict={**default,'min_integrated_lufs':-12}
    recheck={'plan_version_id':plan,'previous_run_id':run['id'],'timelines':[],
             'recheck_quality':True,'policy':strict,'idempotency_key':'sound-check'}
    cancelled=client.post(path,json={**recheck,'idempotency_key':'cancel-recheck'}).json()
    stopped=client.post('/api/production/runs/'+cancelled['id']+'/cancel').json()
    assert stopped['status']=='cancelled'
    assert stopped['episodes'][0]['qc_status']=='cancelled'
    assert task(first['render_task_id'])['status']=='succeeded'
    assert not worker.run_once()
    pending=client.post(path,json=recheck)
    assert pending.status_code==201,pending.text
    pending=pending.json()
    assert pending['reused']==0 and pending['rechecked']==1
    new=pending['episodes'][0]
    assert new['render_reused'] and new['render_task_id']==first['render_task_id']
    assert new['qc_task_id']!=first['qc_task_id']
    def interrupt_decode(self, argv, stage, progress, timeout):
        self.update(stage,progress)
        raise KeyboardInterrupt

    with monkeypatch.context() as patch:
        patch.setattr(quality.Commands,'run',interrupt_decode)
        with pytest.raises(KeyboardInterrupt):
            worker.run_once()
    assert client.get(path+'/'+pending['id']).json()['episodes'][0]['qc'] is None
    with factory.begin() as db:
        db.get(Task,new['qc_task_id']).lease_until=now()-timedelta(seconds=1)
    assert worker.run_once() and not worker.run_once()
    attempts=client.get('/api/tasks/'+new['qc_task_id']+'/attempts').json()
    assert [attempt['status'] for attempt in attempts]==['interrupted','succeeded']
    log=client.get('/api/tasks/'+new['qc_task_id']+'/attempts/2/logs').json()
    assert log['available'] and 'Integrated loudness' in log['text']
    assert task(first['render_task_id'])['attempt']==1
    latest=client.get(path+'/'+pending['id']).json()
    assert latest['status']=='needs_review'
    report=latest['episodes'][0]['qc']
    assert report['output_sha256']==first['qc']['output_sha256']
    assert report['audio']==first['qc']['audio']
    assert [finding['code'] for finding in report['issues']]==['low_loudness']
    downloaded=client.get(path+'/'+pending['id'],params={'download':'true'})
    assert downloaded.status_code==200 and 'attachment;' in downloaded.headers['content-disposition']
    assert downloaded.json()==latest
    assert client.get(path.replace(project,str(uuid4()))+'/'+pending['id']+'?download=true').status_code==404
    assert client.get(path+'/'+run['id']).json()['status']=='passed'

    caption=resolve(task(first['render_task_id'])['output']['caption_storage_key'])
    caption.write_bytes(b'changed')
    assert client.post('/api/production/runs/'+pending['id']+'/episodes/1/review',json={
        'expected_sha256':report['output_sha256'],'note':'验收复核','idempotency_key':'tampered-review'}).status_code==409
    repaired=client.post(path,json={**recheck,'idempotency_key':'damaged-caption'}).json()['episodes'][0]
    assert not repaired['render_reused'] and repaired['render_task_id']!=first['render_task_id']


def test_caption_integrity_format_and_timing(studio):
    _,_,_,_,_,_,resolve,_=studio
    key='outputs/test-captions.srt'
    path=resolve(key)
    path.parent.mkdir(exist_ok=True)
    render=SimpleNamespace(id='test',attempt=1,output={'caption_storage_key':key})
    issues=[]
    def check():
        issues.clear()
        check_captions(render,True,True,1000,lambda code,level,*_:issues.append((code,level)))
        return issues[:]
    assert check()==[('missing_subtitles','error')]
    path.write_bytes(b'not an SRT')
    assert check()==[('subtitle_format','error')]
    path.write_text('1\n00:00:00,000 --> 00:00:02,000\nout of bounds\n',encoding='utf-8')
    assert check()==[('subtitle_bounds','error')]
    path.write_text('1\n00:00:00,100 --> 00:00:00,800\nA\n\n2\n00:00:00,700 --> 00:00:00,900\nB\n',encoding='utf-8')
    assert check()==[('subtitle_overlap','error')]
    render.output['caption_sha256']='0'*64
    assert check()==[('subtitle_integrity','error')]


def test_audio_parser_does_not_report_gate_floor_as_measurement():
    empty='Summary:\n  Integrated loudness:\n    I: -70.0 LUFS\n  True peak:\n    Peak: -inf dBFS\n'
    assert audio_measurements(empty)=={'status':'below_gate_or_short','integrated_lufs':None,'true_peak_dbtp':None}
    measured='Summary:\n  Integrated loudness:\n    I: -23.1 LUFS\n  True peak:\n    Peak: -1.2 dBFS\n'
    assert audio_measurements(measured)=={'status':'measured','integrated_lufs':-23.1,'true_peak_dbtp':-1.2}

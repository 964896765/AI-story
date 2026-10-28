import errno
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pytest
from sqlalchemy import select,func
from app import worker
from app import render as renderer
from app.models import Task,TaskAttempt,Batch,QueueControl,WorkerNode,now
from app.heartbeat import Heartbeat
from app.reliability import classify_error,retry_delay
from test_postgres import database
from test_render_postgres import studio

@pytest.mark.parametrize('error,code,retryable',[(TimeoutError(),'TIMEOUT',True),(FileNotFoundError(),'FILE_OR_TOOL_MISSING',False),(OSError(errno.ENOSPC,'full'),'DISK_FULL',False),(OSError(errno.EBUSY,'busy'),'RESOURCE_BUSY',True),(ValueError(),'INVALID_INPUT_OR_OUTPUT',False),(ConnectionError(),'HEARTBEAT_LOST',True)])
def test_error_policy(error,code,retryable):
    assert classify_error(error)==(code,retryable)
    assert retry_delay(1)==5 and retry_delay(2)==10 and retry_delay(100)==60

def test_atomic_batch_concurrent_idempotency_and_invalid_input(studio):
    client,project,asset,upload,submit,task,resolve,factory=studio
    other=upload('second.mp4',resolve(asset['storage_key']).read_bytes())
    body={'asset_ids':[asset['id'],other['id']],'parameters':{'duration':1},'idempotency_key':'batch-race'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.post(f'/api/projects/{project}/batches',json=body),range(2)))
    assert all(r.status_code==201 for r in results),[r.text for r in results]
    assert results[0].json()['batch']['id']==results[1].json()['batch']['id']
    assert len(client.get(f'/api/projects/{project}/tasks').json())==2
    assert client.post(f'/api/projects/{project}/batches',json={**body,'parameters':{'duration':0.5}}).status_code==409
    invalid={**body,'idempotency_key':'invalid','asset_ids':[asset['id'],'does-not-exist']}
    assert client.post(f'/api/projects/{project}/batches',json=invalid).status_code==404
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Batch).where(Batch.project_id==project))==1
    duplicate={**body,'idempotency_key':'duplicate','asset_ids':[asset['id'],asset['id']]}
    assert client.post(f'/api/projects/{project}/batches',json=duplicate).status_code==422
    worker.run_once();worker.run_once()
    assert all(t['status']=='succeeded' for t in client.get(f'/api/projects/{project}/tasks').json())

def test_pause_is_persistent_and_queued_cancel_still_works(studio):
    client,project,asset,upload,submit,task,resolve,factory=studio
    tid=submit({'duration':1})['id']
    try:
        assert client.post('/api/queue',json={'paused':True}).status_code==200
        with factory() as db:assert db.get(QueueControl,'local').paused
        assert worker.run_once() is False and task(tid)['status']=='queued'
        assert client.post(f'/api/tasks/{tid}/cancel').json()['status']=='cancelled'
        waiting=submit({'duration':1})['id']
        client.post('/api/queue',json={'paused':False})
        worker.run_once();assert task(waiting)['status']=='succeeded'
    finally:client.post('/api/queue',json={'paused':False})

def test_independent_heartbeat_while_stage_is_blocked(studio,monkeypatch):
    import threading
    client,project,asset,upload,submit,task,resolve,factory=studio
    tid=client.post(f'/api/projects/{project}/tasks',json={'asset_id':asset['id'],'idempotency_key':'probe-heartbeat'}).json()['id']
    original=worker.probe
    entered,release=threading.Event(),threading.Event()
    def blocking(path):
        entered.set();assert release.wait(10)
        return original(path)
    monkeypatch.setattr(worker,'probe',blocking)
    with Heartbeat(factory) as heartbeat:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(worker.run_once,heartbeat)
            try:
                assert entered.wait(5)
                time.sleep(2.4)
                state=client.get('/api/queue').json()
                live=next(w for w in state['workers'] if w['id']==heartbeat.id)
                assert live['online'] and live['state']=='busy' and live['task_id']==tid
                with factory() as db:
                    db.get(WorkerNode,heartbeat.id)
                    assert db.get(Task,tid).lease_until>now()+timedelta(seconds=20)
                client.post('/api/queue',json={'paused':True})
            finally:
                release.set()
                client.post('/api/queue',json={'paused':False})
            assert pending.result(timeout=10)
    assert task(tid)['status']=='succeeded'
    attempts=client.get(f'/api/tasks/{tid}/attempts').json()
    assert attempts[0]['status']=='succeeded' and attempts[0]['elapsed_seconds']>=2.4

def test_timeout_backoff_is_bounded_and_preserves_attempts(studio,monkeypatch):
    client,project,asset,upload,submit,task,resolve,factory=studio
    def timeout(*args,**kwargs):raise TimeoutError('injected test timeout')
    monkeypatch.setattr(renderer,'execute_ffmpeg',timeout)
    tid=submit({'duration':1})['id']
    for attempt in range(1,4):
        assert worker.run_once()
        result=task(tid)
        assert result['attempt']==attempt and result['error_code']=='TIMEOUT'
        if attempt<3:
            assert result['status']=='queued' and result['stage']=='retry_wait'
            assert worker.run_once() is False
            with factory.begin() as db:db.get(Task,tid).next_run_at=now()-timedelta(seconds=1)
        else:assert result['status']=='failed'
    attempts=client.get(f'/api/tasks/{tid}/attempts').json()
    assert [a['number'] for a in attempts]==[1,2,3] and all(a['error_code']=='TIMEOUT' for a in attempts)
    assert all(a['inputs']['video']['sha256']==asset['sha256'] for a in attempts)

def test_encoded_checkpoint_resumes_without_encoder(studio,monkeypatch):
    client,project,asset,upload,submit,task,resolve,factory=studio
    original=worker.render
    def interrupted(task_id,attempt,parameters,inputs,update):
        def stage(name,progress):
            if name=='validating':raise RuntimeError('simulated interruption after encoding')
            update(name,progress)
        return original(task_id,attempt,parameters,inputs,stage)
    monkeypatch.setattr(worker,'render',interrupted)
    tid=submit({'duration':1})['id'];worker.run_once()
    assert task(tid)['status']=='failed'
    partial=resolve(f'tmp/{tid}/1/partial.mp4')
    assert partial.exists() and resolve(f'tmp/{tid}/1/manifest.json').exists()
    monkeypatch.setattr(worker,'render',original)
    def forbidden(*args,**kwargs):pytest.fail('encoded checkpoint must avoid a second encode')
    monkeypatch.setattr(renderer,'execute_ffmpeg',forbidden)
    client.post(f'/api/tasks/{tid}/retry');worker.run_once()
    result=task(tid)
    assert result['status']=='succeeded' and result['output']['resumed_from_attempt']==1,result['error']
    assert not partial.exists() and resolve(result['output']['storage_key']).exists()
    history=client.get(f'/api/tasks/{tid}/attempts').json()
    assert [a['status'] for a in history]==['failed','succeeded']
    assert any(p['stage']=='resuming_checkpoint' for p in history[1]['checkpoints'])

def test_corrupt_checkpoint_is_not_reused(studio,monkeypatch):
    client,project,asset,upload,submit,task,resolve,factory=studio
    original=worker.render
    def interrupted(task_id,attempt,parameters,inputs,update):
        def stage(name,progress):
            if name=='validating':raise RuntimeError('interrupted')
            update(name,progress)
        return original(task_id,attempt,parameters,inputs,stage)
    monkeypatch.setattr(worker,'render',interrupted)
    tid=submit({'duration':1})['id'];worker.run_once()
    resolve(f'tmp/{tid}/1/partial.mp4').write_bytes(b'corrupt checkpoint')
    monkeypatch.setattr(worker,'render',original)
    client.post(f'/api/tasks/{tid}/retry');worker.run_once()
    result=task(tid)
    assert result['status']=='succeeded' and result['output']['resumed_from_attempt'] is None

def test_attempt_logs_are_bounded_and_summary_is_observed(studio):
    client,project,asset,upload,submit,task,resolve,factory=studio
    tid=submit({'duration':1})['id'];worker.run_once()
    history=client.get(f'/api/tasks/{tid}/attempts').json()
    assert history[0]['parameters']['duration']==1
    resolve(f'tmp/{tid}/1/ffmpeg.log').write_bytes(b'x'*70000)
    logs=client.get(f'/api/tasks/{tid}/attempts/1/logs').json()
    assert logs['truncated'] and len(logs['text'])==65536
    assert client.get(f'/api/tasks/{tid}/attempts/-1/logs').status_code==404
    summary=client.get(f'/api/projects/{project}/production-summary').json()
    assert summary['attempts']==1 and summary['observed_processing_seconds']>0
    assert summary['recorded_cents']==0 and summary['counts']['succeeded']==1
    assert summary['by_task'][0]['task_id']==tid

def test_live_lease_blocks_a_new_claim_without_advisory_owner(studio):
    client,project,asset,upload,submit,task,resolve,factory=studio
    first=submit({'duration':1})['id'];second=submit({'duration':1})['id']
    with factory.begin() as db:
        row=db.get(Task,first)
        row.status='running';row.attempt=1;row.lease_until=now()+timedelta(seconds=30);row.worker_token='lost-advisory-connection'
    assert worker.run_once() is False
    assert task(second)['status']=='queued'
    with factory.begin() as db:db.get(Task,first).lease_until=now()-timedelta(seconds=1)
    worker.run_once();worker.run_once()
    assert task(first)['status']=='succeeded' and task(second)['status']=='succeeded'

def test_heartbeat_loss_stops_processing_and_schedules_reconcile(studio,monkeypatch):
    client,project,asset,upload,submit,task,resolve,factory=studio
    tid=submit({'duration':1})['id']
    original=worker.render
    with Heartbeat(factory) as heartbeat:
        def lose(task_id,attempt,parameters,inputs,update):
            heartbeat.lost.set()
            return original(task_id,attempt,parameters,inputs,update)
        monkeypatch.setattr(worker,'render',lose)
        worker.run_once(heartbeat)
    result=task(tid)
    assert result['status']=='queued' and result['error_code']=='HEARTBEAT_LOST'
    assert not resolve(f'outputs/{tid}/video.mp4').exists()

def test_currencies_are_never_added_together(studio):
    # Synthetic ledger entries in the disposable test DB only, never a real charge.
    from app.models import CostEntry
    from sqlalchemy import delete
    client,project,asset,upload,submit,task,resolve,factory=studio
    tid=submit({'duration':1})['id'];worker.run_once()
    try:
        with factory.begin() as db:
            for currency,amount in [('CNY',123),('USD',456)]:
                db.add(CostEntry(project_id=project,task_id=tid,provider='TEST_FIXTURE_NOT_A_REAL_CHARGE',amount_cents=amount,currency=currency,reference=tid+currency))
        for endpoint in ('costs','production-summary'):
            data=client.get(f'/api/projects/{project}/{endpoint}').json()
            assert data['recorded_cents']==123 and data['recorded_by_currency']=={'CNY':123,'USD':456}
    finally:
        with factory.begin() as db:db.execute(delete(CostEntry).where(CostEntry.task_id==tid))

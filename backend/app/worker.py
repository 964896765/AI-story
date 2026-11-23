"""Persistent worker. PostgreSQL advisory lock limits all workers to one job."""
import time
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import or_, select, text
from sqlalchemy.orm import aliased
from .db import Session
from .models import Task, TaskEvent, Asset, TaskAttempt, MediaAnalysis, now
from .storage import resolve_key
from .media import probe
from .render import render, Cancelled
from .heartbeat import Heartbeat
from .reliability import queue_control, attempt_record, classify_error, schedule_retry

LOCK_ID = 719031002
LEASE_SECONDS = 30

def event(db, task, message):
    db.add(TaskEvent(task_id=task.id, attempt=task.attempt, message=message))

def cancel_failed_dependencies(db):
    parent=aliased(Task)
    failed=select(parent.id).where(parent.status.in_(('failed','cancelled')))
    dependents=db.scalars(select(Task).where(Task.status=='queued',Task.dependency_task_id.in_(failed))
                          .with_for_update(skip_locked=True)).all()
    for task in dependents:
        task.status,task.stage,task.finished_at='cancelled','dependency_failed',now()
        task.error_code,task.error='DEPENDENCY_FAILED','上游任务失败或取消，未执行本步骤'
        event(db,task,task.error)

def recover_expired(db):
    for task in db.scalars(select(Task).where(Task.status == 'running', Task.lease_until < now()).with_for_update()).all():
        task.worker_token, task.lease_until = None, None
        previous=attempt_record(db,task)
        if previous and previous.status=='running':
            previous.status,previous.finished_at='interrupted',now()
            previous.error_code,previous.error='WORKER_LOST','Worker lease expired'
            previous.elapsed_seconds=task.elapsed_seconds
        task.error_code='WORKER_LOST'
        if task.kind=='adapt':
            from .text_service import recover_adapt_task
            recover_adapt_task(db,task)
            event(db,task,'文本调用中断已核对，未自动重发请求')
            continue
        if task.cancel_requested:
            task.status, task.stage = 'cancelled', 'cancelled'
            task.finished_at = now()
        elif task.kind in ('render', 'analyze', 'still_motion', 'local_voice', 'timeline_render', 'qc_review', 'delivery', 'promotion') and task.attempt < task.max_attempts:
            task.status, task.stage, task.progress = 'queued', 'recovered', 0
            task.next_run_at=now()
        else:
            task.status, task.stage = 'failed', 'failed'
            task.error = 'Worker lease expired; safe to retry local task'
            task.finished_at = now()
        event(db, task, '检测到 Worker 中断；已安全恢复为 '+task.status)

def _run_once(heartbeat):
    with Session.begin() as db:
        control=queue_control(db)
        recover_expired(db)
        from .text_service import recover_detached_calls
        recover_detached_calls(db)
        cancel_failed_dependencies(db)
        # A live lease is a second concurrency fence if the advisory connection was lost.
        if control.paused or db.scalar(select(Task.id).where(Task.status=='running').limit(1)):
            return False
        parent=aliased(Task)
        succeeded=select(parent.id).where(parent.id==Task.dependency_task_id,parent.status=='succeeded').exists()
        task = db.scalar(select(Task).where(Task.status == 'queued',Task.next_run_at<=now(),
            or_(Task.dependency_task_id.is_(None),succeeded)).order_by(Task.created_at,Task.id)
            .with_for_update(skip_locked=True).limit(1))
        if not task:
            return False
        task.status, task.stage, task.progress = 'running', 'inspecting', 0
        task.attempt += 1
        task.started_at, task.finished_at = now(), None
        task.lease_until = now() + timedelta(seconds=LEASE_SECONDS)
        task.worker_token = str(uuid4())
        task.error = None
        task.error_code,task.elapsed_seconds=None,0
        if not task.input_snapshot:
            asset = db.get(Asset,task.asset_id)
            task.input_snapshot = {'video':{'id':asset.id,'storage_key':asset.storage_key,'sha256':asset.sha256}}
        event(db, task, '开始执行 '+task.kind)
        task_id, attempt, token, kind = task.id, task.attempt, task.worker_token, task.kind
        inputs, parameters = task.input_snapshot, task.parameters
        db.add(TaskAttempt(task_id=task_id,number=attempt,worker_id=heartbeat.id,status='running',stage='inspecting',inputs=inputs,parameters=parameters,checkpoints=[{'stage':'inspecting','at':now().isoformat()}]))
    heartbeat.bind(task_id,token)
    started, last_update, previous_stage = time.monotonic(), 0.0, None

    def update(stage, progress):
        nonlocal last_update, previous_stage
        if heartbeat.lost.is_set():
            raise ConnectionError('Worker heartbeat or ownership lost; stop and reconcile local output')
        if stage == previous_stage and time.monotonic()-last_update < 0.4:
            return
        with Session.begin() as db:
            task = db.scalar(select(Task).where(Task.id==task_id).with_for_update())
            if task.status != 'running' or task.worker_token != token:
                raise Cancelled('任务所有权已失效')
            if task.cancel_requested:
                raise Cancelled('用户取消任务')
            if task.stage != stage:
                event(db,task,'执行阶段：'+stage)
            record=attempt_record(db,task)
            if record.stage!=stage:
                record.checkpoints=[*record.checkpoints,{'stage':stage,'at':now().isoformat()}]
            record.stage=stage
            task.stage, task.progress = stage, progress
            task.elapsed_seconds = time.monotonic()-started
            record.elapsed_seconds=task.elapsed_seconds
            task.lease_until = now()+timedelta(seconds=LEASE_SECONDS)
        last_update = time.monotonic()
        previous_stage = stage

    output, error, cancelled,code,retryable = {}, None, False,None,False
    analysis_result = None
    try:
        if kind == 'render':
            output = render(task_id,attempt,parameters,inputs,update)
        elif kind == 'probe':
            with Session.begin() as db:
                db.get(Task,task_id).lease_until = now()+timedelta(seconds=120)
            output = probe(resolve_key(inputs['video']['storage_key']))
        elif kind=='adapt':
            from .text_service import execute_text_task
            output=execute_text_task(task_id,Session)
        elif kind == 'analyze':
            from .analysis_service import execute_analysis
            analysis_result = execute_analysis(task_id, attempt, parameters, inputs, update, Session)
            _, payload = analysis_result
            output = {'operation': payload['operation'], 'artifact_count': len(payload['artifacts']),
                      'reused_from_task_id': payload.get('reused_from_task_id')}
        elif kind == 'still_motion':
            from .generation import build_motion
            output = build_motion(task_id,attempt,parameters,inputs,update,Session)
        elif kind == 'local_voice':
            from .voice import render_voice
            output = render_voice(task_id,attempt,parameters,inputs,update)
        elif kind == 'timeline_render':
            from .timeline_render import timeline_render
            output = timeline_render(task_id,attempt,parameters,inputs,update)
        elif kind == 'qc_review':
            from .quality import qa_output
            with Session() as db:
                origin = db.get(Task,inputs['render_task_id'])
                if origin is None or origin.status!='succeeded':
                    raise ValueError('上游产物尚未通过渲染')
                output = qa_output(origin,parameters,update,task_id,attempt,dialogue=inputs.get('dialogue'))
                if spec := inputs.get('production_spec'):
                    output['production_spec'] = {key:spec[key] for key in ('id','version','sha256')}
        elif kind == 'delivery':
            from .delivery import deliver
            output = deliver(task_id,attempt,parameters,inputs,update,Session)
        elif kind == 'promotion':
            from .distribution import render_promotion
            output=render_promotion(task_id,attempt,parameters,inputs,update,Session)
        else:
            raise ValueError('未知任务类型：'+kind)
    except Cancelled as exc:
        error, cancelled = str(exc), True
        code='CANCELLED'
    except Exception as exc:
        error = str(exc)[-4000:]
        code,retryable=classify_error(exc)
        if kind=='adapt':code=getattr(exc,'code','MODEL_PROCESSING_INTERRUPTED');retryable=False
    with Session.begin() as db:
        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if task.status != 'running' or task.worker_token != token:
            return True
        if kind=='adapt':
            from .text_service import require_call_by_task
            call=require_call_by_task(db,task.id)
            output={'model_call_id':call.id,'status':call.status,'simulated':call.simulated,'review_required':call.status=='awaiting_review','accepted_version_id':call.accepted_version_id}
            if call.status in ('awaiting_review','accepted','rejected'):error=None;code=None;cancelled=False
            elif call.status=='cancelled':cancelled=True
        # Publication wins a cancellation racing the final atomic publish.
        if task.cancel_requested and not (kind in ('render','still_motion','local_voice','timeline_render','delivery','promotion') and output):
            cancelled = True
            if kind == 'analyze':
                output = {}
        task.status = 'cancelled' if cancelled else ('failed' if error else 'succeeded')
        task.stage = task.status
        task.output, task.error = output, error
        task.error_code=code
        task.lease_until, task.worker_token = None, None
        task.finished_at, task.elapsed_seconds = now(), time.monotonic()-started
        if task.status == 'succeeded':
            task.progress = 100
            if kind == 'probe':
                asset = db.get(Asset,task.asset_id)
                asset.media_info = {**asset.media_info,**output}
            if kind=='adapt':task.stage={'awaiting_review':'awaiting_review','accepted':'approved','rejected':'rejected'}.get(output.get('status'),'succeeded')
            if kind == 'analyze':
                signature, payload = analysis_result
                db.add(MediaAnalysis(task_id=task.id, signature=signature, payload=payload))
        record=attempt_record(db,task)
        record.status,record.stage=task.status,task.stage
        record.finished_at,record.elapsed_seconds=task.finished_at,task.elapsed_seconds
        record.error,record.error_code,record.output=error,code,output
        record.checkpoints=[*record.checkpoints,{'stage':task.status,'at':now().isoformat()}]
        if kind!='adapt' and task.status=='failed' and retryable and task.attempt<task.max_attempts:
            schedule_retry(task)
            event(db,task,'可恢复错误，已安排延迟重试：'+code)
        success_message={'render':'执行完成，输出已验证','probe':'媒体信息读取完成','adapt':'文本调用已记录处理结果',
                         'still_motion':'运镜候选已验证',
                         'local_voice':'配音、时间与字幕已验证',
                         'timeline_render':'多轨成片已解码验证',
                         'qc_review':'已保存真实技术质检结果',
                         'delivery':'交付包与文件哈希已核验',
                         'promotion':'实际推广片段和封面已制作，等待人工审阅',
                         'analyze':'解析结果已持久化' if task.status == 'succeeded' else '解析步骤已取消'}
        event(db,task,error or success_message[kind])
    return True

def run_once(heartbeat=None):
    if heartbeat is None:
        with Heartbeat(Session) as local:
            return run_once(local)
    with Session() as guard:
        if not guard.scalar(text('SELECT pg_try_advisory_lock(:key)'),{'key':LOCK_ID}):
            return False
        try:
            return _run_once(heartbeat)
        finally:
            heartbeat.clear()
            guard.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':LOCK_ID})

if __name__ == '__main__':
    while True:
        try:
            with Heartbeat(Session) as heartbeat:
                while True:
                    try:
                        if not run_once(heartbeat):time.sleep(1)
                    except KeyboardInterrupt:raise
                    except Exception as exc:
                        print(f'Worker error: {type(exc).__name__}: {exc}',flush=True)
                        time.sleep(3)
        except KeyboardInterrupt:break
        except Exception as exc:
            print(f'Worker startup unavailable: {type(exc).__name__}',flush=True)
            time.sleep(3)

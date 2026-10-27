"""Persistent worker. PostgreSQL advisory lock limits all workers to one job."""
import time
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select, text
from .db import Session
from .models import Task, TaskEvent, Asset, now
from .storage import resolve_key
from .media import probe
from .render import render, Cancelled

LOCK_ID = 719031002
LEASE_SECONDS = 30

def event(db, task, message):
    db.add(TaskEvent(task_id=task.id, attempt=task.attempt, message=message))

def recover_expired(db):
    for task in db.scalars(select(Task).where(Task.status == 'running', Task.lease_until < now()).with_for_update()).all():
        task.worker_token, task.lease_until = None, None
        if task.cancel_requested:
            task.status, task.stage = 'cancelled', 'cancelled'
            task.finished_at = now()
        elif task.kind == 'render' and task.attempt < 3:
            task.status, task.stage, task.progress = 'queued', 'recovered', 0
        else:
            task.status, task.stage = 'failed', 'failed'
            task.error = 'Worker lease expired; safe to retry local task'
            task.finished_at = now()
        event(db, task, '检测到 Worker 中断；已安全恢复为 '+task.status)

def _run_once():
    with Session.begin() as db:
        recover_expired(db)
        task = db.scalar(select(Task).where(Task.status == 'queued').order_by(Task.created_at).with_for_update(skip_locked=True).limit(1))
        if not task:
            return False
        task.status, task.stage, task.progress = 'running', 'inspecting', 0
        task.attempt += 1
        task.started_at, task.finished_at = now(), None
        task.lease_until = now() + timedelta(seconds=LEASE_SECONDS)
        task.worker_token = str(uuid4())
        task.error = None
        if not task.input_snapshot:
            asset = db.get(Asset,task.asset_id)
            task.input_snapshot = {'video':{'id':asset.id,'storage_key':asset.storage_key,'sha256':asset.sha256}}
        event(db, task, '开始执行 '+task.kind)
        task_id, attempt, token, kind = task.id, task.attempt, task.worker_token, task.kind
        inputs, parameters = task.input_snapshot, task.parameters
    started, last_update, previous_stage = time.monotonic(), 0.0, None

    def update(stage, progress):
        nonlocal last_update, previous_stage
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
            task.stage, task.progress = stage, progress
            task.elapsed_seconds = time.monotonic()-started
            task.lease_until = now()+timedelta(seconds=LEASE_SECONDS)
        last_update = time.monotonic()
        previous_stage = stage

    output, error, cancelled = {}, None, False
    try:
        if kind == 'render':
            output = render(task_id,attempt,parameters,inputs,update)
        elif kind == 'probe':
            with Session.begin() as db:
                db.get(Task,task_id).lease_until = now()+timedelta(seconds=120)
            output = probe(resolve_key(inputs['video']['storage_key']))
        else:
            raise ValueError('未知任务类型：'+kind)
    except Cancelled as exc:
        error, cancelled = str(exc), True
    except Exception as exc:
        error = str(exc)[-4000:]
    with Session.begin() as db:
        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if task.status != 'running' or task.worker_token != token:
            return True
        # Publication wins a cancellation racing the final atomic publish.
        if task.cancel_requested and not (kind=='render' and output):
            cancelled = True
        task.status = 'cancelled' if cancelled else ('failed' if error else 'succeeded')
        task.stage = task.status
        task.output, task.error = output, error
        task.lease_until, task.worker_token = None, None
        task.finished_at, task.elapsed_seconds = now(), time.monotonic()-started
        if task.status == 'succeeded':
            task.progress = 100
            if kind == 'probe': db.get(Asset,task.asset_id).media_info = output
        event(db,task,error or ('执行完成，输出已验证' if kind=='render' else '媒体信息读取完成'))
    return True

def run_once():
    with Session() as guard:
        if not guard.scalar(text('SELECT pg_try_advisory_lock(:key)'),{'key':LOCK_ID}):
            return False
        try:
            return _run_once()
        finally:
            guard.execute(text('SELECT pg_advisory_unlock(:key)'),{'key':LOCK_ID})

if __name__ == '__main__':
    while True:
        try:
            if not run_once(): time.sleep(1)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f'Worker error: {exc}', flush=True)
            time.sleep(3)

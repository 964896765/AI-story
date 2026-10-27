"""Standalone worker; PostgreSQL row locks prevent duplicate claims."""
import time
from datetime import timedelta
from sqlalchemy import select
from .db import Session
from .models import Task, TaskEvent, Asset, now
from .storage import resolve_key
from .media import probe

def event(db, task, message):
    db.add(TaskEvent(task_id=task.id, attempt=task.attempt, message=message))

def run_once():
    with Session.begin() as db:
        expired = db.scalars(select(Task).where(Task.status == 'running', Task.lease_until < now()).with_for_update(skip_locked=True)).all()
        for task in expired:
            task.status, task.error, task.lease_until = 'failed', 'Worker lease expired; safe to retry probe', None
            event(db, task, task.error)
        task = db.scalar(select(Task).where(Task.status == 'queued').order_by(Task.created_at).with_for_update(skip_locked=True).limit(1))
        if not task:
            return False
        task.status, task.attempt = 'running', task.attempt + 1
        task.lease_until = now() + timedelta(seconds=120)
        event(db, task, '开始读取媒体信息')
        task_id, attempt = task.id, task.attempt
        key = db.get(Asset, task.asset_id).storage_key
    try:
        output = probe(resolve_key(key))
        error = None
    except Exception as exc:
        output, error = {}, str(exc)[:4000]
    with Session.begin() as db:
        task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
        if task.status != 'running' or task.attempt != attempt:
            return True
        task.status, task.output, task.error, task.lease_until = ('failed' if error else 'succeeded'), output, error, None
        if not error:
            db.get(Asset, task.asset_id).media_info = output
        event(db, task, error or '媒体信息读取完成')
    return True

if __name__ == '__main__':
    while True:
        try:
            if not run_once():
                time.sleep(2)
        except KeyboardInterrupt:
            break
        except Exception as exc:
            print(f'Worker error: {exc}', flush=True)
            time.sleep(5)

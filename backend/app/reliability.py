import errno
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from .models import QueueControl, TaskAttempt, now

def queue_control(db):
    return db.scalar(select(QueueControl).where(QueueControl.id=='local').with_for_update())

def attempt_record(db,task):
    return db.scalar(select(TaskAttempt).where(TaskAttempt.task_id==task.id,TaskAttempt.number==task.attempt))

def classify_error(exc):
    if isinstance(exc,SQLAlchemyError):return 'DATABASE_UNAVAILABLE',True
    if isinstance(exc,TimeoutError):return 'TIMEOUT',True
    if isinstance(exc,ConnectionError):return 'HEARTBEAT_LOST',True
    if isinstance(exc,FileNotFoundError):return 'FILE_OR_TOOL_MISSING',False
    if isinstance(exc,OSError):
        if exc.errno==errno.ENOSPC or '磁盘' in str(exc):return 'DISK_FULL',False
        if exc.errno in (errno.EBUSY,errno.EAGAIN):return 'RESOURCE_BUSY',True
        return 'IO_ERROR',False
    if isinstance(exc,ValueError):return 'INVALID_INPUT_OR_OUTPUT',False
    return 'PROCESSING_FAILED',False

def retry_delay(attempt):
    return min(60,5*2**max(0,min(attempt-1,4)))

def schedule_retry(task):
    task.status,task.stage,task.progress='queued','retry_wait',0
    task.next_run_at=now()+timedelta(seconds=retry_delay(task.attempt))

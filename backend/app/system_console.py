"""Report observed local resources and production activity."""
import os
import platform
import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text

from .config import STORAGE
from .db import session
from .models import Asset, Project, Task, TaskAttempt, WorkerNode, now

router=APIRouter(prefix='/api/system',tags=['workbench-operations'])


@router.get('/metrics')
def metrics(db=Depends(session)):
    disk_root=next((item for item in (STORAGE,*STORAGE.parents) if item.is_dir()),None)
    usage=shutil.disk_usage(disk_root) if disk_root else None
    records=db.execute(select(Task.kind,Task.status,func.count()).group_by(Task.kind,Task.status)).all()
    asset_count,asset_bytes=db.execute(select(func.count(),func.coalesce(func.sum(Asset.size_bytes),0))).one()
    attempts,elapsed=db.execute(select(func.count(),func.coalesce(func.sum(TaskAttempt.elapsed_seconds),0))).one()
    workers=db.scalars(select(WorkerNode).order_by(WorkerNode.last_seen.desc()).limit(15)).all()
    observed=now()
    return {
        'observed_at':observed,'os':platform.system(),'logical_cpus':os.cpu_count(),
        'database_revision':db.scalar(text('SELECT version_num FROM alembic_version')),
        'projects':db.scalar(select(func.count()).select_from(Project)),
        'recorded_asset_count':asset_count,'recorded_asset_bytes':asset_bytes,
        'disk':{'total':usage.total,'used':usage.used,'free':usage.free} if usage else None,
        'observed_attempts':attempts,'observed_task_seconds':round(elapsed,3),
        'workers':[{'id':worker.id,'state':worker.state,
                    'online':worker.state!='offline' and (observed-worker.last_seen).total_seconds()<15,
                    'last_seen':worker.last_seen}
                   for worker in workers],
        'tasks':[{'kind':kind,'status':status,'count':count} for kind,status,count in records],
    }

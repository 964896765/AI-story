import shutil
from pathlib import Path
from uuid import uuid4
from typing import Annotated, Literal
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, text, func
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import Session as DB
from .config import ORIGIN
from .db import session
from .models import Project, Asset, Task, TaskEvent, CostEntry
from .storage import save_upload, resolve_key
from .render import RenderOptions, validate_srt
from .models import now

app = FastAPI(title='AI 漫剧工厂', version='0.2.0')
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', 'testserver'])
app.add_middleware(CORSMiddleware, allow_origins=[ORIGIN], allow_methods=['GET', 'POST'], allow_headers=['Content-Type'])
DBDep = Annotated[DB, Depends(session)]

@app.middleware('http')
async def local_only(request: Request, call_next):
    if request.client and request.client.host not in ('127.0.0.1', '::1', 'testclient'):
        return JSONResponse(status_code=403, content={'detail': '仅允许本机访问'})
    if request.method != 'GET' and request.headers.get('origin') not in (None, ORIGIN):
        return JSONResponse(status_code=403, content={'detail': '不允许的请求来源'})
    return await call_next(request)

@app.exception_handler(SQLAlchemyError)
async def database_error(request, exc):
    return JSONResponse(status_code=503, content={'detail': '数据库不可用或结构未迁移，请检查 PostgreSQL 和 Alembic'})

class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=200, pattern=r'.*\S.*')
    description: str = Field(default='', max_length=20000)
    budget_cents: int = Field(default=0, ge=0, le=10**12)

class TaskInput(BaseModel):
    asset_id: str
    idempotency_key: str = Field(min_length=1, max_length=100)
    kind: Literal['probe','render'] = 'probe'
    parameters: RenderOptions | None = None

def require(db, model, key):
    row = db.get(model, key)
    if not row:
        raise HTTPException(404, '记录不存在')
    return row

@app.get('/api/health')
def health(db: DBDep):
    checks = {'database': False, 'schema': False, 'ffmpeg': bool(shutil.which('ffmpeg')), 'ffprobe': bool(shutil.which('ffprobe'))}
    try:
        db.execute(text('SELECT 1'))
        checks['database'] = True
        checks['schema'] = db.execute(text('SELECT version_num FROM alembic_version')).scalar() == '0002'
    except SQLAlchemyError:
        db.rollback()
    return JSONResponse(status_code=200 if all(checks.values()) else 503, content={'ready': all(checks.values()), 'checks': checks, 'ai_enabled': False})

@app.get('/api/projects')
def projects(db: DBDep):
    return db.scalars(select(Project).order_by(Project.created_at.desc())).all()

@app.post('/api/projects', status_code=201)
def create_project(body: ProjectInput, db: DBDep):
    row = Project(**body.model_dump())
    db.add(row)
    db.commit()
    return row

@app.get('/api/projects/{project_id}/assets')
def assets(project_id: str, db: DBDep):
    require(db, Project, project_id)
    return db.scalars(select(Asset).where(Asset.project_id == project_id).order_by(Asset.created_at.desc())).all()

@app.post('/api/projects/{project_id}/assets', status_code=201)
async def import_asset(project_id: str, db: DBDep, file: UploadFile = File(), authorization: str = Form(min_length=1, max_length=10000)):
    require(db, Project, project_id)
    if not authorization.strip():
        raise HTTPException(422, '必须记录素材授权来源')
    asset_id = str(uuid4())
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.wav', '.mp3', '.srt'}:
        raise HTTPException(422, '不支持的媒体扩展名')
    key = f'originals/{asset_id}{suffix}'
    saved = False
    try:
        digest, size = await save_upload(file, key, 2*1024**2 if suffix=='.srt' else None)
        saved = True
        if suffix == '.srt':
            validate_srt(resolve_key(key))
        row = Asset(id=asset_id, project_id=project_id, name=(file.filename or 'media').replace('\\', '/').split('/')[-1][:255], storage_key=key, sha256=digest, size_bytes=size, authorization=authorization)
        db.add(row)
        db.commit()
        return row
    except Exception as exc:
        db.rollback()
        if saved:
            resolve_key(key).unlink(missing_ok=True)
        if isinstance(exc, ValueError):
            raise HTTPException(422, str(exc)) from exc
        raise
    finally:
        await file.close()

@app.get('/api/assets/{asset_id}/media')
def media(asset_id: str, db: DBDep):
    row = require(db, Asset, asset_id)
    path = resolve_key(row.storage_key)
    if not path.is_file():
        raise HTTPException(404, '素材文件缺失')
    return FileResponse(path)

@app.get('/api/projects/{project_id}/tasks')
def tasks(project_id: str, db: DBDep):
    require(db, Project, project_id)
    return db.scalars(select(Task).where(Task.project_id == project_id).order_by(Task.created_at.desc())).all()

@app.post('/api/projects/{project_id}/tasks', status_code=201)
def create_task(project_id: str, body: TaskInput, db: DBDep):
    asset = require(db, Asset, body.asset_id)
    if asset.project_id != project_id:
        raise HTTPException(422, '素材不属于此项目')
    if body.kind=='probe' and body.parameters is not None:
        raise HTTPException(422, '解析任务不接受剪辑参数')
    parameters = (body.parameters or RenderOptions()).model_dump() if body.kind=='render' else {}
    inputs = {'video':{'id':asset.id,'storage_key':asset.storage_key,'sha256':asset.sha256}}
    if body.kind=='render':
        if Path(asset.storage_key).suffix not in {'.mp4','.mov','.mkv','.webm','.avi'}:
            raise HTTPException(422, '剪辑输入必须为视频素材')
        for role, key in [('audio','audio_asset_id'),('subtitle','subtitle_asset_id')]:
            if parameters[key]:
                row = require(db,Asset,parameters[key])
                if row.project_id != project_id:
                    raise HTTPException(422, '关联素材不属于此项目')
                if (role=='subtitle') != (Path(row.storage_key).suffix=='.srt'):
                    raise HTTPException(422, '字幕必须为 SRT，音轨必须为媒体文件')
                inputs[role] = {'id':row.id,'storage_key':row.storage_key,'sha256':row.sha256}
    def existing():
        return db.scalar(select(Task).where(Task.project_id == project_id, Task.idempotency_key == body.idempotency_key))
    previous = existing()
    if previous:
        if previous.asset_id != body.asset_id or previous.kind != body.kind or previous.parameters != parameters:
            raise HTTPException(409, '幂等键已用于其他输入')
        return previous
    row = Task(project_id=project_id, asset_id=body.asset_id, idempotency_key=body.idempotency_key,kind=body.kind,parameters=parameters,input_snapshot=inputs)
    db.add(row)
    try:
        db.flush()
        db.add(TaskEvent(task_id=row.id, attempt=0, message='任务已入队，等待 Worker'))
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = existing()
        if not previous or previous.asset_id != body.asset_id or previous.kind != body.kind or previous.parameters != parameters:
            raise HTTPException(409, '幂等键冲突')
        return previous
    return row

@app.post('/api/tasks/{task_id}/retry')
def retry(task_id: str, db: DBDep):
    task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if not task:
        raise HTTPException(404, '任务不存在')
    if task.status not in ('failed','cancelled'):
        raise HTTPException(409, '仅失败或已取消任务可重试')
    task.status, task.error, task.lease_until = 'queued', None, None
    task.cancel_requested, task.progress, task.stage = False, 0, 'queued'
    task.worker_token, task.output, task.finished_at = None, {}, None
    task.started_at, task.elapsed_seconds = None, 0
    db.add(TaskEvent(task_id=task.id, attempt=task.attempt, message='用户请求重试'))
    db.commit()
    return task

@app.post('/api/tasks/{task_id}/cancel')
def cancel(task_id: str, db: DBDep):
    task = db.scalar(select(Task).where(Task.id==task_id).with_for_update())
    if not task:
        raise HTTPException(404,'任务不存在')
    if task.status == 'cancelled':
        return task
    if task.status not in ('queued','running'):
        raise HTTPException(409,'任务已结束')
    task.cancel_requested = True
    if task.status == 'queued':
        task.status, task.stage, task.finished_at = 'cancelled','cancelled',now()
    db.add(TaskEvent(task_id=task.id,attempt=task.attempt,message='用户请求取消；已发布成片的并发完成结果优先'))
    db.commit()
    return task

@app.get('/api/tasks/{task_id}/output')
def task_output(task_id: str, db: DBDep, download: bool = False):
    task = require(db,Task,task_id)
    if task.status != 'succeeded' or task.kind != 'render':
        raise HTTPException(409,'任务没有已验证成片')
    path = resolve_key(task.output['storage_key'])
    if not path.is_file():
        raise HTTPException(404,'成片文件缺失')
    return FileResponse(path,filename=f'{task.id}{path.suffix}' if download else None,media_type='video/mp4' if path.suffix=='.mp4' else 'video/x-matroska')

@app.get('/api/tasks/{task_id}/events')
def events(task_id: str, db: DBDep):
    require(db, Task, task_id)
    return db.scalars(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id)).all()

@app.get('/api/projects/{project_id}/costs')
def costs(project_id: str, db: DBDep):
    project = require(db, Project, project_id)
    amount = db.scalar(select(func.coalesce(func.sum(CostEntry.amount_cents), 0)).where(CostEntry.project_id == project_id))
    return {'recorded_cents': amount, 'currency': 'CNY', 'budget_cents': project.budget_cents, 'note': '仅统计已入账 API 费用；当前未接入付费模型，不含电费和硬件成本'}

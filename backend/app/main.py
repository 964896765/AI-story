import shutil
from pathlib import Path
from uuid import uuid4
from typing import Annotated, Literal
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, text, func
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy.orm import Session as DB
from .config import ORIGIN
from .db import session
from .models import Project, Asset, Task, TaskEvent, CostEntry, Batch, QueueControl, TaskAttempt, WorkerNode,StoryVersion,StoryEntity
from .storage import save_upload, resolve_key
from .render import RenderOptions, validate_srt
from .models import now
from .reliability import queue_control
from datetime import timedelta
from .asset_validation import validate_extra_asset,IMAGE_SUFFIXES
from .creative import router as creative_router
from .text_routes import router as text_router
from .analysis_routes import router as analysis_router
from .analysis_review import router as analysis_review_router
from .series import router as series_router
from .generation import router as generation_router
from .voice import router as voice_router
from .timeline import router as timeline_router
from .production import router as production_router
from .library import router as library_router
from .delivery import router as delivery_router
from fastapi.exceptions import RequestValidationError

app = FastAPI(title='AI 漫剧工厂', version='0.12.0')
app.include_router(creative_router)
app.include_router(text_router)
app.include_router(analysis_router)
app.include_router(analysis_review_router)
app.include_router(series_router)
app.include_router(generation_router)
app.include_router(voice_router)
app.include_router(timeline_router)
app.include_router(production_router)
app.include_router(library_router)
app.include_router(delivery_router)
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

@app.exception_handler(RequestValidationError)
async def validation_error(request,exc):
    # Never echo rejected provider input (including accidentally pasted secrets).
    return JSONResponse(status_code=422,content={'detail':[{'loc':e['loc'],'msg':e['msg'],'type':e['type']} for e in exc.errors()]})

class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=200, pattern=r'.*\S.*')
    description: str = Field(default='', max_length=20000)
    budget_cents: int = Field(default=0, ge=0, le=10**12)

class TaskInput(BaseModel):
    asset_id: str
    idempotency_key: str = Field(min_length=1, max_length=100)
    kind: Literal['probe','render'] = 'probe'
    parameters: RenderOptions | None = None
    story_version_id: str | None = None

class BatchInput(BaseModel):
    asset_ids: list[str] = Field(min_length=1,max_length=100)
    idempotency_key: str = Field(min_length=1,max_length=100)
    parameters: RenderOptions = Field(default_factory=RenderOptions)
    story_version_id: str | None = None

    @model_validator(mode='after')
    def unique_assets(self):
        if len(set(self.asset_ids))!=len(self.asset_ids):
            raise ValueError('批次中不允许重复素材ID')
        return self

class QueueInput(BaseModel):
    paused: bool

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
        checks['schema'] = db.execute(text('SELECT version_num FROM alembic_version')).scalar() == '0011'
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
    if suffix not in {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.wav', '.mp3', '.srt','.txt',*IMAGE_SUFFIXES}:
        raise HTTPException(422, '不支持的媒体扩展名')
    key = f'originals/{asset_id}{suffix}'
    saved = False
    try:
        maximum=2*1024**2 if suffix in ('.srt','.txt') else 20*1024**2 if suffix in IMAGE_SUFFIXES else None
        digest, size = await save_upload(file, key,maximum)
        saved = True
        if suffix == '.srt':
            validate_srt(resolve_key(key))
        validate_extra_asset(resolve_key(key),suffix)
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
    return FileResponse(path,headers={'X-Content-Type-Options':'nosniff'})

@app.get('/api/projects/{project_id}/tasks')
def tasks(project_id: str, db: DBDep):
    require(db, Project, project_id)
    return db.scalars(select(Task).where(Task.project_id == project_id).order_by(Task.created_at.desc())).all()

def prepare_task(project_id: str, body: TaskInput, db):
    asset = require(db, Asset, body.asset_id)
    if asset.project_id != project_id:
        raise HTTPException(422, '素材不属于此项目')
    if body.story_version_id:
        version=require(db,StoryVersion,body.story_version_id)
        entity=require(db,StoryEntity,version.entity_id)
        if entity.project_id!=project_id or entity.kind not in ('script','episode','storyboard'):
            raise HTTPException(422,'生产引用必须为同项目的剧本、分集或分镜版本')
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
    return parameters,inputs

@app.post('/api/projects/{project_id}/tasks', status_code=201)
def create_task(project_id: str, body: TaskInput, db: DBDep):
    parameters,inputs=prepare_task(project_id,body,db)
    def existing():
        return db.scalar(select(Task).where(Task.project_id == project_id, Task.idempotency_key == body.idempotency_key))
    previous = existing()
    if previous:
        if previous.asset_id != body.asset_id or previous.kind != body.kind or previous.parameters != parameters or previous.story_version_id!=body.story_version_id:
            raise HTTPException(409, '幂等键已用于其他输入')
        return previous
    row = Task(project_id=project_id, asset_id=body.asset_id, idempotency_key=body.idempotency_key,kind=body.kind,parameters=parameters,input_snapshot=inputs,story_version_id=body.story_version_id)
    db.add(row)
    try:
        db.flush()
        db.add(TaskEvent(task_id=row.id, attempt=0, message='任务已入队，等待 Worker'))
        db.commit()
    except IntegrityError:
        db.rollback()
        previous = existing()
        if not previous or previous.asset_id != body.asset_id or previous.kind != body.kind or previous.parameters != parameters or previous.story_version_id!=body.story_version_id:
            raise HTTPException(409, '幂等键冲突')
        return previous
    return row

@app.post('/api/tasks/{task_id}/retry')
def retry(task_id: str, db: DBDep):
    task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if not task:
        raise HTTPException(404, '任务不存在')
    if task.kind=='adapt':raise HTTPException(409,'模型任务不得通过通用重试重发；请在模型调用记录中核对费用并显式创建新调用')
    if task.status not in ('failed','cancelled'):
        raise HTTPException(409, '仅失败或已取消任务可重试')
    task.status, task.error, task.lease_until = 'queued', None, None
    task.cancel_requested, task.progress, task.stage = False, 0, 'queued'
    task.worker_token, task.output, task.finished_at = None, {}, None
    task.started_at, task.elapsed_seconds = None, 0
    task.next_run_at,task.error_code=now(),None
    db.add(TaskEvent(task_id=task.id, attempt=task.attempt, message='用户请求重试'))
    db.commit()
    return task

@app.post('/api/tasks/{task_id}/cancel')
def cancel(task_id: str, db: DBDep):
    task = db.scalar(select(Task).where(Task.id==task_id).with_for_update())
    if not task:
        raise HTTPException(404,'任务不存在')
    if task.kind=='adapt':
        from .text_service import cancel_locked
        result=cancel_locked(db,task);db.commit();return task
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
    if task.status != 'succeeded' or task.kind not in ('render','timeline_render'):
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
    totals=dict(db.execute(select(CostEntry.currency,func.sum(CostEntry.amount_cents)).where(CostEntry.project_id==project_id).group_by(CostEntry.currency)).all())
    return {'recorded_cents':totals.get('CNY',0),'recorded_by_currency':totals,'currency':'CNY','budget_cents':project.budget_cents,'note':'金额为已入账人民币 API 费用；其他币种单列且不换算。当前未接入付费模型，不含电费和硬件成本'}

@app.post('/api/projects/{project_id}/batches',status_code=201)
def create_batch(project_id: str, body: BatchInput, db: DBDep):
    require(db,Project,project_id)
    request=body.model_dump(exclude={'idempotency_key'})
    if not body.story_version_id:request.pop('story_version_id',None)  # Keep P3 batch retries compatible.
    def existing():
        row=db.scalar(select(Batch).where(Batch.project_id==project_id,Batch.idempotency_key==body.idempotency_key))
        if row and row.request!=request:raise HTTPException(409,'批次幂等键已用于不同输入或参数')
        return row
    def result(row):
        return {'batch':row,'tasks':db.scalars(select(Task).where(Task.batch_id==row.id).order_by(Task.created_at,Task.id)).all()}
    previous=existing()
    if previous:return result(previous)
    prepared=[]
    for asset_id in body.asset_ids:
        options=TaskInput(asset_id=asset_id,idempotency_key='internal',kind='render',parameters=body.parameters,story_version_id=body.story_version_id)
        parameters,inputs=prepare_task(project_id,options,db)
        prepared.append((asset_id,parameters,inputs))
    batch=Batch(project_id=project_id,idempotency_key=body.idempotency_key,request=request)
    try:
        db.add(batch);db.flush()
        for index,(asset_id,parameters,inputs) in enumerate(prepared):
            row=Task(project_id=project_id,asset_id=asset_id,batch_id=batch.id,kind='render',idempotency_key=f'batch:{batch.id}:{index}',parameters=parameters,input_snapshot=inputs,story_version_id=body.story_version_id)
            db.add(row);db.flush()
            db.add(TaskEvent(task_id=row.id,attempt=0,message='原子批次已入队：'+batch.id))
        db.commit()
    except IntegrityError:
        db.rollback()
        previous=existing()
        if previous:return result(previous)
        raise HTTPException(409,'批次创建冲突，未提交任何新任务')
    return result(batch)

@app.get('/api/queue')
def queue_state(db: DBDep):
    row=db.get(QueueControl,'local')
    workers=db.scalars(select(WorkerNode).order_by(WorkerNode.last_seen.desc()).limit(20)).all()
    return {'paused':row.paused,'concurrency':1,'workers':[{'id':w.id,'pid':w.pid,'hostname':w.hostname,'state':w.state,'task_id':w.task_id,'last_seen':w.last_seen,'online':w.state!='offline' and w.last_seen>now()-timedelta(seconds=15),'error':w.error} for w in workers]}

@app.post('/api/queue')
def set_queue(body: QueueInput, db: DBDep):
    row=queue_control(db)
    row.paused=body.paused
    db.commit()
    return {'paused':row.paused,'note':'暂停仅停止领取新任务，正在运行的任务继续；中断恢复与取消仍可处理'}

@app.get('/api/tasks/{task_id}/attempts')
def task_attempts(task_id: str, db: DBDep):
    require(db,Task,task_id)
    return db.scalars(select(TaskAttempt).where(TaskAttempt.task_id==task_id).order_by(TaskAttempt.number)).all()

@app.get('/api/tasks/{task_id}/attempts/{number}/logs')
def attempt_logs(task_id: str,number: int,db: DBDep):
    require(db,Task,task_id)
    record=db.scalar(select(TaskAttempt).where(TaskAttempt.task_id==task_id,TaskAttempt.number==number))
    if not record:raise HTTPException(404,'尝试记录不存在（P2历史不会伪造补录）')
    path=resolve_key(f'tmp/{task_id}/{record.number}/ffmpeg.log')
    if not path.is_file():return {'available':False,'text':'此尝试没有 FFmpeg 日志（可能是解析任务或编码前失败）','truncated':False}
    with path.open('rb') as file:
        size=path.stat().st_size
        file.seek(max(0,size-65536))
        content=file.read(65536).decode('utf-8',errors='replace')
    return {'available':True,'text':content,'truncated':size>65536}

@app.get('/api/projects/{project_id}/production-summary')
def production_summary(project_id: str,db: DBDep):
    project=require(db,Project,project_id)
    counts=dict(db.execute(select(Task.status,func.count()).where(Task.project_id==project_id).group_by(Task.status)).all())
    attempts=db.execute(select(TaskAttempt.task_id,func.count(),func.sum(TaskAttempt.elapsed_seconds)).join(Task,Task.id==TaskAttempt.task_id).where(Task.project_id==project_id).group_by(TaskAttempt.task_id)).all()
    charges=dict(db.execute(select(CostEntry.task_id,func.sum(CostEntry.amount_cents)).where(CostEntry.project_id==project_id,CostEntry.currency=='CNY').group_by(CostEntry.task_id)).all())
    totals=dict(db.execute(select(CostEntry.currency,func.sum(CostEntry.amount_cents)).where(CostEntry.project_id==project_id).group_by(CostEntry.currency)).all())
    return {'counts':counts,'recorded_cents':totals.get('CNY',0),'recorded_by_currency':totals,'currency':'CNY','budget_cents':project.budget_cents,'attempts':sum(a[1] for a in attempts),'observed_processing_seconds':sum(a[2] for a in attempts),'by_task':[{'task_id':tid,'attempts':count,'observed_processing_seconds':elapsed,'recorded_cents':charges.get(tid,0)} for tid,count,elapsed in attempts],'note':'耗时为P3尝试中已观测处理时间；中断可能少计，P2历史不补造。费用仅为实际入账人民币API费用，其他币种单列不混加；不含硬件与电费，当前没有付费模型调用。'}

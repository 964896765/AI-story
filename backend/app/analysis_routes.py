from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import select

from . import storage
from .analysis_schemas import AnalysisRequest, OCR_OPERATIONS
from .creative import require
from .db import session
from .models import Asset, MediaAnalysis, Project, Task, TaskEvent, now
from .analysis_service import analysis_public
from .perception_ocr import recognizer
from .subtitle_revision import SubtitleRevisionInput, revision_list, save_revision

router = APIRouter(prefix='/api/analysis', tags=['media-analysis'])
INPUT_FORMATS = {'.mp4', '.mov', '.mkv', '.webm', '.avi', '.wav', '.mp3'}


@router.post('/projects/{project_id}/tasks', status_code=201)
def submit(project_id: str, body: AnalysisRequest, db=Depends(session)):
    if not db.scalar(select(Project).where(Project.id == project_id).with_for_update()):
        raise HTTPException(404, '项目不存在')
    asset = require(db, Asset, body.asset_id)
    if asset.project_id != project_id or Path(asset.storage_key).suffix.lower() not in INPUT_FORMATS:
        raise HTTPException(422, '请选择同项目的音视频素材')
    parameters = [step.signature_parameters() for step in body.steps]
    if any(step in parameters[:i] for i, step in enumerate(parameters)):
        raise HTTPException(422, '同次提交包含重复解析步骤')
    prefix = 'media-analysis:' + body.idempotency_key + ':'
    # The ordered batch is compared in full, including a deliberately shorter replay.
    keys = [prefix + str(i) for i in range(12)]
    prior = {row.idempotency_key: row for row in db.scalars(select(Task).where(
        Task.project_id == project_id, Task.idempotency_key.in_(keys)))}
    if prior:
        existing = [prior.get(key) for key in keys[:len(parameters)]]
        if len(prior) != len(parameters) or any(row is None or row.kind != 'analyze' or
                row.asset_id != asset.id or row.parameters != step for row, step in zip(existing, parameters)):
            raise HTTPException(409, '此请求键已用于其他素材或解析参数')
        return existing
    recognizers = {}
    for index, step in enumerate(body.steps):
        if step.operation in OCR_OPERATIONS:
            try:
                recognizers[index] = recognizer(step.ocr_language)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
    tasks = []
    submitted_at = now()
    for index, (key, step) in enumerate(zip(keys, parameters)):
        snapshot = {'video': {'id': asset.id, 'storage_key': asset.storage_key, 'sha256': asset.sha256}}
        if index in recognizers:
            snapshot['ocr'] = recognizers[index]
        task = Task(project_id=project_id, asset_id=asset.id, kind='analyze', parameters=step,
                    idempotency_key=key, created_at=submitted_at+timedelta(microseconds=index),
                    input_snapshot=snapshot)
        db.add(task)
        tasks.append(task)
    db.flush()
    for task in tasks:
        db.add(TaskEvent(task_id=task.id, attempt=0, message='本地媒体解析已排队：' + task.parameters['operation']))
    db.commit()
    return tasks


@router.get('/projects/{project_id}/assets/{asset_id}/tasks')
def list_tasks(project_id: str, asset_id: str, offset: int = Query(0, ge=0),
               limit: int = Query(100, ge=1, le=100), db=Depends(session)):
    asset = require(db, Asset, asset_id)
    if asset.project_id != project_id:
        raise HTTPException(404, '素材不属于该项目')
    return db.scalars(select(Task).where(Task.asset_id == asset_id, Task.kind == 'analyze',
        Task.project_id == project_id).order_by(Task.created_at.desc(), Task.id).offset(offset).limit(limit)).all()


@router.get('/tasks/{task_id}/result')
def result(task_id: str, db=Depends(session)):
    return analysis_public(require(db, MediaAnalysis, task_id))


@router.get('/projects/{project_id}/assets/{asset_id}/tasks/{task_id}')
def get_task(project_id: str, asset_id: str, task_id: str, db=Depends(session)):
    task = db.scalar(select(Task).where(Task.id == task_id, Task.kind == 'analyze',
                                        Task.project_id == project_id, Task.asset_id == asset_id))
    if task is None:
        raise HTTPException(404, '该素材下找不到此解析任务')
    return task


SUBTITLE_REVISIONS = '/projects/{project_id}/assets/{asset_id}/tasks/{task_id}/subtitle-tracks/{stream_index}/revisions'


@router.get(SUBTITLE_REVISIONS)
def subtitle_revisions(project_id: str, asset_id: str, task_id: str, stream_index: int, db=Depends(session)):
    task = get_task(project_id, asset_id, task_id, db)
    return revision_list(db, require(db, Asset, asset_id), task, stream_index)


@router.post(SUBTITLE_REVISIONS, status_code=201)
def review_subtitles(project_id: str, asset_id: str, task_id: str, stream_index: int,
                     body: SubtitleRevisionInput, db=Depends(session)):
    task = get_task(project_id, asset_id, task_id, db)
    db.scalar(select(Project.id).where(Project.id == project_id).with_for_update())
    return save_revision(db, require(db, Asset, asset_id), task, stream_index, body.edits)


@router.get('/tasks/{task_id}/artifacts/{number}')
def artifact(task_id: str, number: int, download: bool = False, db=Depends(session)):
    entries = require(db, MediaAnalysis, task_id).payload['artifacts']
    if not 0 <= number < len(entries):
        raise HTTPException(404, '解析产物不存在')
    entry = entries[number]
    path = storage.resolve_key(entry['storage_key'])
    if not path.is_file() or path.stat().st_size != entry['size_bytes']:
        raise HTTPException(404, '文件缺失或不完整，请重新执行该步骤')
    return FileResponse(path, media_type=entry['media_type'], filename=entry['name'] if download else None,
                        headers={'X-Content-Type-Options': 'nosniff'})


@router.get('/tasks/{task_id}/logs/{attempt}')
def logs(task_id: str, attempt: int, db=Depends(session)):
    task = require(db, Task, task_id)
    if task.kind != 'analyze' or not 1 <= attempt <= task.attempt:
        raise HTTPException(404, '解析尝试不存在')
    work = storage.resolve_key(f'tmp/{task.id}/{attempt}')
    files = sorted(work.glob('*.stderr'))
    result = []
    for path in files[-24:]:
        with path.open('rb') as handle:
            handle.seek(max(0, path.stat().st_size - 4096))
            result.append({'name': path.name, 'tail': handle.read().decode('utf-8', errors='replace')})
    return {'files': result}

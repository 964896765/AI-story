"""Build persistent per-episode render → QC graphs with scoped rework."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select

from . import storage
from .analysis_service import fingerprint
from .creative import require, version_ref
from .db import session
from .models import ProductionEpisode, ProductionRun, Project, QualityReview, Task, TaskEvent, now
from .render import file_hash
from .series import series_report
from .story_schemas import Strict
from .timeline import all_source_versions

router = APIRouter(prefix='/api/production',tags=['series-production'])
WORKFLOW = 'series-render-qc-v1'


class Ref(Strict):
    number: int=Field(ge=1,le=60)
    timeline_version_id: str=Field(min_length=1,max_length=36)


class Policy(Strict):
    require_audio: bool=False
    require_subtitles: bool=False
    black_ms: int=Field(default=500,ge=100,le=10000)
    freeze_ms: int=Field(default=750,ge=100,le=10000)
    silence_ms: int=Field(default=1000,ge=100,le=10000)
    silence_db: int=Field(default=-45,ge=-99,le=-10)


class RunRequest(Strict):
    plan_version_id: str=Field(min_length=1,max_length=36)
    previous_run_id: str | None=Field(default=None,min_length=1,max_length=36)
    timelines: list[Ref]=Field(min_length=1,max_length=60)
    policy: Policy=Field(default_factory=Policy)
    idempotency_key: str=Field(min_length=1,max_length=64)


class ReviewRequest(Strict):
    expected_sha256: str=Field(pattern=r'^[0-9a-f]{64}$')
    note: str=Field(min_length=1,max_length=4000,pattern=r'.*\S.*')
    idempotency_key: str=Field(min_length=1,max_length=64)


def episode_rows(db,run_id):
    return db.scalars(select(ProductionEpisode).where(ProductionEpisode.run_id==run_id)
                      .order_by(ProductionEpisode.number)).all()


def no_blockers(qc):
    return all(issue['severity']!='error' for issue in qc.output['issues'])


def render_intact(render):
    try:
        path = storage.resolve_key(render.output['storage_key'])
        return path.stat().st_size==render.output['size_bytes'] and file_hash(path)==render.output['sha256']
    except (OSError,KeyError,ValueError):
        return False


def can_reuse(db,row,version):
    if not row or row.timeline_version_id!=version.id:
        return False
    render,qc = db.get(Task,row.render_task_id),db.get(Task,row.qc_task_id)
    return (render.status=='succeeded' and qc.status=='succeeded'
            and qc.output.get('output_sha256')==render.output.get('sha256') and render_intact(render))


def public(db,run,*,details=True):
    rows = episode_rows(db,run.id)
    task_ids = {task_id for row in rows for task_id in (row.render_task_id,row.qc_task_id)}
    tasks = {task.id:task for task in db.scalars(select(Task).where(Task.id.in_(task_ids))).all()}
    qc_ids = {row.qc_task_id for row in rows if tasks[row.qc_task_id].status=='succeeded'}
    reviews = {}
    for review in db.scalars(select(QualityReview).where(QualityReview.qc_task_id.in_(qc_ids))
        .order_by(QualityReview.created_at.desc(),QualityReview.id)):
        reviews.setdefault(review.qc_task_id,review)
    episodes = []
    for row in rows:
        render,qc = tasks[row.render_task_id],tasks[row.qc_task_id]
        reviewed = reviews.get(qc.id)
        findings = qc.output.get('issues',[])
        pending = any(task.status in ('queued','running') for task in (render,qc))
        if pending:
            state = 'processing'
        elif render.status==qc.status=='cancelled':
            state = 'cancelled'
        elif render.status!='succeeded' or qc.status!='succeeded' or not no_blockers(qc):
            state = 'needs_rework'
        elif findings and not (reviewed and reviewed.reviewed_sha256==qc.output.get('output_sha256')):
            state = 'needs_review'
        else:
            state = 'passed'
        unit = {'number':row.number,'timeline_version_id':row.timeline_version_id,'reused':row.reused,'status':state,
                'render_task_id':render.id,'render_status':render.status,'render_error':render.error,
                'qc_task_id':qc.id,'qc_status':qc.status,'qc_stage':qc.stage,'qc_error':qc.error,'issue_count':len(findings)}
        if details:
            unit['qc'] = qc.output if qc.status=='succeeded' else None
            unit['review'] = {'id':reviewed.id,'note':reviewed.note,'file_sha256':reviewed.reviewed_sha256} if reviewed else None
        episodes.append(unit)
    statuses = {unit['status'] for unit in episodes}
    state = next((item for item in ('processing','needs_rework','needs_review','cancelled') if item in statuses),'passed')
    return {'id':run.id,'workflow':WORKFLOW,'plan_version_id':run.plan_version_id,
            'previous_run_id':run.previous_run_id,'status':state,'created_at':run.created_at,
            'episode_count':len(episodes),'episodes':episodes if details else None,
            'policy':run.policy,'passed':sum(unit['status']=='passed' for unit in episodes),
            'reused':sum(unit['reused'] for unit in episodes)}


def add_tasks(db,run,version,number):
    render = Task(project_id=run.project_id,kind='timeline_render',story_version_id=version.id,
        idempotency_key=f'production:{run.id}:{number}:render',parameters={'timeline':version.content},
        input_snapshot={'version_hash':version.content_hash,'assets':all_source_versions(db,run.project_id,version.content)})
    db.add(render)
    db.flush()
    qc = Task(project_id=run.project_id,kind='qc_review',story_version_id=version.id,
        dependency_task_id=render.id,idempotency_key=f'production:{run.id}:{number}:qc',
        parameters=run.policy,input_snapshot={'render_task_id':render.id})
    db.add(qc)
    db.flush()
    db.add_all([TaskEvent(task_id=render.id,attempt=0,message='整剧渲染步骤已排队'),
                TaskEvent(task_id=qc.id,attempt=0,message='技术质检等待固定渲染产物')])
    return render.id,qc.id


@router.post('/projects/{project_id}/runs',status_code=201)
def submit(project_id:str,body:RunRequest,db=Depends(session)):
    if not db.scalar(select(Project).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    request_hash = fingerprint(body.model_dump(exclude={'idempotency_key'}))
    prior = db.scalar(select(ProductionRun).where(ProductionRun.project_id==project_id,
                        ProductionRun.request_key==body.idempotency_key))
    if prior:
        if prior.request_hash!=request_hash:
            raise HTTPException(409,'请求键已用于其他生产批次')
        return public(db,prior)
    entity,plan = version_ref(db,project_id,body.plan_version_id,{'story_bible'})
    plan_report = series_report(db,entity,plan)
    if not plan_report['approved']:
        raise HTTPException(422,'请选已批准的整剧计划版本')
    policy = body.policy.model_dump()
    old_rows = {}
    if body.previous_run_id:
        previous = require(db,ProductionRun,body.previous_run_id)
        if previous.project_id!=project_id or previous.plan_version_id!=plan.id:
            raise HTTPException(422,'返工批次须属于同项目及固定计划')
        if public(db,previous,details=False)['status']=='processing':
            raise HTTPException(409,'上一批次仍在处理')
        old_rows = {row.number:row for row in episode_rows(db,previous.id)}
    items = {item.number:item.timeline_version_id for item in body.timelines}
    if len(items)!=len(body.timelines):
        raise HTTPException(422,'同一分集不能提交多个时间轴版本')
    versions = {number:row.timeline_version_id for number,row in old_rows.items()} | items
    if set(versions)!={entry['number'] for entry in plan_report['episodes']}:
        raise HTTPException(422,'整剧生产必须覆盖批准计划中的全部分集')
    run = ProductionRun(project_id=project_id,plan_version_id=plan.id,
                        previous_run_id=body.previous_run_id,request_key=body.idempotency_key,
                        request_hash=request_hash,policy=policy)
    db.add(run)
    db.flush()
    for entry in plan_report['episodes']:
        number = entry['number']
        _,timeline = version_ref(db,project_id,versions[number],{'timeline'})
        if timeline.content['source_version_id']!=plan.id:
            raise HTTPException(422,f'第 {number} 集时间轴未固定到整剧生产计划')
        assembly = timeline.provenance.get('assembly_request')
        if assembly and assembly['episode']!=number:
            raise HTTPException(422,f'第 {number} 集和自动装配记录不匹配')
        old = old_rows.get(number)
        reuse = bool(body.previous_run_id and previous.policy==policy and can_reuse(db,old,timeline))
        render_id,qc_id = (old.render_task_id,old.qc_task_id) if reuse else add_tasks(db,run,timeline,number)
        db.add(ProductionEpisode(run_id=run.id,number=number,timeline_version_id=timeline.id,
                                 render_task_id=render_id,qc_task_id=qc_id,reused=reuse))
    db.commit()
    return public(db,run)


@router.get('/projects/{project_id}/runs')
def runs(project_id:str,db=Depends(session)):
    require(db,Project,project_id)
    rows = db.scalars(select(ProductionRun).where(ProductionRun.project_id==project_id)
                      .order_by(ProductionRun.created_at.desc(),ProductionRun.id).limit(20)).all()
    return [public(db,run,details=False) for run in rows]


@router.get('/runs/{run_id}')
def run(run_id:str,db=Depends(session)):
    return public(db,require(db,ProductionRun,run_id))


@router.post('/runs/{run_id}/cancel')
def cancel(run_id:str,db=Depends(session)):
    run = db.scalar(select(ProductionRun).where(ProductionRun.id==run_id).with_for_update())
    if not run:
        raise HTTPException(404,'批次不存在')
    ids = {task_id for row in episode_rows(db,run.id) if not row.reused for task_id in (row.render_task_id,row.qc_task_id)}
    for task in db.scalars(select(Task).where(Task.id.in_(ids)).order_by(Task.id).with_for_update()):
        if task.status in ('queued','running'):
            task.cancel_requested=True
            if task.status=='queued':
                task.status=task.stage='cancelled'
                task.finished_at=now()
            db.add(TaskEvent(task_id=task.id,attempt=task.attempt,message='用户请求停止此生产批次'))
    db.commit()
    return public(db,run)


@router.post('/runs/{run_id}/episodes/{number}/review',status_code=201)
def review(run_id:str,number:int,body:ReviewRequest,db=Depends(session)):
    run = require(db,ProductionRun,run_id)
    episode = db.get(ProductionEpisode,(run.id,number))
    if not episode:
        raise HTTPException(404,'批次中不存在该集')
    qc = db.scalar(select(Task).where(Task.id==episode.qc_task_id).with_for_update())
    render = require(db,Task,episode.render_task_id)
    if qc.status!='succeeded' or not no_blockers(qc):
        raise HTTPException(409,'技术硬门槛未通过，必须返工')
    if body.expected_sha256!=qc.output['output_sha256'] or not render_intact(render):
        raise HTTPException(409,'成片与固定审核哈希不一致')
    prior = db.scalar(select(QualityReview).where(QualityReview.qc_task_id==qc.id,QualityReview.request_key==body.idempotency_key))
    if prior:
        if prior.note!=body.note:
            raise HTTPException(409,'请求键已用于其他审核意见')
        return public(db,run)
    db.add(QualityReview(qc_task_id=qc.id,request_key=body.idempotency_key,
                         reviewed_sha256=body.expected_sha256,note=body.note))
    db.commit()
    return public(db,run)

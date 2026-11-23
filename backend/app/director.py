"""Approve and dispatch fixed local work through the existing production queue."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, StringConstraints
from sqlalchemy import select

from . import delivery, director_guidance, production, text_service, timeline
from .analysis_service import fingerprint
from .creative import require, version_ref
from .db import session
from .library import Region, Slug
from .guardian import require_active_plan
from .models import DirectorPlan, ModelCall, ProductionRun, Project, StoryEntity, StoryVersion, Task, now, uid
from .series import series_report
from .story_schemas import Strict, Timeline
from .production_specs import approval_spec
from .text_schemas import DirectorAdviceInput, DirectorAdviceReview, ReconcileInput, RetryInput

router = APIRouter(prefix='/api/director/projects/{project_id}', tags=['director'])


class Render(Strict):
    action: Literal['render']
    version_id: str = Field(min_length=1, max_length=36)


class Package(Strict):
    action: Literal['release']
    run_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=180, pattern=r'.*\S.*')
    platform: Slug
    region: Region


class Batch(production.RunOptions):
    action: Literal['batch']


class Draft(Strict):
    instruction: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    idempotency_key: str = Field(min_length=1, max_length=64)
    operation: Render | Package | Batch = Field(discriminator='action')


def lock_project(db, project_id):
    if not db.scalar(select(Project.id).where(Project.id == project_id).with_for_update()):
        raise HTTPException(404, '项目不存在')


def fixed_input(db, project_id, action, params):
    if action == 'render':
        _, version = version_ref(db, project_id, params['version_id'], {'timeline'})
        snapshot = timeline.render_snapshot(db, project_id, version, Timeline.model_validate(version.content))
        return version, snapshot
    return delivery.package_snapshot(db, project_id, params)


def prepare_batch(db, project_id, params):
    body = production.RunOptions.model_validate(params)
    policy = body.policy.model_dump(exclude_none=True)
    version, episodes = production.prepare_episodes(db, project_id, body, policy)
    snapshot = {
        'plan_hash': version.content_hash, 'policy': policy, 'previous_run_id': body.previous_run_id,
        'episodes': [{
            'number': item.number, 'version_id': item.version.id, 'input': item.snapshot,
            'render_id': item.render.id if item.render else None,
            'render_hash': item.render.output['sha256'] if item.render else None,
            'qc_id': item.qc.id if item.qc else None,
            **({'dialogue':item.dialogue} if item.dialogue else {}),
        } for item in episodes],
    }
    return body, policy, episodes, fingerprint(snapshot)


def public(plan, task=None, run=None):
    return {
        'id': plan.id, 'instruction': plan.instruction, 'action': plan.action, 'parameters': plan.parameters,
        'input_hash': plan.input_hash, 'created_at': plan.created_at, 'approved_at': plan.approved_at,
        'external_cost_cents': 0, 'run_id': plan.run_id, 'run': run, 'preview': plan.preview,
        'production_spec_version_id':plan.production_spec_version_id,
        'task': {
            'id': task.id, 'status': task.status, 'stage': task.stage, 'progress': task.progress,
            'elapsed_seconds': task.elapsed_seconds, 'error': task.error,
        } if task else None,
    }


def details(db, plan):
    task = db.get(Task, plan.task_id) if plan.task_id else None
    run = db.get(ProductionRun, plan.run_id) if plan.run_id else None
    return public(plan, task, production.public(db, run, details=False, include_episodes=True) if run else None)


@router.get('/batch-options')
def approved_series(project_id: str, db=Depends(session)):
    require(db, Project, project_id)
    rows = db.execute(select(StoryVersion.id, StoryVersion.title, StoryVersion.number)
        .join(StoryEntity, StoryVersion.entity_id == StoryEntity.id)
        .where(StoryEntity.project_id == project_id, StoryEntity.kind == 'story_bible',
               StoryVersion.provenance['series_approved'].as_boolean().is_(True))
        .distinct(StoryVersion.entity_id).order_by(StoryVersion.entity_id, StoryVersion.number.desc()))
    return [{'version_id': row.id, 'title': row.title, 'version': row.number} for row in rows]


@router.get('/batch-options/{version_id}')
def batch_options(project_id: str, version_id: str, db=Depends(session)):
    entity, version = version_ref(db, project_id, version_id, {'story_bible'})
    if not version.provenance.get('series_approved'):
        raise HTTPException(422, '请选已批准的整剧计划版本')
    require_active_plan(db, version)
    report = series_report(db, entity, version)
    rows = db.execute(select(StoryVersion.id, StoryVersion.title, StoryVersion.number, StoryVersion.provenance)
        .join(StoryEntity, StoryVersion.entity_id == StoryEntity.id)
        .where(StoryEntity.project_id == project_id, StoryEntity.kind == 'timeline',
               StoryVersion.content['source_version_id'].as_string() == version.id)
        .order_by(StoryVersion.created_at.desc(), StoryVersion.id))
    return {'episodes': [{'number': item['number'], 'title': item['title']} for item in report['episodes']],
            'timelines': [{'version_id': row.id, 'title': row.title, 'version': row.number,
                           'episode': (row.provenance.get('assembly_request') or {}).get('episode')} for row in rows]}


def scoped_plan(db, project_id, plan_id):
    plan = db.get(DirectorPlan, plan_id)
    if not plan or plan.project_id != project_id:
        raise HTTPException(404, '执行计划不存在')
    return plan


def scoped_advice(db, project_id, call_id):
    row = db.get(ModelCall, call_id)
    if not row or row.project_id!=project_id or row.prompt_version!=director_guidance.PROMPT_VERSION:
        raise HTTPException(404,'导演建议记录不存在')
    return row


@router.get('/advice')
def advice_history(project_id: str, db=Depends(session)):
    require(db, Project, project_id)
    rows = db.scalars(select(ModelCall).where(ModelCall.project_id==project_id,
        ModelCall.prompt_version==director_guidance.PROMPT_VERSION)
        .order_by(ModelCall.created_at.desc(),ModelCall.id).limit(30))
    return [text_service.call_public(row) for row in rows]


@router.get('/advice/{call_id}')
def get_advice(project_id: str,call_id: str,db=Depends(session)):
    return text_service.call_public(scoped_advice(db,project_id,call_id))


@router.post('/advice',status_code=201)
def request_advice(project_id: str,body: DirectorAdviceInput,db=Depends(session)):
    call = text_service.reserve_call(db,project_id,body)
    db.commit()
    return text_service.call_public(call)


@router.post('/advice/{call_id}/cancel')
def cancel_advice(project_id: str,call_id: str,db=Depends(session)):
    call = scoped_advice(db,project_id,call_id)
    task = db.scalar(select(Task).where(Task.id==call.task_id).with_for_update())
    call = text_service.cancel_locked(db,task)
    db.commit()
    return text_service.call_public(call)


@router.post('/advice/{call_id}/retry',status_code=201)
def retry_advice(project_id: str,call_id: str,body: RetryInput,db=Depends(session)):
    row = text_service.retry_call(db,scoped_advice(db,project_id,call_id),body)
    db.commit()
    return text_service.call_public(row)


@router.post('/advice/{call_id}/reconcile')
def reconcile_advice(project_id: str,call_id: str,body: ReconcileInput,db=Depends(session)):
    scoped_advice(db,project_id,call_id)
    row = text_service.reconcile(db,call_id,body)
    db.commit()
    return text_service.call_public(row)


@router.post('/advice/{call_id}/review')
def review_advice(project_id: str,call_id: str,body: DirectorAdviceReview,db=Depends(session)):
    lock_project(db,project_id)
    scoped_advice(db,project_id,call_id)
    task,_,call = text_service.locked_call(db,call_id)
    request = body.model_dump()
    if call.review:
        if call.review['request']!=request:
            raise HTTPException(409,'此建议已有审核记录')
        return text_service.call_public(call)
    if call.status!='awaiting_review' or call.budget_status!='settled' or call.draft_revision!=body.draft_revision:
        raise HTTPException(409,'建议状态或草稿版本已变化，请重新读取')
    plan_id = None
    if body.action=='accept':
        plan_id = call.request['plan_ids'][call.draft['choice']-1]
        plan = scoped_plan(db,project_id,plan_id)
        if plan.approved_at:
            raise HTTPException(409,'建议所选计划已执行，请重新选择待审批计划')
        if plan.action=='batch':
            _,_,_,digest = prepare_batch(db,project_id,plan.parameters)
        else:
            _,snapshot = fixed_input(db,project_id,plan.action,plan.parameters)
            digest = fingerprint(snapshot)
        if digest!=plan.input_hash:
            raise HTTPException(409,'计划输入或授权已变化，请重新准备执行计划')
    call.status = 'accepted' if plan_id else 'rejected'
    call.review = {'request':request,'plan_id':plan_id,'recorded_at':now().isoformat()}
    text_service.event(db,task,'导演建议审核已记录'+(' · '+plan_id if plan_id else ' · 已退回'))
    text_service.sync_task_after_manual_action(task,call)
    db.commit()
    return text_service.call_public(call)


@router.get('/plans')
def plans(project_id: str, db=Depends(session)):
    require(db, Project, project_id)
    rows = db.execute(
        select(DirectorPlan, Task).outerjoin(Task, DirectorPlan.task_id == Task.id)
        .where(DirectorPlan.project_id == project_id)
        .order_by(DirectorPlan.created_at.desc(), DirectorPlan.id).limit(50)
    )
    return [public(plan, task) for plan, task in rows]


@router.get('/plans/{plan_id}')
def get_plan(project_id: str, plan_id: str, db=Depends(session)):
    return details(db, scoped_plan(db, project_id, plan_id))


@router.post('/plans', status_code=201)
def prepare(project_id: str, body: Draft, db=Depends(session)):
    lock_project(db, project_id)
    action = body.operation.action
    params = body.operation.model_dump(exclude={'action'})
    if action=='batch' and params['policy']['dialogue_asr_language'] is None:
        params['policy'].pop('dialogue_asr_language')
    previous = db.scalar(select(DirectorPlan).where(
        DirectorPlan.project_id == project_id, DirectorPlan.request_key == body.idempotency_key))
    if previous:
        if (previous.instruction, previous.action, previous.parameters) != (body.instruction, action, params):
            raise HTTPException(409, '请求键已用于其他执行计划')
        return details(db, previous)
    preview = None
    if action == 'batch':
        _, _, episodes, digest = prepare_batch(db, project_id, params)
        spec = episodes[0].snapshot.get('production_spec')
        preview = [{'number': item.number, 'version_id': item.version.id, 'title': item.version.title,
                    'version': item.version.number, 'mode': item.mode} for item in episodes]
    else:
        _, snapshot = fixed_input(db, project_id, action, params)
        digest = fingerprint(snapshot)
        spec = snapshot.get('production_spec')
    if not spec:
        approval_spec(db,project_id,{},require_pin=True)
    plan = DirectorPlan(project_id=project_id, request_key=body.idempotency_key, instruction=body.instruction,
                        action=action, parameters=params, input_hash=digest, preview=preview,
                        production_spec_version_id=spec['id'] if spec else None)
    db.add(plan)
    db.commit()
    return public(plan)


@router.post('/plans/{plan_id}/execute')
def execute(project_id: str, plan_id: str, db=Depends(session)):
    lock_project(db, project_id)
    plan = scoped_plan(db, project_id, plan_id)
    if plan.approved_at:
        return details(db, plan)
    if plan.action == 'batch':
        body, policy, episodes, digest = prepare_batch(db, project_id, plan.parameters)
        if digest != plan.input_hash:
            raise HTTPException(409, '批次输入或可复用产物已变化，请重新准备计划并审核')
        run = production.enqueue_run(db, project_id, body, policy, episodes, 'director:' + uid(),
                                     fingerprint(plan.parameters))
        plan.run_id = run.id
        plan.approved_at = now()
        db.commit()
        return details(db, plan)
    source, snapshot = fixed_input(db, project_id, plan.action, plan.parameters)
    if fingerprint(snapshot) != plan.input_hash:
        raise HTTPException(409, '输入或授权记录已变化，请重新准备计划并审核')
    key = 'director:' + uid()
    if plan.action == 'render':
        task = timeline.enqueue_render(db, project_id, source, key, snapshot)
    else:
        task = delivery.enqueue_package(db, project_id, source, key, plan.parameters, snapshot)
    plan.task_id = task.id
    plan.approved_at = now()
    db.commit()
    return public(plan, task)

"""Approve and dispatch fixed local work through the existing production queue."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, StringConstraints
from sqlalchemy import select

from . import delivery, timeline
from .analysis_service import fingerprint
from .creative import require, version_ref
from .db import session
from .library import Region, Slug
from .models import DirectorPlan, Project, Task, now, uid
from .story_schemas import Strict, Timeline

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


class Draft(Strict):
    instruction: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    idempotency_key: str = Field(min_length=1, max_length=64)
    operation: Render | Package = Field(discriminator='action')


def lock_project(db, project_id):
    if not db.scalar(select(Project.id).where(Project.id == project_id).with_for_update()):
        raise HTTPException(404, '项目不存在')


def fixed_input(db, project_id, action, params):
    if action == 'render':
        _, version = version_ref(db, project_id, params['version_id'], {'timeline'})
        snapshot = timeline.render_snapshot(db, project_id, version, Timeline.model_validate(version.content))
        return version, snapshot
    return delivery.package_snapshot(db, project_id, params)


def public(plan, task=None):
    return {
        'id': plan.id, 'instruction': plan.instruction, 'action': plan.action, 'parameters': plan.parameters,
        'input_hash': plan.input_hash, 'created_at': plan.created_at, 'approved_at': plan.approved_at,
        'external_cost_cents': 0,
        'task': {
            'id': task.id, 'status': task.status, 'stage': task.stage, 'progress': task.progress,
            'elapsed_seconds': task.elapsed_seconds, 'error': task.error,
        } if task else None,
    }


def scoped_plan(db, project_id, plan_id):
    plan = db.get(DirectorPlan, plan_id)
    if not plan or plan.project_id != project_id:
        raise HTTPException(404, '执行计划不存在')
    return plan


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
    plan = scoped_plan(db, project_id, plan_id)
    return public(plan, db.get(Task, plan.task_id) if plan.task_id else None)


@router.post('/plans', status_code=201)
def prepare(project_id: str, body: Draft, db=Depends(session)):
    lock_project(db, project_id)
    action = body.operation.action
    params = body.operation.model_dump(exclude={'action'})
    previous = db.scalar(select(DirectorPlan).where(
        DirectorPlan.project_id == project_id, DirectorPlan.request_key == body.idempotency_key))
    if previous:
        if (previous.instruction, previous.action, previous.parameters) != (body.instruction, action, params):
            raise HTTPException(409, '请求键已用于其他执行计划')
        return public(previous, db.get(Task, previous.task_id) if previous.task_id else None)
    _, snapshot = fixed_input(db, project_id, action, params)
    plan = DirectorPlan(project_id=project_id, request_key=body.idempotency_key, instruction=body.instruction,
                        action=action, parameters=params, input_hash=fingerprint(snapshot))
    db.add(plan)
    db.commit()
    return public(plan)


@router.post('/plans/{plan_id}/execute')
def execute(project_id: str, plan_id: str, db=Depends(session)):
    lock_project(db, project_id)
    plan = scoped_plan(db, project_id, plan_id)
    if plan.task_id:
        return public(plan, db.get(Task, plan.task_id))
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

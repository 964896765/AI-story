"""Approve and execute project-scoped Agent work with the existing Worker."""

from typing import Annotated, Literal
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, StringConstraints, model_validator
from sqlalchemy import select

from .agent_tools import RULE_VERSION, ROLES, WORKFLOWS, execute_role, frozen
from .analysis_service import fingerprint
from .creative import require
from .db import session
from .models import AgentRun, Project, Task, TaskEvent, now
from .story_schemas import Strict, VersionId

router = APIRouter(prefix='/api/projects/{project_id}/agents',tags=['agent-execution'])
Note = Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=2000)]
Digest = Annotated[str,Field(pattern=r'^[0-9a-f]{64}$')]


class Draft(Strict):
    workflow: Literal['story','preflight']
    goal: Note
    production_spec_version_id: VersionId
    source_version_id: VersionId | None = None
    series_version_id: VersionId | None = None
    timeline_version_id: VersionId | None = None
    external_budget_cents: int = Field(default=0,ge=0,le=0,strict=True)
    idempotency_key: str = Field(min_length=1,max_length=64,pattern=r'\S')

    @model_validator(mode='after')
    def required_inputs(self):
        if self.workflow=='story':
            if not self.source_version_id or self.series_version_id or self.timeline_version_id:
                raise ValueError('原稿筹备只接受一个固定原稿版本')
        elif self.source_version_id or not (self.series_version_id and self.timeline_version_id):
            raise ValueError('生产预检须指定批准计划和固定时间轴')
        return self


class Approval(Strict):
    expected_input_sha256: Digest
    note: Note


class Review(Strict):
    decision: Literal['accepted','rejected']
    expected_output_sha256: Digest
    note: Note


def role_info(role):
    title, need, output, permission = ROLES[role]
    return {'id':role,'label':title,'input':need,'output':output,'permission':permission,
            'engine':'local_rules','external_cost_cents':0}


def lock_project(db, project_id):
    if not db.scalar(select(Project.id).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')


def scoped(db, project_id, run_id, *, lock=False):
    statement = select(AgentRun).where(AgentRun.project_id==project_id,AgentRun.id==run_id)
    run = db.scalar(statement.with_for_update() if lock else statement)
    if not run:
        raise HTTPException(404,'当前项目没有此 Agent 运行')
    return run


def stages(db, run, *, lock=False):
    if not run.task_ids:
        return []
    statement = select(Task).where(Task.project_id==run.project_id,Task.id.in_(run.task_ids),
                                   Task.kind=='agent_step').order_by(Task.id)
    rows = {row.id:row for row in db.scalars(statement.with_for_update() if lock else statement)}
    if set(rows)!=set(run.task_ids):
        raise HTTPException(409,'Agent 运行的任务记录不完整')
    return [rows[key] for key in run.task_ids]


def state(run, tasks):
    if run.review:
        return run.review['decision']
    if run.cancelled_at:
        return 'cancelling' if any(task.status=='running' for task in tasks) else 'cancelled'
    if not run.approval:
        return 'awaiting_approval'
    if all(task.status=='succeeded' for task in tasks) and tasks:
        return 'awaiting_review'
    if any(task.status=='failed' for task in tasks):
        return 'failed'
    if any(task.status=='running' for task in tasks) or any(task.attempt for task in tasks):
        return 'running'
    return 'queued'


def output_hash(tasks):
    results = []
    previous = None
    for task in tasks:
        output = task.output
        if (task.status!='succeeded' or fingerprint(output.get('result'))!=output.get('result_sha256')
            or output.get('previous_result_sha256')!=previous or output.get('role')!=task.parameters['role']
            or output.get('input_sha256')!=task.input_snapshot['input_sha256']):
            return None
        previous = output['result_sha256']
        results.append({'task_id':task.id,'result_sha256':previous})
    return fingerprint(results) if results else None


def public(run, tasks, *, detail=True):
    result = {'id':run.id,'workflow':run.request['workflow'],'goal':run.request['goal'],'status':state(run,tasks),
              'created_at':run.created_at,'production_spec_version_id':run.production_spec_version_id,
              'approval':run.approval,'review':run.review,'input_sha256':run.input_sha256,
              'output_sha256':output_hash(tasks),'external_budget_cents':0,'external_cost_cents':0}
    if detail:
        result['inputs'] = {key:value for key,value in run.inputs.items() if key!='assets'}
        result['asset_count'] = len(run.inputs.get('assets',{}))
        result['steps'] = [{**role_info(task.parameters['role']),'task_id':task.id,'status':task.status,
                           'stage':task.stage,'progress':task.progress,'attempt':task.attempt,
                           'elapsed_seconds':task.elapsed_seconds,'error_code':task.error_code,
                           'error':task.error,'result':task.output or None}
                           for task in tasks] if tasks else [role_info(role) for role in WORKFLOWS[run.request['workflow']]]
    return result


@router.get('/capabilities')
def capabilities(project_id: str, db=Depends(session)):
    require(db,Project,project_id)
    return {'rule_version':RULE_VERSION,'workflows':WORKFLOWS,'roles':[role_info(role) for role in ROLES]}


@router.get('/runs')
def list_runs(project_id: str, db=Depends(session)):
    require(db,Project,project_id)
    runs = db.scalars(select(AgentRun).where(AgentRun.project_id==project_id)
                      .order_by(AgentRun.created_at.desc(),AgentRun.id).limit(30)).all()
    ids = [key for run in runs for key in run.task_ids]
    tasks = {task.id:task for task in db.scalars(select(Task).where(Task.project_id==project_id,Task.id.in_(ids)))}
    return [public(run,[tasks[key] for key in run.task_ids if key in tasks],detail=False) for run in runs]


@router.get('/runs/{run_id}')
def get_run(project_id: str, run_id: str, db=Depends(session)):
    run = scoped(db,project_id,run_id)
    return public(run,stages(db,run))


@router.post('/runs',status_code=201)
def prepare(project_id: str, body: Draft, db=Depends(session)):
    lock_project(db,project_id)
    request = body.model_dump(exclude={'idempotency_key'})
    previous = db.scalar(select(AgentRun).where(AgentRun.project_id==project_id,AgentRun.request_key==body.idempotency_key))
    if previous:
        if previous.request!=request:
            raise HTTPException(409,'请求键已用于另一项 Agent 运行')
        return public(previous,stages(db,previous))
    inputs = frozen(db,project_id,request)
    run = AgentRun(project_id=project_id,production_spec_version_id=body.production_spec_version_id,
                   request_key=body.idempotency_key,request=request,inputs=inputs,
                   input_sha256=fingerprint([request,inputs]))
    db.add(run)
    db.commit()
    return public(run,[])


@router.post('/runs/{run_id}/approve')
def approve(project_id: str, run_id: str, body: Approval, db=Depends(session)):
    lock_project(db,project_id)
    run = scoped(db,project_id,run_id,lock=True)
    if run.cancelled_at or body.expected_input_sha256!=run.input_sha256:
        raise HTTPException(409,'运行已取消或审批依据不符')
    if run.approval:
        if run.approval['note']!=body.note:
            raise HTTPException(409,'该运行已有不同的审批记录')
        return public(run,stages(db,run))
    if fingerprint([run.request,frozen(db,project_id,run.request)])!=run.input_sha256:
        raise HTTPException(409,'固定输入已变化，请重新准备')
    tasks = []
    primary = run.inputs.get('source') or run.inputs['series']
    for index,role in enumerate(WORKFLOWS[run.request['workflow']]):
        task = Task(project_id=project_id,kind='agent_step',story_version_id=primary['id'],
                    dependency_task_id=tasks[-1].id if tasks else None,idempotency_key=f'agent:{run.id}:{index}',
                    parameters={'run_id':run.id,'role':role,'position':index},
                    input_snapshot={'input_sha256':run.input_sha256,'production_spec':run.inputs['production_spec']})
        db.add(task)
        db.flush()
        db.add(TaskEvent(task_id=task.id,attempt=0,message='人工审批通过，固定本机 Agent 工具已排队'))
        tasks.append(task)
    run.task_ids = [task.id for task in tasks]
    run.approval = {'at':now().isoformat(),'note':body.note,'input_sha256':run.input_sha256}
    db.commit()
    return public(run,tasks)


@router.post('/runs/{run_id}/review')
def review(project_id: str, run_id: str, body: Review, db=Depends(session)):
    run = scoped(db,project_id,run_id,lock=True)
    tasks = stages(db,run,lock=True)
    digest = output_hash(tasks)
    if digest is None or digest!=body.expected_output_sha256 or run.cancelled_at:
        raise HTTPException(409,'仅可审核当前完整、已校验的输出')
    if run.review:
        if (run.review['decision'],run.review['note'])!=(body.decision,body.note):
            raise HTTPException(409,'该运行已有审核记录')
        return public(run,tasks)
    run.review = {'at':now().isoformat(),'decision':body.decision,'note':body.note,'output_sha256':digest}
    db.commit()
    return public(run,tasks)


@router.post('/runs/{run_id}/cancel')
def cancel(project_id: str, run_id: str, db=Depends(session)):
    run = scoped(db,project_id,run_id,lock=True)
    tasks = stages(db,run,lock=True)
    if run.cancelled_at:
        return public(run,tasks)
    if state(run,tasks) not in ('awaiting_approval','queued','running','failed'):
        raise HTTPException(409,'已完成的输出请使用审核入口')
    run.cancelled_at = now()
    for task in tasks:
        if task.status not in ('running','queued'):
            continue
        task.cancel_requested = True
        if task.status=='queued':
            task.status, task.stage, task.finished_at = 'cancelled','cancelled',now()
        db.add(TaskEvent(task_id=task.id,attempt=task.attempt,message='项目 Agent 运行已请求取消'))
    db.commit()
    return public(run,tasks)


@router.post('/runs/{run_id}/retry')
def retry(project_id: str, run_id: str, db=Depends(session)):
    run = scoped(db,project_id,run_id,lock=True)
    tasks = stages(db,run,lock=True)
    if state(run,tasks)!='failed' or any(task.status=='running' for task in tasks):
        raise HTTPException(409,'仅失败且未取消的 Agent 运行可重试')
    failed = [task for task in tasks if task.status=='failed']
    if any(task.attempt>=task.max_attempts for task in failed):
        raise HTTPException(409,'角色已达到任务尝试上限')
    for task in tasks:
        if task.status not in ('failed','cancelled'):
            continue
        task.status,task.stage,task.progress = 'queued','queued',0
        task.cancel_requested,task.error,task.error_code = False,None,None
        task.started_at,task.finished_at,task.next_run_at = None,None,now()
        task.output,task.elapsed_seconds = {},0
        db.add(TaskEvent(task_id=task.id,attempt=task.attempt,message='重试失败及受阻步骤，保留已完成结果'))
    db.commit()
    return public(run,tasks)


def execute(task_id, project_id, inputs, parameters, update, factory):
    update('agent_verify_inputs',10)
    with factory() as db:
        run = scoped(db,project_id,parameters['run_id'])
        index, role = parameters['position'], parameters['role']
        if (not run.approval or run.cancelled_at or not 0<=index<len(run.task_ids) or run.task_ids[index]!=task_id
            or WORKFLOWS[run.request['workflow']][index]!=role or run.input_sha256!=inputs['input_sha256']
            or run.inputs['rule_version']!=RULE_VERSION or fingerprint([run.request,run.inputs])!=run.input_sha256):
            raise ValueError('Agent 任务未经批准或固定输入已变化')
        previous = None
        if index:
            parent = require(db,Task,run.task_ids[index-1])
            if parent.status!='succeeded' or fingerprint(parent.output.get('result'))!=parent.output.get('result_sha256'):
                raise ValueError('上一步结果尚未校验')
            previous = parent.output
        update('agent_execute_role',45)
        result = execute_role(db,run,role,previous,update)
    update('agent_check_output',95)
    return {'role':role,'rule_version':RULE_VERSION,'input_sha256':inputs['input_sha256'],
            'previous_result_sha256':previous['result_sha256'] if previous else None,
            'external_cost_cents':0,'result':result,'result_sha256':fingerprint(result)}

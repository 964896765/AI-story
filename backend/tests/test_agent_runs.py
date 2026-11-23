from datetime import timedelta

import pytest
from sqlalchemy import delete, func, select

from app import agent_runs, worker
from app.models import AgentRun, ModelCall, Project, Task, TaskAttempt, now
from test_creative import creative
from test_postgres import database
from test_render_postgres import studio


@pytest.fixture
def agents(creative):
    workbench, create = creative
    client, project, *_, factory = workbench
    settings = {'episode_count':2,'episode_duration_ms':1500,'style':'线稿','fps':24,
                'profile':'square','width':720,'height':720,'platform':'local-test','region':'CN','budget_cents':0}
    spec = client.post(f'/api/projects/{project}/production-specs',json={
        'expected_version':0,'settings':settings,'idempotency_key':'test-agent-spec'
    }).json()
    novel = create('novel','港灯',{'text':'守灯人登上灯塔。\n\n归船在雾中找到港口。','authorization':'原创测试'})
    body = {'workflow':'story','goal':'准备两集原创试制','production_spec_version_id':spec['id'],
            'source_version_id':novel['version_id'],'idempotency_key':'test-agent-run'}
    try:
        yield client,f'/api/projects/{project}/agents/runs',project,body,factory,novel,settings
    finally:
        with factory.begin() as db:
            db.execute(delete(AgentRun).where(AgentRun.project_id==project))


def prepare_and_approve(client, root, body):
    draft = client.post(root,json=body)
    assert draft.status_code==201,draft.text
    document = draft.json()
    path = f'{root}/{document["id"]}'
    response = client.post(path+'/approve',json={'expected_input_sha256':document['input_sha256'],'note':'核对固定输入'})
    assert response.status_code==200,response.text
    return path,response.json()


def test_agent_approval_pins_versions_and_reviews_hashed_handoffs(agents):
    client,root,project,body,factory,novel,settings = agents
    assert client.post(root,json={**body,'external_budget_cents':1}).status_code==422
    response = client.post(root,json=body)
    assert response.status_code==201,response.text
    draft = response.json()
    assert draft['status']=='awaiting_approval' and len(draft['steps'])==3
    assert client.post(root,json=body).json()['id']==draft['id']
    assert client.post(root,json={**body,'goal':'不允许用相同键改成别的目标'}).status_code==409
    assert client.get(f'/api/projects/{project}/tasks').json()==[]
    path = f'{root}/{draft["id"]}'
    with factory.begin() as db:
        other = Project(name='Agent tenant test')
        db.add(other)
        db.flush()
        other_id = other.id
    try:
        foreign = f'/api/projects/{other_id}/agents/runs'
        assert client.get(foreign).json()==[]
        assert client.get(f'{foreign}/{draft["id"]}').status_code==404
        assert client.post(foreign,json=body).status_code==404
    finally:
        with factory.begin() as db:
            db.execute(delete(Project).where(Project.id==other_id))
    changed = client.post(f'/api/projects/{project}/production-specs',json={
        'expected_version':1,'idempotency_key':'new-style','settings':{**settings,'style':'城市夜景'},
    })
    assert changed.status_code==201,changed.text
    edited = client.post(f'/api/story/entities/{novel["id"]}/versions',json={
        'expected_version':1,'idempotency_key':'new-source','title':'港灯','content':{**novel['content'],'text':'新版原稿'},
    })
    assert edited.status_code==201,edited.text
    approval = {'expected_input_sha256':draft['input_sha256'],'note':'核对固定输入'}
    assert client.post(path+'/approve',json={**approval,'expected_input_sha256':'0'*64}).status_code==409
    approved = client.post(path+'/approve',json=approval).json()
    assert approved['status']=='queued'
    task_ids = [step['task_id'] for step in approved['steps']]
    repeat = client.post(path+'/approve',json=approval).json()
    assert [step['task_id'] for step in repeat['steps']]==task_ids
    assert client.post('/api/tasks/'+task_ids[0]+'/cancel').status_code==409
    assert client.post('/api/tasks/'+task_ids[0]+'/retry').status_code==409
    for _ in task_ids:
        assert worker.run_once()
    done = client.get(path).json()
    assert done['status']=='awaiting_review',done
    results = [step['result'] for step in done['steps']]
    assert [step['role'] for step in results]==['director','analysis','writer']
    assert results[0]['result']['style']=='线稿'
    assert results[1]['result']['opening_excerpt']=='守灯人登上灯塔。'
    assert results[2]['result']['requires_human_edit'] is True
    assert [step['previous_result_sha256'] for step in results]==[None,results[0]['result_sha256'],results[1]['result_sha256']]
    review = {'decision':'accepted','expected_output_sha256':done['output_sha256'],'note':'已核对原稿摘录'}
    assert client.post(path+'/review',json={**review,'expected_output_sha256':'0'*64}).status_code==409
    with factory.begin() as db:
        db.get(Task,task_ids[-1]).output = {**results[-1],'previous_result_sha256':'0'*64}
    assert client.post(path+'/review',json=review).status_code==409
    with factory.begin() as db:
        db.get(Task,task_ids[-1]).output = results[-1]
    reviewed = client.post(path+'/review',json=review)
    assert reviewed.status_code==200,reviewed.text
    assert reviewed.json()['status']=='accepted' and reviewed.json()['review']['note']==review['note']
    assert client.post(path+'/review',json=review).json()['review']==reviewed.json()['review']
    assert client.post(path+'/review',json={**review,'decision':'rejected'}).status_code==409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ModelCall).where(ModelCall.project_id==project))==0


def test_agent_retry_reuses_successful_role_and_worker_recovers_lease(agents, monkeypatch):
    client,root,_,body,factory,*_ = agents
    path,approved = prepare_and_approve(client,root,body)
    director,analysis,writer = [step['task_id'] for step in approved['steps']]
    with factory.begin() as db:
        interrupted = db.get(Task,director)
        interrupted.status,interrupted.attempt = 'running',1
        interrupted.lease_until = now()-timedelta(seconds=1)
        db.add(TaskAttempt(task_id=director,number=1,worker_id='interrupted-worker',status='running',stage='agent_verify_inputs',
                           inputs=interrupted.input_snapshot,parameters=interrupted.parameters,checkpoints=[]))
    assert worker.run_once()
    with factory() as db:
        attempts = db.scalars(select(TaskAttempt).where(TaskAttempt.task_id==director).order_by(TaskAttempt.number)).all()
        assert [attempt.status for attempt in attempts]==['interrupted','succeeded']
    original = agent_runs.execute_role

    def fail_analysis(db, run, role, previous, update):
        if role=='analysis':
            raise ValueError('测试注入：剧情分析步骤失败')
        return original(db,run,role,previous,update)

    with monkeypatch.context() as patch:
        patch.setattr(agent_runs,'execute_role',fail_analysis)
        assert worker.run_once()
    assert not worker.run_once()
    failed = client.get(path).json()
    assert failed['status']=='failed'
    assert [step['status'] for step in failed['steps']]==['succeeded','failed','cancelled']
    assert failed['steps'][2]['error_code']=='DEPENDENCY_FAILED'
    retried = client.post(path+'/retry').json()
    assert [step['task_id'] for step in retried['steps']]==[director,analysis,writer]
    assert [step['status'] for step in retried['steps']]==['succeeded','queued','queued']
    assert worker.run_once() and worker.run_once()
    recovered = client.get(path).json()
    assert recovered['status']=='awaiting_review'
    assert [step['attempt'] for step in recovered['steps']]==[2,2,1]
    assert recovered['steps'][0]['result']==failed['steps'][0]['result']


def test_agent_cancellation_blocks_approval_and_queued_execution(agents):
    client,root,_,body,factory,*_ = agents
    draft = client.post(root,json=body).json()
    path = root+'/'+draft['id']
    assert client.post(path+'/cancel').json()['status']=='cancelled'
    assert client.post(path+'/approve',json={'expected_input_sha256':draft['input_sha256'],'note':'取消后尝试审批'}).status_code==409
    queued_path,_ = prepare_and_approve(client,root,{**body,'idempotency_key':'queued-run'})
    cancelled = client.post(queued_path+'/cancel').json()
    assert cancelled['status']=='cancelled'
    assert all(step['status']=='cancelled' and step['attempt']==0 for step in cancelled['steps'])
    assert not worker.run_once()
    assert client.post(queued_path+'/retry').status_code==409

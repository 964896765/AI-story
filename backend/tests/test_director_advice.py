from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from sqlalchemy import delete, update

from app import text_service, worker
from app.model_adapters import ModelResult
from app.models import Asset, DirectorPlan
from test_creative import creative
from test_postgres import database
from test_render_postgres import studio
from test_text_governance import governed


@pytest.fixture
def advisory(governed):
    fixture,create,_,provider,budget,*_ = governed
    client,project,asset,_,_,_,_,factory = fixture
    base = f'/api/director/projects/{project}'
    plans = []
    for frames in (24,30):
        version = create('timeline',f'港湾验收 {frames}',{'frames':frames,'profile':'square',
            'tracks':[{'id':'main','role':'main','clips':[{'id':'clip','asset_id':asset['id'],'at':0,'frames':frames}]}]})
        response = client.post(base+'/plans',json={
            'instruction':f'按固定版本渲染 {frames} 帧','operation':{'action':'render','version_id':version['version_id']},
            'idempotency_key':str(frames)})
        assert response.status_code==201,response.text
        plans.append(response.json())
    yield fixture,base,plans,provider,budget
    with factory.begin() as db:
        db.execute(delete(DirectorPlan).where(DirectorPlan.project_id==project))


class AdviceResponse:
    def __init__(self,choice):
        self.choice=choice

    def invoke(self,request):
        prompt=json.loads(request.prompt)
        assert 'options' in prompt and 'authorized_source' not in prompt
        assert 'source_text' not in request.parameters
        draft={'choice':self.choice,'rationale':'模型验收选择','checks':['核对固定时间轴']}
        return ModelResult('mock-director-test',{'text':json.dumps(draft,ensure_ascii=False)},None,None,
                           {'prompt_tokens':80,'completion_tokens':50},'stop','mock-test')


def test_choice_is_recorded_then_requires_separate_execution(advisory,monkeypatch):
    fixture,base,plans,provider,budget=advisory
    client,project,*_=fixture
    path=base+'/advice'
    simulated=provider()
    live=provider(kind='openai_compatible',base_url='https://example.com/v1',secret_env='DIRECTOR_TEST_API_KEY')
    body={'provider_id':simulated['id'],'goal':'比较两条待审批方案','plan_ids':[item['id'] for item in plans],
          'idempotency_key':'distinct-director-advice'}
    assert client.post(path,json=body).status_code==409
    assert client.post(path,json={**body,'provider_id':live['id']}).status_code==403
    budget()
    foreign=client.post('/api/projects',json={'name':'测试跨项目导演方案'}).json()['id']
    assert client.post(path.replace(project,foreign),json=body).status_code==404
    with ThreadPoolExecutor(max_workers=2) as pool:
        queued=list(pool.map(lambda _:client.post(path,json=body),range(2)))
    assert all(item.status_code==201 for item in queued)
    call=queued[0].json()
    assert call['id']==queued[1].json()['id'] and call['status']=='queued'
    assert client.post(path,json={**body,'goal':'修改目标'}).status_code==409
    endpoint=path+'/'+call['id']
    assert client.get(endpoint.replace(project,foreign)).status_code==404
    assert client.get(f'/api/text/projects/{project}/calls').json()==[]
    monkeypatch.setattr(text_service,'build_adapter',lambda *_:AdviceResponse(2))
    assert worker.run_once()
    ready=client.get(endpoint).json()
    assert ready['status']=='awaiting_review' and ready['budget_status']=='settled'
    assert ready['draft']['choice']==2 and ready['calculated_cost_micros']==180
    assert ready['actual_cost_micros'] is None and ready['simulated']
    assert client.get(f'/api/projects/{project}/overview').json()['draft_review_count']==0
    assert client.get(f"/api/text/calls/{call['id']}/compare").status_code==422
    review={'action':'accept','draft_revision':1,'note':'选择第二个固定版本'}
    accepted=client.post(endpoint+'/review',json=review)
    assert accepted.status_code==200,accepted.text
    assert accepted.json()['review']['plan_id']==plans[1]['id']
    assert client.post(endpoint+'/review',json=review).json()==accepted.json()
    assert client.post(endpoint+'/review',json={**review,'action':'reject'}).status_code==409
    assert client.get(base+'/plans/'+plans[1]['id']).json()['approved_at'] is None
    rows=client.get(f'/api/projects/{project}/tasks').json()
    assert len(rows)==1 and rows[0]['parameters']['purpose']=='director_advice'
    keys=[item['kind'] for item in client.get(f'/api/text/projects/{project}/ledger').json() if item['call_id']==call['id']]
    assert keys==['settle','reserve']
    run=client.post(base+'/plans/'+plans[1]['id']+'/execute')
    assert run.status_code==200,run.text
    assert worker.run_once()
    task_id=run.json()['task']['id']
    assert client.get(f'/api/tasks/{task_id}/output',headers={'Range':'bytes=0-31'}).status_code==206
    assert client.get(base+'/plans/'+plans[0]['id']).json()['approved_at'] is None


def test_invalid_proposal_and_unknown_usage_do_not_dispatch_local_work(advisory,monkeypatch):
    fixture,base,plans,provider,budget=advisory
    client,project,asset,*_,factory=fixture
    path=base+'/advice'
    budget()
    mock=provider()
    body={'provider_id':mock['id'],'goal':'核对选项范围','plan_ids':[plans[0]['id']],'idempotency_key':'invalid-choice'}
    queued=client.post(path,json=body).json()
    with monkeypatch.context() as patch:
        patch.setattr(text_service,'build_adapter',lambda *_:AdviceResponse(4))
        assert worker.run_once()
    invalid=client.get(path+'/'+queued['id']).json()
    assert invalid['status']=='invalid_output' and invalid['draft'] is None
    assert invalid['error_code']=='DIRECTOR_OPTION_OUT_OF_SCOPE'

    uncertain=provider('missing_usage')
    queued=client.post(path,json={**body,'provider_id':uncertain['id'],'idempotency_key':'unknown-usage'}).json()
    endpoint=path+'/'+queued['id']
    assert worker.run_once()
    assert client.get(endpoint).json()['status']=='cost_unknown'
    retry={'idempotency_key':'retry-director','acknowledge_new_charge':True}
    assert client.post(endpoint+'/retry',json=retry).status_code==409
    recovered=client.post(endpoint+'/reconcile',json={
        'resolution':'not_charged','evidence':'本机离线模拟未发生外部实付，用户手工确认释放模拟费用占用。'})
    assert recovered.status_code==200,recovered.text
    assert recovered.json()['budget_status']=='released'
    started=client.post(endpoint+'/retry',json=retry)
    assert started.status_code==201,started.text
    assert started.json()['id']!=queued['id']
    cancelled=client.post(path+'/'+started.json()['id']+'/cancel').json()
    assert cancelled['status']=='cancelled' and cancelled['budget_status']=='released'

    queued=client.post(path,json={**body,'idempotency_key':'changed-input'}).json()
    assert worker.run_once()
    with factory.begin() as db:
        db.execute(update(Asset).where(Asset.id==asset['id']).values(version=2))
    endpoint=path+'/'+queued['id']
    review={'action':'accept','draft_revision':1,'note':'尝试采纳过期建议'}
    assert client.post(endpoint+'/review',json=review).status_code==409
    assert client.post(endpoint+'/review',json={**review,'action':'reject'}).json()['status']=='rejected'
    assert all(item['kind']=='adapt' for item in client.get(f'/api/projects/{project}/tasks').json())

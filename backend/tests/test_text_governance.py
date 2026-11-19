import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import select,delete,func
from app import text_service as service
from app import worker
from app.models import ModelCall,ModelBudget,ModelLedger,ModelDraft,TextProvider,Task,StoryEntity,StoryVersion,now
from app.text_adapters import OpenAICompatibleAdapter,CallFailure
from app.model_adapters import ModelRequest
from test_postgres import database
from test_render_postgres import studio
from test_creative import creative

@pytest.fixture
def governed(creative):
    studio,create=creative
    client,project,asset,upload,submit,task,resolve,factory=studio
    source=create('novel','授权改编测试',{'text':'林舟回到旧城。\n\n守门人：你终于回来了。','authorization':'自行编写的测试素材'})
    provider_ids=[]
    def provider(scenario='success',kind='mock',**settings):
        body={'label':'模拟费率配置（非市场报价）','kind':kind,'enabled':True,'settings':{'model':'simulation-text','currency':'CNY','input_per_million':'1','output_per_million':'2','input_token_limit':8192,'output_token_limit':2048,'mock_scenario':scenario,**settings}}
        result=client.post('/api/text/providers',json=body)
        assert result.status_code==201,result.text
        row=result.json();provider_ids.append(row['id']);return row
    def budget(limit=1_000_000,mode='mock',**extra):
        result=client.post(f'/api/text/projects/{project}/budgets',json={'mode':mode,'currency':'CNY','limit_micros':limit,'idempotency_key':str(uuid4()),**extra})
        assert result.status_code==200,result.text
        return result.json()
    def request(pid,key=None,**extra):
        return {'source_version_id':source['version_id'],'provider_id':pid,'goal':'改为悬疑开场，保留核心人物关系','style':'简练','audience':'成年观众','length':'一集短稿','constraints':'不改变原始素材，不发布','max_output_tokens':1024,'idempotency_key':key or str(uuid4()),**extra}
    def call(pid,key=None,**extra):
        result=client.post(f'/api/text/projects/{project}/calls',json=request(pid,key,**extra))
        assert result.status_code==201,result.text
        return result.json()
    yield studio,create,source,provider,budget,request,call
    with factory.begin() as db:
        ids=select(ModelCall.id).where(ModelCall.project_id==project)
        budgets=select(ModelBudget.id).where(ModelBudget.project_id==project)
        db.execute(delete(ModelDraft).where(ModelDraft.call_id.in_(ids)))
        db.execute(delete(ModelLedger).where(ModelLedger.budget_id.in_(budgets)))
        db.execute(delete(ModelCall).where(ModelCall.project_id==project))
        db.execute(delete(ModelBudget).where(ModelBudget.project_id==project))
        db.execute(delete(TextProvider).where(TextProvider.id.in_(provider_ids)))

def get(client,cid):return client.get(f'/api/text/calls/{cid}').json()

def test_budget_reserve_settle_and_duplicate_requests(governed):
    studio,create,source,provider,budget,request,call=governed
    client,project,*_=studio
    p=provider();budget()
    first=call(p['id'],'same-key');same=call(p['id'],'same-key')
    assert first['id']==same['id'] and first['simulated'] and first['actual_cost_micros'] is None
    b=client.get(f'/api/text/projects/{project}/budgets').json()[0]
    assert b['reserved_micros']==first['reserved_micros']
    worker.run_once();done=get(client,first['id'])
    assert done['status']=='awaiting_review' and done['budget_status']=='settled'
    assert done['usage']['prompt_tokens']==100 and done['calculated_cost_micros']==260
    assert done['actual_cost_micros'] is None
    for _ in range(2):assert client.post(f"/api/text/calls/{first['id']}/settle").status_code==200
    b=client.get(f'/api/text/projects/{project}/budgets').json()[0]
    assert b['reserved_micros']==0 and b['spent_micros']==260
    entries=client.get(f'/api/text/projects/{project}/ledger').json()
    assert len([e for e in entries if e['kind']=='settle'])==1

def test_concurrent_reservations_and_no_overspend(governed):
    studio,create,source,provider,budget,request,call=governed
    client,project,*_=studio
    p=provider();budget(15000)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda i:client.post(f'/api/text/projects/{project}/calls',json=request(p['id'],str(i))),range(2)))
    assert sorted(r.status_code for r in results)==[201,409]
    b=client.get(f'/api/text/projects/{project}/budgets').json()[0]
    assert b['reserved_micros']<=b['limit_micros']

def test_zero_budget_unknown_price_and_missing_authorization_block(governed,monkeypatch):
    studio,create,source,provider,budget,request,call=governed
    client,project,*_=studio
    p=provider();budget(0)
    assert client.post(f'/api/text/projects/{project}/calls',json=request(p['id'])).status_code==409
    budget()
    unknown=provider(input_per_million=None)
    assert client.get(f"/api/text/providers/{unknown['id']}/quote").json()['upper_bound_micros'] is None
    assert client.post(f'/api/text/projects/{project}/calls',json=request(unknown['id'])).status_code==409
    live=provider(kind='openai_compatible',base_url='https://example.invalid/v1',secret_env='TEST_TEXT_API_KEY',billing_verified=True,price_source='test fixture only')
    monkeypatch.delenv('AI_STORY_ENABLE_PAID_TEXT',raising=False)
    assert client.post(f'/api/text/projects/{project}/budgets',json={'mode':'live','limit_micros':1000,'idempotency_key':'live-budget'}).status_code==403
    assert client.post(f'/api/text/projects/{project}/calls',json=request(live['id'])).status_code==403

@pytest.mark.parametrize('scenario,status,held',[('rate_limit','failed',False),('timeout','unknown',True),('server_error','unknown',True),('invalid_output','invalid_output',False),('missing_usage','cost_unknown',True)])
def test_failure_policy_never_blindly_retries(governed,scenario,status,held):
    studio,create,source,provider,budget,request,call=governed
    client,project,*_=studio
    p=provider(scenario);budget();row=call(p['id']);worker.run_once()
    done=get(client,row['id']);assert done['status']==status
    b=client.get(f'/api/text/projects/{project}/budgets').json()[0]
    assert (b['reserved_micros']>0)==held
    assert worker.run_once() is False
    assert client.post(f"/api/tasks/{row['task_id']}/retry").status_code==409
    if held:assert client.post(f"/api/text/calls/{row['id']}/retry",json={'idempotency_key':'new','acknowledge_new_charge':True}).status_code==409
    if scenario=='invalid_output':assert done['draft'] is None and done['calculated_cost_micros']==260

def test_unknown_release_requires_evidence_and_never_double_releases(governed):
    studio,create,source,provider,budget,request,call=governed
    client,project,*_=studio
    p=provider('timeout');budget();row=call(p['id']);worker.run_once()
    assert client.post(f"/api/text/calls/{row['id']}/reconcile",json={'resolution':'not_charged','evidence':'short'}).status_code==422
    body={'resolution':'not_charged','evidence':'人工查阅供应商测试账单，确认此请求未受理且未收费（模拟验收证据）'}
    assert client.post(f"/api/text/calls/{row['id']}/reconcile",json=body).status_code==200
    assert client.post(f"/api/text/calls/{row['id']}/reconcile",json=body).status_code==409
    assert client.get(f'/api/text/projects/{project}/budgets').json()[0]['reserved_micros']==0

def test_missing_usage_can_be_reconciled_without_generation(governed):
    studio,create,source,provider,budget,request,call=governed
    client,project,asset,upload,submit,task,resolve,factory=studio
    p=provider('missing_usage');budget();row=call(p['id']);worker.run_once()
    with factory() as db:receipt=dict(db.get(ModelCall,row['id']).receipt)
    receipt['usage']={'prompt_tokens':100,'completion_tokens':80}
    result=client.post(f"/api/text/calls/{row['id']}/reconcile",json={'resolution':'receipt','evidence':'补充同一供应商调用的用量，内容保持原样；此为模拟测试凭证','receipt':receipt})
    assert result.status_code==200 and result.json()['status']=='awaiting_review',result.text


def test_released_unknown_receipt_cannot_reopen_settlement(governed):
    studio,_,_,provider,budget,_,call=governed
    client,project,*_=studio
    p=provider('missing_usage');budget();row=call(p['id']);worker.run_once()
    path=f"/api/text/calls/{row['id']}"
    assert client.post(path+'/reconcile',json={'resolution':'not_charged',
        'evidence':'模拟供应商凭证：该次请求未受理计费，确认释放原先占用的额度。'}).status_code==200
    assert client.post(path+'/settle').status_code==409
    assert get(client,row['id'])['budget_status']=='released'
    assert client.get(f'/api/text/projects/{project}/budgets').json()[0]['reserved_micros']==0

def test_cancel_before_dispatch_and_after_dispatch(governed,monkeypatch):
    studio,create,source,provider,budget,request,call=governed
    client,project,*_=studio
    p=provider();budget();queued=call(p['id'])
    assert client.post(f"/api/text/calls/{queued['id']}/cancel").json()['budget_status']=='released'
    assert worker.run_once() is False
    row=call(p['id']);original=service.build_adapter;entered=threading.Event();release=threading.Event()
    class Blocking:
        def invoke(self,request):entered.set();assert release.wait(10);return original('mock',p['settings']).invoke(request)
    monkeypatch.setattr(service,'build_adapter',lambda *args:Blocking())
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(worker.run_once)
        try:
            assert entered.wait(5)
            client.post(f"/api/text/calls/{row['id']}/cancel")
            assert client.get(f'/api/text/projects/{project}/budgets').json()[0]['reserved_micros']>0
        finally:release.set()
        assert pending.result(timeout=10)
    done=get(client,row['id']);assert done['status']=='cancelled' and done['budget_status']=='settled'

def test_settlement_crash_recovers_receipt_without_second_send(governed,monkeypatch):
    studio,create,source,provider,budget,request,call=governed
    client,project,*_=studio
    p=provider();budget();row=call(p['id'])
    original=service.finalize_receipt;calls=[];builder=service.build_adapter
    class Counting:
        def invoke(self,request):calls.append(request.idempotency_key);return builder('mock',p['settings']).invoke(request)
    monkeypatch.setattr(service,'build_adapter',lambda *args:Counting())
    def interrupted(*args):raise RuntimeError('injected local settlement interruption')
    monkeypatch.setattr(service,'finalize_receipt',interrupted)
    worker.run_once();assert get(client,row['id'])['status']=='received'
    monkeypatch.setattr(service,'finalize_receipt',original)
    worker.run_once()
    assert get(client,row['id'])['status']=='awaiting_review' and len(calls)==1

def test_overrun_halts_more_calls(governed):
    studio,create,source,provider,budget,request,call=governed
    client,project,*_=studio
    p=provider('overrun');budget(20000);row=call(p['id']);worker.run_once()
    assert get(client,row['id'])['status']=='budget_overrun'
    b=client.get(f'/api/text/projects/{project}/budgets').json()[0]
    assert b['halted'] and b['spent_micros']>b['limit_micros']
    assert client.post(f'/api/text/projects/{project}/calls',json=request(p['id'])).status_code==409

def test_review_gate_edit_history_accept_and_real_video(governed):
    studio,create,source,provider,budget,request,call=governed
    client,project,asset,upload,submit,task,resolve,factory=studio
    p=provider();budget();row=call(p['id']);worker.run_once();done=get(client,row['id'])
    with factory() as db:assert db.scalar(select(func.count()).select_from(StoryEntity).where(StoryEntity.project_id==project,StoryEntity.kind=='script'))==0
    draft={**done['draft'],'body':'人工审核修改后的正文。'}
    edit=client.post(f"/api/text/calls/{row['id']}/draft",json={'expected_revision':1,'draft':draft,'idempotency_key':'edit'})
    assert edit.status_code==200 and edit.json()['draft_revision']==2
    assert client.post(f"/api/text/calls/{row['id']}/review",json={'action':'accept','draft_revision':1,'note':'stale approval'}).status_code==409
    review={'action':'accept','draft_revision':2,'note':'已人工审核。模拟结果不代表真实AI验收。'}
    accepted=client.post(f"/api/text/calls/{row['id']}/review",json=review)
    assert accepted.status_code==200,accepted.text
    assert client.post(f"/api/text/calls/{row['id']}/review",json=review).json()['accepted_version_id']==accepted.json()['accepted_version_id']
    version_id=accepted.json()['accepted_version_id']
    version=client.get(f'/api/story/versions/{version_id}').json()
    assert version['provenance']['reviewed'] and version['provenance']['simulated']
    assert version['content']['body']=='人工审核修改后的正文。'
    assert client.get(f"/api/story/versions/{source['version_id']}").json()['content']['text']==source['content']['text']
    render=client.post(f'/api/projects/{project}/batches',json={'asset_ids':[asset['id']],'parameters':{'duration':1},'story_version_id':version_id,'idempotency_key':'accepted-video'})
    assert render.status_code==201,render.text
    worker.run_once();output=task(render.json()['tasks'][0]['id'])
    assert output['status']=='succeeded' and resolve(output['output']['storage_key']).exists()

def test_http_contract_and_secret_redaction_without_network(monkeypatch):
    secret='test-secret-only-not-a-real-key';seen=[]
    monkeypatch.setenv('AI_STORY_ENABLE_PAID_TEXT','1');monkeypatch.setenv('AI_STORY_BUDGET_GUARD_APPROVED','1');monkeypatch.setenv('AI_STORY_LIVE_AUTHORIZATION_ID','test-only')
    monkeypatch.setenv('TEST_TEXT_API_KEY',secret)
    def respond(request):
        seen.append(json.loads(request.content));assert request.headers['authorization']=='Bearer '+secret
        return httpx.Response(200,json={'id':'call-local-fixture','choices':[{'message':{'content':json.dumps({'echo':secret})},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':5}},headers={'x-request-id':'request-local'})
    from app.text_schemas import ProviderSettings
    settings=ProviderSettings(base_url='https://example.invalid/v1',model='configured-model',secret_env='TEST_TEXT_API_KEY').model_dump(mode='json')
    request=ModelRequest('test','unique','text','JSON input',(),{'system_prompt':'JSON only','max_output_tokens':512})
    result=OpenAICompatibleAdapter(settings,httpx.MockTransport(respond)).invoke(request)
    assert secret not in result.output['text'] and '[REDACTED]' in result.output['text']
    assert seen[0]['model']=='configured-model' and seen[0]['max_completion_tokens']==512 and seen[0]['response_format']['type']=='json_schema'
    assert seen[0]['store'] is False and seen[0]['stream'] is False
    monkeypatch.delenv('TEST_TEXT_API_KEY')
    with pytest.raises(CallFailure,match='API_KEY_NOT_CONFIGURED'):OpenAICompatibleAdapter(settings,httpx.MockTransport(respond)).invoke(request)

def test_provider_validation_never_echoes_rejected_secret(governed):
    studio,*_=governed;client=studio[0]
    fake='test-only-secret-value'
    result=client.post('/api/text/providers',json={'api_key':fake})
    assert result.status_code==422 and fake not in result.text


def test_billing_evidence_adjusts_mock_balance_once_and_caps_refund(governed):
    studio,_,_,provider,budget,_,call=governed
    client,project,*_=studio
    configured=provider()
    budget()
    row=call(configured['id'])
    assert worker.run_once()
    path=f"/api/text/calls/{row['id']}/billing"
    invoice={'kind':'charge','amount_micros':400,'evidence':'Independent test invoice confirming provider charge.','idempotency_key':'invoice'}
    refund={'kind':'refund','amount_micros':100,'evidence':'Independent test refund entry for the same invoice.','idempotency_key':'refund'}
    for entry in (invoice,invoice,refund,refund):
        result=client.post(path,json=entry)
        assert result.status_code==200,result.text
        assert result.json()['actual_cost_micros'] is None
    assert client.post(path,json={**refund,'amount_micros':301,'idempotency_key':'another'}).status_code==409
    assert client.post(path,json={**invoice,'amount_micros':401}).status_code==409
    assert client.get(f'/api/text/projects/{project}/budgets').json()[0]['spent_micros']==300
    ledger=client.get(f'/api/text/projects/{project}/ledger').json()
    assert [entry['kind'] for entry in ledger].count('charge')==1
    assert [entry['kind'] for entry in ledger].count('refund')==1


def test_live_ceiling_blocks_dispatch_after_authorization_is_lowered(governed,monkeypatch):
    studio,_,_,provider,budget,request,call=governed
    client,project,*_=studio
    endpoint='https://example.invalid/v1'
    for key,value in {
        'AI_STORY_ENABLE_PAID_TEXT':'1','AI_STORY_BUDGET_GUARD_APPROVED':'1',
        'AI_STORY_LIVE_AUTHORIZATION_ID':'test-only','AI_STORY_LIVE_BASE_URL':endpoint,
        'AI_STORY_LIVE_SECRET_ENV':'TEST_TEXT_API_KEY','AI_STORY_LIVE_LIMIT_CNY_MICROS':'15000',
        'TEST_TEXT_API_KEY':'offline-fixture-no-network',
    }.items():
        monkeypatch.setenv(key,value)
    approved=provider(kind='openai_compatible',base_url=endpoint,secret_env='TEST_TEXT_API_KEY',
        billing_verified=True,price_source='test fixture only')
    unapproved=provider(kind='openai_compatible',base_url='https://other.invalid/v1',secret_env='TEST_TEXT_API_KEY',
        billing_verified=True,price_source='test fixture only')
    budget(50000,'live',authorization_id='test-only')
    result=client.post(f'/api/text/projects/{project}/calls',json=request(unapproved['id']))
    assert result.status_code==403 and result.json()['detail']=='PROVIDER_ENDPOINT_NOT_AUTHORIZED'
    first=call(approved['id'])
    result=client.post(f'/api/text/projects/{project}/calls',json=request(approved['id']))
    assert result.status_code==409
    monkeypatch.setenv('AI_STORY_LIVE_LIMIT_CNY_MICROS','1')
    def forbidden(*args):
        pytest.fail('No adapter may be built after the live ceiling is lowered')
    monkeypatch.setattr(service,'build_adapter',forbidden)
    assert worker.run_once()
    row=get(client,first['id'])
    assert row['error_code']=='GLOBAL_BUDGET_BLOCKED_BEFORE_DISPATCH' and row['budget_status']=='released'


@pytest.mark.parametrize('sent',[False,True])
def test_worker_restart_before_and_after_dispatch(governed,monkeypatch,sent):
    studio,_,_,provider,budget,_,call=governed
    client,_,_,_,_,task,_,factory=studio
    p=provider();budget();row=call(p['id'])
    with factory.begin() as db:
        job=db.get(Task,row['task_id']);job.status='running';job.attempt=1
        job.lease_until=now()-timedelta(seconds=1);job.worker_token='lost-worker'
        if sent:
            record=db.get(ModelCall,row['id']);record.status='dispatching';record.sent_at=now()
    if sent:
        monkeypatch.setattr(service,'build_adapter',lambda *args:pytest.fail('Ambiguous dispatch must never be replayed'))
    worker.run_once()
    done=get(client,row['id'])
    assert done['status']==('unknown' if sent else 'awaiting_review')
    assert done['budget_status']==('unknown' if sent else 'settled')
    assert task(row['task_id'])['status']==('failed' if sent else 'succeeded')
    assert worker.run_once() is False


def test_explicit_retry_and_draft_history_restoration(governed):
    studio,_,_,provider,budget,_,call=governed
    client,_,_,_,_,task,_,_=studio
    p=provider();budget();first=call(p['id'])
    client.post(f"/api/text/calls/{first['id']}/cancel")
    path=f"/api/text/calls/{first['id']}/retry"
    body={'idempotency_key':'explicit-new-call','acknowledge_new_charge':True}
    retried=client.post(path,json=body).json()
    assert client.post(path,json=body).json()['id']==retried['id']
    worker.run_once();done=get(client,retried['id'])
    original=client.get(f"/api/text/calls/{retried['id']}/drafts/1").json()['payload']
    edit_path=f"/api/text/calls/{retried['id']}/draft"
    changed={**original,'body':'人工修订一次。'}
    assert client.post(edit_path,json={'expected_revision':1,'draft':changed,'idempotency_key':'v2'}).status_code==200
    restored=client.post(edit_path,json={'expected_revision':2,'draft':original,'idempotency_key':'restore-v1'}).json()
    assert restored['draft_revision']==3 and restored['draft']==original
    assert client.get(f"/api/text/calls/{retried['id']}/drafts/2").json()['payload']==changed
    assert client.post(f"/api/text/calls/{retried['id']}/review",json={'action':'reject','draft_revision':3,'note':'拒稿不退还已发生的模拟消耗'}).json()['status']=='rejected'
    assert task(retried['task_id'])['stage']=='rejected'
    assert get(client,retried['id'])['calculated_cost_micros']==done['calculated_cost_micros']


def test_source_append_conflict_preserves_versions_and_approval_gate(governed):
    studio,create,_,provider,budget,_,call=governed
    client,project,asset,_,_,task,_,_=studio
    source=create('script','固定源剧本',{'body':'固定原稿正文。'})
    p=provider();budget();row=call(p['id'],source_version_id=source['version_id']);worker.run_once()
    # A call ID is never a formal story-version ID.
    assert client.post(f'/api/projects/{project}/batches',json={'asset_ids':[asset['id']],
        'story_version_id':row['id'],'parameters':{},'idempotency_key':'unreviewed'}).status_code==404
    response=client.post(f"/api/story/entities/{source['id']}/versions",json={
        'expected_version':1,'title':'已更新原稿','content':{'body':'并发人工新正文。'},'idempotency_key':'source-v2'})
    assert response.status_code==201
    path=f"/api/text/calls/{row['id']}/review"
    review={'action':'accept','draft_revision':1,'note':'审核通过','save_mode':'source_new_version','expected_source_version':2}
    assert client.post(path,json=review).status_code==409
    approved=client.post(path,json={**review,'save_mode':'new_script'}).json()
    assert approved['accepted_version_id'] and task(row['task_id'])['stage']=='approved'
    assert client.get(f"/api/story/versions/{source['version_id']}").json()['content']['body']=='固定原稿正文。'


@pytest.mark.parametrize('http_status,known,code,unknown',[
    (429,True,'RATE_LIMIT_REJECTED',False),(429,False,'HTTP_429_OUTCOME_UNKNOWN',True),
    (500,True,'HTTP_500_OUTCOME_UNKNOWN',True),(401,True,'HTTP_401_REJECTED',False)])
def test_local_http_rejection_contract(monkeypatch,http_status,known,code,unknown):
    from app.text_schemas import ProviderSettings
    for key in ('AI_STORY_ENABLE_PAID_TEXT','AI_STORY_BUDGET_GUARD_APPROVED'):
        monkeypatch.setenv(key,'1')
    monkeypatch.setenv('AI_STORY_LIVE_AUTHORIZATION_ID','offline-only')
    monkeypatch.setenv('TEST_TEXT_API_KEY','fixture-not-a-key')
    settings=ProviderSettings(base_url='https://example.invalid/v1',model='test',secret_env='TEST_TEXT_API_KEY',
        rejection_is_nonbillable=known).model_dump(mode='json')
    sends=[]
    def respond(request):
        sends.append(1);return httpx.Response(http_status,json={'error':'never expose raw provider errors'})
    with pytest.raises(CallFailure) as error:
        OpenAICompatibleAdapter(settings,httpx.MockTransport(respond)).invoke(
            ModelRequest('test','unique','text','{}',(),{'system_prompt':'JSON','max_output_tokens':128}))
    assert error.value.code==code and error.value.unknown is unknown and len(sends)==1


@pytest.mark.parametrize('finish',['length','refusal',None])
def test_incomplete_output_is_never_reviewable(finish):
    from app.adaptation_policy import validated_draft
    with pytest.raises(CallFailure,match='MODEL_OUTPUT_INCOMPLETE_OR_REFUSED'):
        validated_draft({'content':'{}','finish_reason':finish})


def test_cached_and_reasoning_usage_survives_receipt_round_trip():
    from app.adaptation_policy import validated_usage
    usage={'prompt_tokens':100,'completion_tokens':80,'prompt_tokens_details':{'cached_tokens':20},
        'completion_tokens_details':{'reasoning_tokens':30}}
    normalized=validated_usage(usage)
    assert validated_usage(normalized)==normalized
    assert normalized['cached_tokens']==20 and normalized['reasoning_tokens']==30 and normalized['total_tokens']==180


def test_financial_migration_downgrade_is_refused(governed):
    studio,_,_,provider,budget,_,call=governed
    client,_,_,_,_,_,_,factory=studio
    p=provider();budget();call(p['id'])
    result=subprocess.run([sys.executable,'-m','alembic','downgrade','0005'],
        env={**os.environ,'DATABASE_URL':os.environ['TEST_DATABASE_URL']},capture_output=True,text=True,timeout=30)
    assert result.returncode!=0 and 'P5 financial audit records exist' in result.stderr
    from sqlalchemy import text
    with factory() as db:assert db.scalar(text('SELECT version_num FROM alembic_version'))=='0012'


def test_new_worker_process_recovers_persisted_receipt_without_network(governed):
    studio,_,_,provider,budget,_,call=governed
    client,_,_,_,_,task,_,factory=studio
    p=provider();budget();row=call(p['id']);worker.run_once()
    with factory.begin() as db:
        call_record=db.get(ModelCall,row['id']);call_record.status='received';call_record.budget_status='reserved'
        call_record.calculated_cost_micros=None;call_record.draft=None;call_record.draft_revision=0
        account=db.get(ModelBudget,call_record.budget_id)
        account.spent_micros=0;account.reserved_micros=call_record.reserved_micros
        db.execute(delete(ModelDraft).where(ModelDraft.call_id==row['id']))
        db.execute(delete(ModelLedger).where(ModelLedger.call_id==row['id'],ModelLedger.kind=='settle'))
        job=db.get(Task,row['task_id']);job.status='running';job.lease_until=now()-timedelta(seconds=1)
        job.worker_token='terminated-process'
    # A genuinely new interpreter has no in-memory mock or previous session state.
    program='from app import text_service,worker\ndef no_send(*a): raise AssertionError("Recovery must not call an adapter")\ntext_service.build_adapter=no_send\nassert worker.run_once()\nassert not worker.run_once()'
    result=subprocess.run([sys.executable,'-c',program],env={**os.environ,
        'DATABASE_URL':os.environ['TEST_DATABASE_URL'],'AI_STORY_ENABLE_PAID_TEXT':'0'},
        capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    assert get(client,row['id'])['status']=='awaiting_review' and task(row['task_id'])['stage']=='awaiting_review'

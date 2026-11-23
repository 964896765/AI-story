import base64
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import delete, select

from app import image_adapter, worker
from app.models import ModelBudget, ModelConnectionDraft, ModelLedger, Project, Task, now
from app.text_adapters import CallFailure
from test_creative import creative
from test_postgres import database
from test_render_postgres import studio


@pytest.fixture
def images(creative):
    fixture, create = creative
    client,project,_,upload,_,_,resolve,factory = fixture
    reference = upload('reference.png',image_adapter.simulation('square').content)
    source = create('character','守灯人',{'appearance':'海蓝色大衣','reference_asset_ids':[reference['id']]})
    response = client.post(f'/api/projects/{project}/production-specs',json={
        'expected_version':0,'idempotency_key':'images','settings':{'episode_count':1,'episode_duration_ms':1500,
        'style':'线稿','profile':'portrait','width':720,'height':1280,'fps':24,'platform':'local-test',
        'region':'CN','budget_cents':100,'budget_currency':'USD'}})
    assert response.status_code==201,response.text
    root = f'/api/generation/projects/{project}/images'
    body = {'spec_version_id':response.json()['id'],'source_version_id':source['version_id'],
            'prompt':'港口守灯人立姿参考','idempotency_key':'fixture'}
    try:
        yield client,project,root,body,reference,resolve,factory
    finally:
        with factory.begin() as db:
            ids = select(ModelBudget.id).where(ModelBudget.project_id==project)
            db.execute(delete(ModelLedger).where(ModelLedger.budget_id.in_(ids)))
            db.execute(delete(ModelBudget).where(ModelBudget.project_id==project))
            db.execute(delete(ModelConnectionDraft).where(ModelConnectionDraft.connector=='openai-image'))


def test_real_png_mock_candidate_review_and_adoption(images):
    client,project,root,body,reference,resolve,factory = images
    capabilities = client.get(root+'/capabilities').json()
    assert capabilities['mock_available'] and not capabilities['live_available'] and capabilities['quote'] is None
    assert client.post(root,json={**body,'mode':'openai','confirm_external_text':True}).status_code==403
    queued = client.post(root,json=body)
    assert queued.status_code==201,queued.text
    row = queued.json()
    path = f'{root}/{row["id"]}'
    assert client.post(root,json=body).json()['id']==row['id']
    assert client.get(path).json()['id']==row['id']
    assert client.post(root,json={**body,'prompt':'键重复'}).status_code==409
    assert client.get(path+'/file').status_code==409
    foreign = client.post('/api/projects',json={'name':'隔离测试'}).json()['id']
    try:
        assert client.get(path.replace(project,foreign)).status_code==404
        assert client.get(path.replace(project,foreign)+'/file').status_code==404
    finally:
        with factory.begin() as db:
            db.execute(delete(Project).where(Project.id==foreign))
    with factory.begin() as db:
        stale = db.get(Task,row['id'])
        stale.status,stale.attempt = 'running',1
        stale.lease_until = now()-timedelta(seconds=1)
    assert worker.run_once()
    [result] = client.get(root).json()
    assert result['status']=='succeeded',result
    assert result['attempt']==2 and result['mode']=='mock' and result['actual_cost_micros']==0
    assert (result['output']['width'],result['output']['height'])==(1024,1536)
    file = client.get(path+'/file')
    assert file.status_code==200 and file.content==image_adapter.simulation('portrait').content
    selection = {'expected_sha256':result['output']['sha256'],'title':'模拟入库'}
    assert client.post(path+'/adopt',json=selection).status_code==409
    review = {'decision':'approved','expected_sha256':result['output']['sha256'],'note':'已人工核验模拟流程',
              'reference_asset_id':reference['id'],'checks':result['checks']}
    assert client.post(path+'/review',json={**review,'checks':[]}).status_code==422
    assert client.post(path+'/review',json={**review,'expected_sha256':'0'*64}).status_code==409
    assert client.post(path+'/review',json=review).status_code==200
    receipt = client.post(path+'/adopt',json=selection)
    assert receipt.status_code==201,receipt.text
    adopted = receipt.json()['output']['adoption']['asset_id']
    assert client.post(path+'/adopt',json=selection).json()['output']['adoption']['asset_id']==adopted
    asset = next(a for a in client.get(f'/api/projects/{project}/assets').json() if a['id']==adopted)
    assert asset['media_info']['simulated'] and asset['media_info']['source_version_id']==body['source_version_id']
    resolve(asset['storage_key']).write_bytes(b'broken')
    assert client.get(path+'/file').status_code==409


def authorize_image(client, project, monkeypatch):
    for key,value in {
        'AI_STORY_ENABLE_PAID_IMAGE':'1','AI_STORY_ENABLE_PAID_TEXT':'0','AI_STORY_BUDGET_GUARD_APPROVED':'1',
        'AI_STORY_LIVE_AUTHORIZATION_ID':'image-contract-test','AI_STORY_IMAGE_PROJECT_ID':project,
        'AI_STORY_IMAGE_MODEL':'gpt-image-1','AI_STORY_IMAGE_SECRET_ENV':'AI_STORY_IMAGE_TEST_API_KEY',
        'AI_STORY_IMAGE_TEST_API_KEY':'test-image-credential','AI_STORY_IMAGE_CURRENCY':'USD',
        'AI_STORY_IMAGE_MAX_MICROS':'750000','AI_STORY_IMAGE_PRICE_SOURCE':'协议测试，不代表报价',
        'AI_STORY_LIVE_LIMIT_USD_MICROS':'1000000',
    }.items():
        monkeypatch.setenv(key,value)
    assert client.post('/api/models/connections/openai-image',json={
        'base_url':image_adapter.BASE_URL,'model':'gpt-image-1','secret_env':'AI_STORY_IMAGE_TEST_API_KEY'}).status_code==200
    budget = client.post(f'/api/text/projects/{project}/budgets',json={'mode':'live','currency':'USD','limit_micros':1000000,
        'authorization_id':'image-contract-test','idempotency_key':'image-budget'})
    assert budget.status_code==200,budget.text


def test_image_unknown_held_no_replay_invoice_and_unsent_cancel(images, monkeypatch):
    client,project,root,body,_,_,factory = images
    authorize_image(client,project,monkeypatch)
    seen = []
    real_transport = image_adapter.generate

    def service(request):
        seen.append(request)
        return httpx.Response(503,json={'reason':'vendor response is private'})

    monkeypatch.setattr(image_adapter,'generate',lambda *args:real_transport(*args,transport=httpx.MockTransport(service)))
    request = {**body,'mode':'openai','confirm_external_text':True}
    assert client.post(root,json={**request,'confirm_external_text':False}).status_code==422
    accepted = client.post(root,json=request)
    assert accepted.status_code==201,accepted.text
    created = accepted.json()
    assert created['actual_cost_micros'] is None and created['billing']['reserved_micros']==750000
    assert client.post(root,json={**request,'idempotency_key':'blocked','prompt':'另外一张'}).status_code==409
    assert worker.run_once()
    assert len(seen)==1
    assert json.loads(seen[0].content)['prompt']==request['prompt']+'\n\n视觉风格：线稿\n制作限制：'
    [failed] = client.get(root).json()
    assert failed['status']=='failed' and failed['billing']['state']=='awaiting_invoice'
    assert failed['error_code']=='IMAGE_HTTP_503_UNKNOWN' and failed['actual_cost_micros'] is None
    assert client.post(root,json=request).json()['id']==created['id']
    assert client.post(root,json={**request,'idempotency_key':'cannot-replay'}).status_code==409
    assert client.post(f'/api/tasks/{created["id"]}/retry').status_code==409
    with factory.begin() as db:
        interrupted = db.get(Task,created['id'])
        interrupted.status = 'running'
        interrupted.lease_until = now()-timedelta(seconds=1)
    assert worker.run_once() and len(seen)==1
    assert not worker.run_once() and len(seen)==1
    path = f'{root}/{created["id"]}/invoice'
    invoice = {'actual_cost_micros':1234,'evidence':'隔离模拟账单'}
    for _ in range(2):
        assert client.post(path,json=invoice).json()['actual_cost_micros']==1234
    ready = client.post(root,json={**request,'idempotency_key':'cancel-before-send'}).json()
    assert client.post(f'/api/tasks/{ready["id"]}/cancel').status_code==200
    assert len(seen)==1
    with factory() as db:
        budget = db.scalar(select(ModelBudget).where(ModelBudget.project_id==project))
        assert budget.reserved_micros==0 and budget.spent_micros==1234
        assert db.get(Task,ready['id']).output['billing']['state']=='released'


def test_image_success_receipt_recovers_without_resending(images, monkeypatch):
    client,project,root,body,_,_,factory = images
    authorize_image(client,project,monkeypatch)
    request = {**body,'mode':'openai','confirm_external_text':True}
    monkeypatch.setenv('AI_STORY_IMAGE_MAX_MICROS','0')
    assert client.post(root,json=request).status_code==409
    monkeypatch.setenv('AI_STORY_IMAGE_MAX_MICROS','750000')
    accepted = client.post(root,json=request)
    assert accepted.status_code==201,accepted.text
    task_id = accepted.json()['id']
    calls = []

    def fake_result(*arguments):
        calls.append(arguments[0])
        return image_adapter.ImageResult(image_adapter.simulation('portrait').content,'test-receipt',{'total_tokens':20})

    monkeypatch.setattr(image_adapter,'generate',fake_result)
    assert worker.run_once()
    with factory.begin() as db:
        interrupted = db.get(Task,task_id)
        assert interrupted.status=='succeeded'
        interrupted.status = 'running'
        interrupted.output = {'billing':interrupted.output['billing']}
        interrupted.lease_until = now()-timedelta(seconds=1)
    assert worker.run_once() and calls==['gpt-image-1']
    [recovered] = client.get(root).json()
    assert recovered['status']=='succeeded' and recovered['output']['vendor_request_id']=='test-receipt'
    assert recovered['output']['usage']=={'total_tokens':20} and recovered['actual_cost_micros'] is None


def test_openai_image_transport_contract_and_malformed_output():
    candidate = image_adapter.simulation('square').content
    def simulate(request):
        assert request.method=='POST' and str(request.url)==image_adapter.BASE_URL+'/images/generations'
        assert request.headers['authorization']=='Bearer test-token' and request.headers['x-client-request-id']=='image-call'
        assert json.loads(request.content)=={'model':'gpt-image-1','prompt':'测试','size':'1024x1024',
            'quality':'medium','n':1,'output_format':'png','stream':False}
        return httpx.Response(200,headers={'x-request-id':'receipt-id'},json={
            'data':[{'b64_json':base64.b64encode(candidate).decode()}],
            'usage':{'input_tokens':14,'output_tokens':15,'total_tokens':29}})
    result = image_adapter.generate('gpt-image-1','测试','square','test-token','image-call',transport=httpx.MockTransport(simulate))
    assert result.content==candidate and result.request_id=='receipt-id' and result.usage['total_tokens']==29
    for malformed in ({'data':[{'url':'https://example.com/image.png'}]}, {'data':[{'b64_json':'%%%'}]}):
        transport = httpx.MockTransport(lambda _:httpx.Response(200,json=malformed))
        with pytest.raises(CallFailure,match='IMAGE_RESPONSE_OUTCOME_UNKNOWN'):
            image_adapter.generate('gpt-image-1','测试','square','test-token','image-call',transport=transport)

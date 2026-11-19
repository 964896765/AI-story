from io import BytesIO
from zipfile import ZipFile

import pytest
from sqlalchemy import delete,select

from app import worker
from app.models import ChannelProfile, Publication, SettlementEntry
from test_creative import creative
from test_delivery import delivery_fixture
from test_postgres import database
from test_production import series_fixture
from test_render_postgres import studio


@pytest.fixture
def ops(delivery_fixture):
    studio,*_=delivery_fixture
    client,project,_,_,_,_,_,factory=studio
    dist=f'/api/distribution/projects/{project}'
    channel={'label':'线下验收剧场','organization':'自有验收组织','account_label':'fixture-account',
             'platform':'local-test','region':'CN','rules_url':'https://example.invalid/rules',
             'verified':True,'verification_note':'本地规则测试，未连接真实平台','idempotency_key':'channel'}
    created=client.post(dist+'/channels',json=channel)
    assert created.status_code==201,created.text
    yield delivery_fixture,dist,channel,created.json()
    with factory.begin() as db:
        db.execute(delete(SettlementEntry).where(SettlementEntry.channel_id.in_(
            select(ChannelProfile.id).where(ChannelProfile.project_id==project))))
        db.execute(delete(Publication).where(Publication.project_id==project))
        db.execute(delete(ChannelProfile).where(ChannelProfile.project_id==project))


def test_confirmed_cash_ad_credit_estimate_and_duplicate_csv(ops):
    fixture,dist,channel_form,channel=ops
    studio,*_=fixture
    client,project,*_=studio
    path=f'/api/finance/projects/{project}'
    csv=('external_id,currency,kind,status,amount,period_start,period_end,evidence\n'
         'cash-1,CNY,cash,confirmed,10.250001,2026-11-01,2026-11-15,actual cash fixture\n'
         'ad-1,CNY,ad_credit,confirmed,50,2026-11-01,2026-11-15,ad credits fixture\n'
         'rent-1,CNY,expense,confirmed,2.10,2026-11-01,2026-11-15,expense fixture\n'
         'usd-1,USD,cash,unknown,,2026-11-01,2026-11-15,pending evidence\n'
         'forecast,CNY,cash,estimate,89,2026-11-01,2026-11-15,estimate fixture\n')
    body={'channel_id':channel['id'],'csv':csv}
    assert client.post(path+'/settlements/import',json=body).json()=={'inserted':5,'duplicates':0}
    newer=client.post(dist+'/channels',json={**channel_form,'verification_note':'Second rule snapshot fixture','idempotency_key':'channel-v2'}).json()
    assert newer['rule_version']==2
    assert client.post(path+'/settlements/import',json={**body,'channel_id':newer['id']}).json()=={'inserted':0,'duplicates':5}
    res=client.post(path+'/settlements/import',json={**body,'csv':csv.replace('10.250001','10.250002')})
    assert res.status_code==409
    result=client.get(path+'/summary')
    assert result.status_code==200,result.text
    summary=result.json()['by_currency']
    cny,usd=summary
    assert cny['amounts_micros']['cash']=='10250001'
    assert cny['amounts_micros']['ad_credit']=='50000000'
    assert cny['recorded_cash_difference_micros']=='8150001' and cny['estimate_entries']==1
    assert usd['unknown_entries']==1 and usd['amounts_micros']['cash']=='0'
    assert len(client.get(path+'/settlements').json())==5


def test_rights_checked_manual_publication_and_real_promo(ops):
    fixture,dist,_,channel=ops
    studio,path,prep,timeline=fixture
    client,project,video,_,_,task,*_=studio
    plan=prep(1)
    made=client.post(path,json={'plan_version_id':plan,'timelines':[timeline(plan,1)],'idempotency_key':'distribution-qc'})
    assert made.status_code==201,made.text
    run=made.json()['id']
    assert worker.run_once() and worker.run_once()
    grant={'status':'approved','source_type':'owned','holder':'自制测试权利人','evidence':'自编合成媒体，仅用于验收',
           'commercial':True,'regions':['CN'],'platforms':['local-test'],'idempotency_key':'grant-distribution'}
    assert client.post(f"/api/library/assets/{video['id']}/rights",json=grant).status_code==201
    zipped=client.post(f'/api/delivery/projects/{project}/packages',json={'run_id':run,'title':'本机交付',
        'platform':'local-test','region':'CN','idempotency_key':'ops-delivery'})
    assert zipped.status_code==201,zipped.text
    assert worker.run_once()
    package=zipped.json()['id']
    record=client.post(dist+'/publications',json={'channel_id':channel['id'],'delivery_task_id':package,
        'title':'手工记录验收','idempotency_key':'publication'})
    assert record.status_code==201,record.text
    assert record.json()['status']=='draft' and record.json()['mode']=='manual_record'
    route='/api/distribution/publications/'+record.json()['id']+'/events'
    for start,end in [('draft','planned'),('planned','submitted'),('submitted','published')]:
        result=client.post(route,json={'expected_status':start,'status':end,
            'evidence':'人为记录的本机验收流程，没有外部运行','idempotency_key':end})
        assert result.status_code==201,result.text
    assert len(result.json()['events'])==3
    assert client.post(route,json={'expected_status':'draft','status':'published',
        'evidence':'invalid transition test','idempotency_key':'invalid'}).status_code==409
    promo=client.post(dist+'/promotions',json={'delivery_task_id':package,'episode':1,'title':'本地预告',
        'description':'自有样本中选取半秒作为验收预告','start_seconds':0,'duration_seconds':.5,'idempotency_key':'trial'})
    assert promo.status_code==201,promo.text
    assert worker.run_once()
    check=task(promo.json()['id'])
    assert check['status']=='succeeded',check['error']
    download=client.get('/api/distribution/promotions/'+promo.json()['id']+'/file')
    assert download.status_code==200
    with ZipFile(BytesIO(download.content)) as archive:
        assert set(archive.namelist())=={'highlight.mp4','cover.jpg','manifest.json'}
        assert archive.read('highlight.mp4')[4:8]==b'ftyp'

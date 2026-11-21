from datetime import timedelta
from hashlib import sha256
from io import BytesIO
import json
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import delete,select

from app import worker
from app.models import Asset,AssetRight,LibraryWork,now
from test_creative import creative
from test_postgres import database
from test_production import series_fixture
from test_render_postgres import studio


@pytest.fixture
def delivery_fixture(series_fixture):
    yield series_fixture
    studio,*_=series_fixture
    _,project,_,_,_,_,_,factory=studio
    with factory.begin() as db:
        db.execute(delete(AssetRight).where(AssetRight.asset_id.in_(select(Asset.id).where(Asset.project_id==project))))
        db.execute(delete(LibraryWork).where(LibraryWork.project_id==project))


def test_catalog_pagination_sort_search_and_archive(delivery_fixture):
    studio,*_=delivery_fixture
    client,project,video,*_=studio
    root=f'/api/library/projects/{project}/works'
    body={'title':'灯塔短集','origin':'自有本机生产素材','tags':['港口'],'idempotency_key':'catalog-1',
          'episodes':[{'number':10,'title':'第十集','asset_id':video['id']},
                      {'number':2,'title':'第二集','asset_id':video['id']}]}
    response=client.post(root,json=body)
    assert response.status_code==201,response.text
    work=response.json()
    assert [item['number'] for item in work['episodes']]==[2,10]
    assert client.post(root,json=body).json()==work
    results=client.get(root,params={'q':'灯塔','tag':'港口','limit':1}).json()
    assert results['total']==1 and results['items'][0]['id']==work['id']
    assert client.post(f"/api/library/works/{work['id']}/archive").json()['archived']
    assert client.get(root).json()['total']==0
    assert client.get(f"/api/assets/{video['id']}/media").status_code==200


def test_real_delivery_rights_gates_and_verified_archive(delivery_fixture):
    studio,path,prep,timeline=delivery_fixture
    client,project,asset,_,_,task,_,_=studio
    plan=prep(1)
    made=client.post(path,json={'plan_version_id':plan,'timelines':[timeline(plan,1)],'idempotency_key':'release-ready'})
    assert made.status_code==201,made.text
    run=made.json()['id']
    package_route=f'/api/delivery/projects/{project}/packages'
    readiness_route=f'/api/delivery/projects/{project}/runs/{run}/readiness'
    body={'run_id':run,'title':'灯塔交付包','platform':'local-test','region':'CN','idempotency_key':'delivery'}
    target={'platform':'local-test','region':'CN'}
    pending=client.get(readiness_route,params=target)
    assert pending.status_code==200,pending.text
    assert pending.json()['pending_episodes']==[{'number':1,'status':'processing','issue_count':0}]
    assert not pending.json()['ready'] and not pending.json()['rights_checked']
    assert client.get(path+'/'+run).json()['id']==run
    foreign=f'/api/production/projects/{uuid4()}/runs/{run}'
    assert client.get(foreign).status_code==404
    assert client.get(readiness_route.replace(project,str(uuid4())),params=target).status_code==404
    assert client.get(readiness_route,params={**target,'platform':'invalid slug'}).status_code==422
    assert client.post(package_route,json=body).status_code==409
    assert worker.run_once() and worker.run_once()
    assert client.get('/api/production/runs/'+run).json()['status']=='passed'

    def blocked(reason):
        response=client.post(package_route,json=body)
        assert response.status_code==409,response.text
        assert reason in response.json()['detail']['assets'][0]['reason']
        report=client.get(readiness_route,params=target).json()
        assert report['rights_checked'] and not report['ready']
        assert report['blockers']==response.json()['detail']['assets']
        assert report['source_count']==1 and report['authorized_sources']==0
        assert client.get(package_route).json()==[]

    blocked('待核验')
    rights=f"/api/library/assets/{asset['id']}/rights"
    grant={'status':'approved','source_type':'owned','holder':'自制测试权利人','evidence':'自编并生成的合成媒体，仅验收',
           'commercial':True,'regions':['CN'],'platforms':['local-test']}
    result=client.post(rights,json={**grant,'expires_at':(now()-timedelta(days=1)).isoformat(),'idempotency_key':'expired'})
    assert result.status_code==201,result.text
    blocked('到期')
    result=client.post(rights,json={**grant,'platforms':['another'],'idempotency_key':'scope'})
    assert result.status_code==201,result.text
    blocked('平台或地域')
    allowed=client.post(rights,json={**grant,'idempotency_key':'approved'})
    assert allowed.status_code==201,allowed.text
    ready=client.get(readiness_route,params=target).json()
    assert ready['ready'] and ready['authorized_sources']==1 and len(ready['authorization_revision'])==64
    assert client.get(package_route).json()==[]
    created=client.post(package_route,json=body)
    assert created.status_code==201,created.text
    package=created.json()
    assert client.get(package_route+'/'+package['id']).json()['id']==package['id']
    assert client.get(package_route.replace(project,str(uuid4()))+'/'+package['id']).status_code==404
    assert client.post(package_route,json=body).json()['id']==package['id']
    assert worker.run_once()
    result=task(package['id'])
    assert result['status']=='succeeded',result['error']
    url='/api/delivery/packages/'+package['id']+'/file'
    downloaded=client.get(url)
    assert downloaded.status_code==200
    assert sha256(downloaded.content).hexdigest()==result['output']['sha256']
    with ZipFile(BytesIO(downloaded.content)) as archive:
        manifest=json.loads(archive.read('manifest.json'))
        assert len(manifest['files'])==5
        assert 'episode-001/cover.jpg' in archive.namelist()
        assert archive.read('episode-001/cover.jpg').startswith(b'\xff\xd8')
        for entry in manifest['files']:
            assert sha256(archive.read(entry['path'])).hexdigest()==entry['sha256']
        assert json.loads(archive.read('rights.json'))[0]['right_id']==allowed.json()['id']
    assert client.post(rights,json={**grant,'status':'revoked','idempotency_key':'revoke'}).status_code==201
    assert not client.get(readiness_route,params=target).json()['ready']
    assert client.get(url).status_code==409
    assert client.post(rights,json={**grant,'idempotency_key':'approve-again'}).status_code==201
    assert client.get(readiness_route,params=target).json()['authorization_revision']!=ready['authorization_revision']
    assert client.get(url).status_code==409


def test_checked_caption_is_required_at_packaging(delivery_fixture):
    studio,path,prep,timeline=delivery_fixture
    client,project,video,upload,_,task,resolve,_=studio
    caption=upload('授权字幕.srt','1\n00:00:00,000 --> 00:00:00,830\n自行编写的交付字幕\n'.encode())
    plan=prep(1)
    run=client.post(path,json={'plan_version_id':plan,'timelines':[timeline(plan,1,caption=caption)],
                               'policy':{'require_subtitles':True},'idempotency_key':'caption-ready'}).json()
    assert worker.run_once() and worker.run_once()
    checked=client.get(path+'/'+run['id']).json()
    assert checked['status']=='passed'
    episode=checked['episodes'][0]
    grant={'status':'approved','source_type':'owned','holder':'自制样本','evidence':'合成样片与自编字幕',
           'commercial':True,'regions':['CN'],'platforms':['local-test'],'idempotency_key':'rights'}
    for item in (video,caption):
        assert client.post(f"/api/library/assets/{item['id']}/rights",json=grant).status_code==201
    package_route=f'/api/delivery/projects/{project}/packages'
    response=client.post(package_route,json={'run_id':run['id'],'title':'含字幕交付','platform':'local-test',
                                            'region':'CN','idempotency_key':'caption-missing'})
    assert response.status_code==201,response.text
    pack_id=response.json()['id']
    storage_key=task(episode['render_task_id'])['output']['caption_storage_key']
    resolve(storage_key).unlink()
    assert worker.run_once()
    failed=task(pack_id)
    assert failed['status']=='failed' and '已质检字幕文件缺失' in failed['error']
    assert client.get('/api/delivery/packages/'+pack_id+'/file').status_code==409

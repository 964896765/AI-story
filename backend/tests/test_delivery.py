from datetime import timedelta
from hashlib import sha256
from io import BytesIO
import json
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
    body={'run_id':run,'title':'灯塔交付包','platform':'local-test','region':'CN','idempotency_key':'delivery'}
    assert client.post(package_route,json=body).status_code==409
    assert worker.run_once() and worker.run_once()
    assert client.get('/api/production/runs/'+run).json()['status']=='passed'

    def blocked(reason):
        response=client.post(package_route,json=body)
        assert response.status_code==409,response.text
        assert reason in response.json()['detail']['assets'][0]['reason']

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
    created=client.post(package_route,json=body)
    assert created.status_code==201,created.text
    package=created.json()
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
    assert client.get(url).status_code==409

from hashlib import sha256
from io import BytesIO
import json
import os
import subprocess
from time import monotonic
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app import storage,worker
from app.main import app
from test_creative import creative
from test_delivery import delivery_fixture
from test_postgres import database
from test_production import series_fixture
from test_render_postgres import studio


def test_secure_storage_keys_and_local_request_limits(tmp_path):
    root=tmp_path/'storage'
    root.mkdir()
    for unsafe in ('../out','/outside','originals//clip.mp4','originals/clip.mp4:stream',
                   'originals/CON.txt','tmp/../data','originals/name.','originals\\..\\misc'):
        try:
            storage.resolve_key(unsafe,root)
        except ValueError:
            continue
        raise AssertionError(f'Accepted invalid key {unsafe!r}')
    sub=root/'valid'
    sub.mkdir()
    alias=root/'alias'
    if os.name=='nt':
        subprocess.run(['cmd.exe','/d','/c','mklink','/j',str(alias),str(sub)],check=True,
                       capture_output=True,timeout=15)
    else:
        alias.symlink_to(sub,target_is_directory=True)
    try:
        storage.resolve_key('alias/asset.mp4',root)
    except ValueError:
        pass
    else:
        raise AssertionError('A storage path traversed an internal filesystem link.')
    assert storage.resolve_key('one\\two.mp4',root)==root/'one'/'two.mp4'
    client=TestClient(app)
    rejected=client.post('/api/projects',headers={'sec-fetch-site':'cross-site'},json={'name':'blocked'})
    assert rejected.status_code==403 and len(rejected.headers['x-request-id'])==36
    oversized=client.post('/api/projects',headers={'content-length':str(13*1024**2)},json={'name':'blocked'})
    assert oversized.status_code==413
    assert oversized.headers['x-request-id']!=rejected.headers['x-request-id']


def test_full_three_episode_30_second_production_delivery(delivery_fixture,tmp_path,record_testsuite_property):
    studio,production,prep,timeline=delivery_fixture
    client,project,_,upload,_,task,_,_=studio
    source=tmp_path/'local-30s.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=24:duration=30',
        '-f','lavfi','-i','sine=frequency=510:sample_rate=48000:duration=30','-t','30','-c:v','libx264',
        '-threads','2','-preset','veryfast','-c:a','aac',str(source)],check=True,timeout=60)
    rights_asset=upload('三集自产测试.mp4',source.read_bytes())
    approved=prep(3,seconds=30)
    items=[timeline(approved,n,frames=720,linked=rights_asset,with_audio=False) for n in range(1,4)]
    root=f'/api/projects/{project}'
    page=client.get(root+'/tasks?offset=0&limit=2')
    assert page.status_code==200
    started=monotonic()
    created=client.post(production,json={'plan_version_id':approved,'timelines':items,'idempotency_key':'release-soak'})
    assert created.status_code==201,created.text
    for _ in range(6):
        assert worker.run_once()
    run=client.get('/api/production/runs/'+created.json()['id']).json()
    assert run['status']=='passed' and run['passed']==3,run
    metrics=client.get('/api/system/metrics')
    assert metrics.status_code==200,metrics.text
    counters=metrics.json()
    assert counters['database_revision']=='0017' and counters['observed_attempts']>=6 and counters['disk']['total']>0
    assert any(node['state']=='offline' for node in counters['workers'])
    assert all(not node['online'] for node in counters['workers'] if node['state']=='offline')
    assert len(client.get(root+'/tasks?limit=2').json())==2
    assert len(client.get(root+'/tasks?offset=2&limit=2').json())==2

    grant=client.post(f"/api/library/assets/{rights_asset['id']}/rights",json={'status':'approved','source_type':'owned',
        'holder':'自行生成的本地验收素材','evidence':'本次独立样本由 FFmpeg 现场生成；仅验收用',
        'commercial':True,'regions':['CN'],'platforms':['isolated-test'],'idempotency_key':'test-only'})
    assert grant.status_code==201,grant.text
    request=client.post(f'/api/delivery/projects/{project}/packages',json={'run_id':run['id'],'title':'三集 30 秒本机验收',
        'platform':'isolated-test','region':'CN','idempotency_key':'batch-archive'})
    assert request.status_code==201,request.text
    assert worker.run_once()
    zipped=task(request.json()['id'])
    assert zipped['status']=='succeeded',zipped['error']
    package=client.get(f"/api/delivery/packages/{zipped['id']}/file")
    assert package.status_code==200 and sha256(package.content).hexdigest()==zipped['output']['sha256']
    with ZipFile(BytesIO(package.content)) as archive:
        data=json.loads(archive.read('manifest.json'))
        assert len([item for item in data['files'] if item['path'].endswith('/video.mp4')])==3
        for n in range(1,4):
            quality=json.loads(archive.read(f'episode-{n:03d}/quality.json'))
            assert quality['technical']['duration_ms']==30_000
    record_testsuite_property('real_output_seconds',90)
    record_testsuite_property('elapsed_local_pipeline_seconds',round(monotonic()-started,3))
    record_testsuite_property('verified_archive_bytes',len(package.content))
    record_testsuite_property('logical_cpus',counters['logical_cpus'])

import hashlib
import subprocess

from app import worker
from test_postgres import database
from test_render_postgres import studio


def test_real_motion_candidates_cache_review_and_render(studio,tmp_path):
    client,project,_,upload,submit,task,resolve,_=studio
    picture=tmp_path/'owned.png'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=320x240:rate=24',
                    '-frames:v','1','-threads','1','-update','1',str(picture)],check=True,timeout=30)
    original=picture.read_bytes()
    asset=upload('自有图案.png',original)
    base=f'/api/generation/projects/{project}'
    path=base+'/still-motion'
    specs=[{'preset':'push_in','aspect':'square','frames':12},{'preset':'pan_right','aspect':'square','frames':12}]
    body={'asset_id':asset['id'],'candidates':specs,'idempotency_key':'multiple-candidates'}
    response=client.post(path,json=body)
    assert response.status_code==201,response.text
    first,second=response.json()
    assert client.post(path,json=body).json()==response.json()
    assert client.post(path,json={**body,'candidates':specs[:1]}).status_code==409
    select=f"/api/generation/candidates/{first['id']}/select"
    choice={'title':'已采纳的运镜','note':'人工对比候选后采纳第一条'}
    assert client.post(select,json=choice).status_code==409
    for result in (first,second):
        assert worker.run_once()
        assert task(result['id'])['status']=='succeeded',task(result['id'])['error']
    first,second=[task(result['id']) for result in (first,second)]
    assert first['output']['actual_external_cost_micros']==0
    assert first['output']['sha256']!=second['output']['sha256']
    first_video=resolve(first['output']['storage_key'])
    frames=subprocess.run(['ffmpeg','-v','error','-i',str(first_video),'-f','framemd5','-'],
                          check=True,capture_output=True,timeout=30,text=True).stdout
    digests=[line.split(',')[-1].strip() for line in frames.splitlines() if line and not line.startswith('#')]
    assert len(digests)==12 and len(set(digests))>3
    served=client.get(f"/api/generation/candidates/{first['id']}/video",headers={'Range':'bytes=0-99'})
    assert served.status_code==206 and len(served.content)==100

    cache=client.post(path,json={**body,'idempotency_key':'cache-candidate','candidates':specs[:1]}).json()[0]
    assert worker.run_once()
    assert task(cache['id'])['output']['reused_from_task_id']==first['id']
    chosen=client.post(select,json=choice)
    assert chosen.status_code==201,chosen.text
    selected=chosen.json()
    assert selected['authorization']==asset['authorization']
    assert selected['media_info']['generated_from_asset']==asset['id']
    assert client.post(select,json=choice).json()['id']==selected['id']
    assert client.post(select,json={**choice,'title':'其他名字'}).status_code==409
    render=submit(params={'duration':.4},aid=selected['id'])
    assert worker.run_once()
    assert task(render['id'])['status']=='succeeded',task(render['id'])['error']
    assert hashlib.sha256(resolve(asset['storage_key']).read_bytes()).hexdigest()==asset['sha256']
    modes=client.get('/api/generation/capabilities').json()['modes']
    assert [mode['id'] for mode in modes if mode['available']]==['local_still_motion']

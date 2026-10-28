"""Real local batch/queue/worker/history acceptance; generates no paid calls."""
import json
import subprocess
import time
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[1]
fixture=root/'data/fixtures/p3-owned.mp4'
fixture.parent.mkdir(parents=True,exist_ok=True)
if not fixture.exists():
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=480x270:rate=24','-t','2','-c:v','mpeg4',str(fixture)],check=True,timeout=30)
with httpx.Client(base_url='http://127.0.0.1:15173',timeout=30) as client:
    client.get('/api/health').raise_for_status()
    original=client.get('/api/queue').json()
    if original['paused']:raise SystemExit('Queue already paused by user; leave it unchanged and resume manually before smoke test.')
    existing=client.get('/api/projects').json()
    for project in existing:
        if any(t['status'] in ('queued','running') for t in client.get(f"/api/projects/{project['id']}/tasks").json()):
            raise SystemExit('Other queued/running work exists; smoke test will not pause user work.')
    p=client.post('/api/projects',json={'name':'P3 批量可靠性实机验收','description':'自行生成测试素材；原子批次、队列暂停、心跳和尝试日志验收。'});p.raise_for_status()
    project=p.json()['id'];ids=[]
    for index in range(2):
        a=client.post(f'/api/projects/{project}/assets',files={'file':(f'P3-owned-{index}.mp4',fixture.read_bytes())},data={'authorization':'FFmpeg 自行生成，仅用于真实处理验收'})
        a.raise_for_status();ids.append(a.json()['id'])
    try:
        client.post('/api/queue',json={'paused':True}).raise_for_status()
        body={'asset_ids':ids,'parameters':{'duration':1,'aspect':'1:1'},'idempotency_key':'p3-acceptance-batch'}
        r=client.post(f'/api/projects/{project}/batches',json=body);r.raise_for_status()
        duplicate=client.post(f'/api/projects/{project}/batches',json=body);duplicate.raise_for_status()
        assert r.json()['batch']['id']==duplicate.json()['batch']['id']
        time.sleep(1.2)
        queued=client.get(f'/api/projects/{project}/tasks').json()
        assert len(queued)==2 and all(t['status']=='queued' for t in queued)
    finally:client.post('/api/queue',json={'paused':False}).raise_for_status()
    deadline=time.monotonic()+90
    while time.monotonic()<deadline:
        tasks=client.get(f'/api/projects/{project}/tasks').json()
        if all(t['status'] in ('succeeded','failed','cancelled') for t in tasks):break
        time.sleep(0.3)
    assert all(t['status']=='succeeded' for t in tasks),tasks
    histories={}
    for t in tasks:
        history=client.get(f"/api/tasks/{t['id']}/attempts");history.raise_for_status()
        histories[t['id']]=history.json()
        assert len(history.json())==1 and history.json()[0]['status']=='succeeded'
        path=root/'data'/t['output']['storage_key'];assert path.is_file()
        subprocess.run(['ffprobe','-v','error',str(path)],check=True,capture_output=True)
        assert client.get(f"/api/tasks/{t['id']}/output",headers={'range':'bytes=0-99'}).status_code==206
    queue=client.get('/api/queue').json()
    assert any(w['online'] for w in queue['workers'])
    summary=client.get(f'/api/projects/{project}/production-summary').json()
    assert summary['attempts']==2 and summary['recorded_cents']==0 and summary['observed_processing_seconds']>0
    evidence={'project_id':project,'batch_id':r.json()['batch']['id'],'tasks':tasks,'attempts':histories,'queue':queue,'summary':summary,'pause_verified':True,'duplicate_batch_deduplicated':True}
    (root/'docs/p3-http-acceptance.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print('P3 HTTP: atomic batch x2; pause/resume; live heartbeat; real outputs; attempt history; observed time and uncharged API ledger verified.')

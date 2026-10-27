"""Live HTTP acceptance. Creates clearly labelled owned test media and outputs."""
import json
import subprocess
import time
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[1]
fixture=root/'data/fixtures/p2-owned.mp4'
fixture.parent.mkdir(parents=True,exist_ok=True)
if not fixture.exists():
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=640x360:rate=24','-f','lavfi','-i','sine=frequency=440','-t','3','-c:v','mpeg4','-c:a','aac',str(fixture)],check=True,timeout=30)
with httpx.Client(base_url='http://127.0.0.1:15173',timeout=30) as client:
    health=client.get('/api/health');health.raise_for_status()
    p=client.post('/api/projects',json={'name':'P2 真实剪辑验收','description':'本项目自行生成测试视频与字幕，仅用于验收，不是生产交付内容。'});p.raise_for_status()
    project=p.json()['id']
    def upload(name,content):
        result=client.post(f'/api/projects/{project}/assets',files={'file':(name,content)},data={'authorization':'项目自行生成的测试素材，无外部版权内容'})
        result.raise_for_status();return result.json()
    asset=upload('P2-owned.mp4',fixture.read_bytes())
    subtitle=upload('验收字幕.srt','1\n00:00:00,000 --> 00:00:01,500\nP2 real subtitle / 漫剧工厂验收\n'.encode())
    ids=[]
    for index,parameters in enumerate([
        {'start':0.5,'duration':1.5,'aspect':'9:16','resolution':'720','strategy':'pad','subtitle_asset_id':subtitle['id']},
        {'start':0,'end':2,'aspect':'1:1','strategy':'crop','audio_mode':'mute'},
    ]):
        body={'asset_id':asset['id'],'kind':'render','parameters':parameters,'idempotency_key':f'acceptance-{index}'}
        response=client.post(f'/api/projects/{project}/tasks',json=body);response.raise_for_status()
        duplicate=client.post(f'/api/projects/{project}/tasks',json=body);duplicate.raise_for_status()
        assert response.json()['id']==duplicate.json()['id']
        ids.append(response.json()['id'])
    observed=[]
    deadline=time.monotonic()+120
    while time.monotonic()<deadline:
        tasks=client.get(f'/api/projects/{project}/tasks').json()
        observed.append([{'id':t['id'],'status':t['status'],'stage':t['stage'],'progress':t['progress']} for t in tasks])
        if all(t['status'] in ('succeeded','failed','cancelled') for t in tasks):break
        time.sleep(0.25)
    assert len(tasks)==2 and all(t['status']=='succeeded' for t in tasks),tasks
    for task in tasks:
        path=root/'data'/task['output']['storage_key']
        assert path.is_file()
        result=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)],capture_output=True,check=True)
        assert any(s['codec_type']=='video' for s in json.loads(result.stdout)['streams'])
        preview=client.get(f"/api/tasks/{task['id']}/output",headers={'range':'bytes=0-99'})
        assert preview.status_code==206
        download=client.get(f"/api/tasks/{task['id']}/output?download=true")
        assert download.status_code==200 and 'attachment' in download.headers['content-disposition']
    evidence={'project_id':project,'health':health.json(),'tasks':tasks,'observed':observed}
    (root/'docs/p2-http-acceptance.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print('P2 live HTTP acceptance: two real rendered outputs; preview 206; downloads 200; duplicate submission deduplicated.')

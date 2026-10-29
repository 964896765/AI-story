"""Real creative version -> pinned video batch acceptance. No AI requests."""
import json
import subprocess
import time
from pathlib import Path
import httpx

root=Path(__file__).resolve().parents[1]
fixture=root/'data/fixtures/p4-owned.mp4';fixture.parent.mkdir(parents=True,exist_ok=True)
if not fixture.exists():subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=480x270:rate=24','-t','2','-c:v','mpeg4',str(fixture)],check=True,timeout=30)
with httpx.Client(base_url='http://127.0.0.1:15173',timeout=30) as client:
    client.get('/api/health').raise_for_status()
    if client.get('/api/queue').json()['paused']:raise SystemExit('Queue paused by user; leave it unchanged.')
    response=client.post('/api/projects',json={'name':'P4 创作版本与真实生产验收','description':'自行编写的中文测试内容与FFmpeg自有测试视频；非AI生成，不是生产交付。'});response.raise_for_status();project=response.json()['id']
    def post(path,body):
        response=client.post(path,json=body);response.raise_for_status();return response.json()
    def upload(name,content):
        response=client.post(f'/api/projects/{project}/assets',files={'file':(name,content)},data={'authorization':'项目自行编写/生成的测试素材，已授权本地使用'})
        response.raise_for_status();return response.json()
    def entity(kind,title,content,key):return post(f'/api/projects/{project}/story/entities',{'kind':kind,'title':title,'content':content,'idempotency_key':key})
    text='第一章：归城\n\n林舟走进旧城门。\n\n守门人：你终于回来了。\n\n林舟：这封信，只能交给你。'
    source=upload('原创验收小说.txt',text.encode());video=upload('P4-owned.mp4',fixture.read_bytes())
    novel=entity('novel','归城 · 自编验收文本',{'text':text,'authorization':'本项目自行编写','source_asset_id':source['id']},'novel')
    char=entity('character','林舟',{'description':'送信人','appearance':'黑发，灰色外套','voice':{'description':'沉稳、语速平缓；仅配置未生成'}},'char')
    guard=entity('character','守门人',{'description':'旧城守卫'},'guard')
    scene=entity('scene','旧城门',{'description':'雨后的旧城门','location':'城门内侧','time_of_day':'黎明'},'scene')
    entity('relationship','归城人物关系',{'relationships':[{'from_character_version_id':char['version_id'],'to_character_version_id':guard['version_id'],'description':'相识多年的旧友'}]},'relation')
    script=entity('script','归城第一场',{'body':text,'source_version_id':novel['version_id'],'character_version_ids':[char['version_id'],guard['version_id']],'scene_version_ids':[scene['version_id']]},'script')
    episodes=post(f'/api/projects/{project}/story/derive',{'source_version_id':script['version_id'],'operation':'split_episodes','unit_chars':100,'idempotency_key':'episodes'})
    board=entity('storyboard','归城分镜计划',{'source_version_id':script['version_id'],'shots':[{'number':1,'description':'林舟从旧城门走入','dialogue':'这封信，只能交给你。','planned_duration':3,'scene_version_id':scene['version_id'],'character_version_ids':[char['version_id'],guard['version_id']]}]},'board')
    updated=post(f"/api/story/entities/{char['id']}/versions",{'expected_version':1,'title':'林舟','content':{**char['content'],'appearance':'黑发，蓝色外套'},'idempotency_key':'char-v2'})
    assert updated['version']==2
    restored=post(f"/api/story/entities/{char['id']}/restore",{'expected_version':2,'version':1,'idempotency_key':'char-restore'})
    assert restored['version']==3
    plan=entity('generation_plan','后续文本模型输入计划',{'capability':'text','prompt':'仅准备，不调用模型。后续人工授权后再润色对白。','input_version_ids':[script['version_id'],board['version_id']]},'plan')
    estimate=client.get(f"/api/story/entities/{plan['id']}/model-estimate").json()
    assert estimate['available'] is False and estimate['estimated_cost_minor'] is None
    body={'asset_ids':[video['id']],'parameters':{'duration':1,'aspect':'1:1'},'story_version_id':board['version_id'],'idempotency_key':'creative-production'}
    batch=post(f'/api/projects/{project}/batches',body)
    assert post(f'/api/projects/{project}/batches',body)['batch']['id']==batch['batch']['id']
    task_id=batch['tasks'][0]['id'];deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        task=next(t for t in client.get(f'/api/projects/{project}/tasks').json() if t['id']==task_id)
        if task['status'] in ('succeeded','failed','cancelled'):break
        time.sleep(0.25)
    assert task['status']=='succeeded' and task['story_version_id']==board['version_id'],task
    output=root/'data'/task['output']['storage_key'];assert output.is_file()
    subprocess.run(['ffprobe','-v','error',str(output)],check=True,capture_output=True)
    assert client.get(f'/api/tasks/{task_id}/output',headers={'range':'bytes=0-99'}).status_code==206
    exported=client.get(f'/api/projects/{project}/story/export');exported.raise_for_status();data=exported.json()
    version_ids={v['version_id'] for v in data['versions']}
    assert char['version_id'] in version_ids and restored['version_id'] in version_ids
    evidence={'project_id':project,'novel_id':novel['id'],'character_id':char['id'],'script_id':script['id'],'script_version_id':script['version_id'],'storyboard_id':board['id'],'storyboard_version_id':board['version_id'],'plan_id':plan['id'],'task':task,'model_estimate':estimate,'export_version_ids':sorted(version_ids),'rule_episodes_ai_generated':episodes['ai_generated']}
    (root/'docs/p4-http-acceptance.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print('P4 HTTP: creative assets, pinned refs, v1/v2/restore-v3, rule drafts, unknown model cost and real version-linked render passed.')

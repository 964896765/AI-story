import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest
from sqlalchemy import select,delete,func
from app.models import StoryEntity,StoryVersion,StoryReference,StoryOperation,Project,Task
from app import worker
from app.model_adapters import adapter_for,ModelRequest,ModelsDisabled
from app.story_schemas import CONTENT_MODELS
from app.creative import split_units
from test_postgres import database
from test_render_postgres import studio

@pytest.fixture
def creative(studio):
    client,project,asset,upload,submit,task,resolve,factory=studio
    def create(kind,title,content,key=None):
        response=client.post(f'/api/projects/{project}/story/entities',json={'kind':kind,'title':title,'content':content,'idempotency_key':key or str(uuid4())})
        assert response.status_code==201,response.text
        return response.json()
    yield studio,create
    # Project fixtures delete source files after task records. Release creative refs first.
    with factory.begin() as db:
        db.execute(Task.__table__.update().where(Task.project_id==project).values(story_version_id=None))
        db.execute(delete(StoryEntity).where(StoryEntity.project_id==project))

def test_disabled_adapter_and_typed_content():
    request=ModelRequest('test','key','text','未执行',())
    assert adapter_for().estimate(request)['estimated_cost_minor'] is None
    with pytest.raises(ModelsDisabled):adapter_for().invoke(request)
    with pytest.raises(ModelsDisabled):adapter_for('unapproved-cloud')
    with pytest.raises(ValueError):CONTENT_MODELS['character'].model_validate({'voice':{'provider':'paid'}})
    with pytest.raises(ValueError):CONTENT_MODELS['storyboard'].model_validate({'source_version_id':'x','shots':[{'number':1,'description':'a'},{'number':1,'description':'b'}]})
    assert ''.join(split_units('甲'*120+'\n\n'+'乙'*120,100)).replace('\n','')=='甲'*120+'乙'*120

def test_version_history_optimistic_conflict_and_restore(creative):
    studio,create=creative;client,project,asset,upload,submit,task,resolve,factory=studio
    original=create('character','林舟',{'appearance':'黑发，灰色外套','voice':{'description':'沉稳男声'}},'character-one')
    assert create('character','林舟',original['content'],'character-one')['version_id']==original['version_id']
    base={'expected_version':1,'title':'林舟','content':{**original['content'],'appearance':'黑发，蓝色外套'},'idempotency_key':'edit-once'}
    updated=client.post(f"/api/story/entities/{original['id']}/versions",json=base)
    assert updated.status_code==201 and updated.json()['version']==2
    assert client.post(f"/api/story/entities/{original['id']}/versions",json=base).json()['version_id']==updated.json()['version_id']
    conflict=client.post(f"/api/story/entities/{original['id']}/versions",json={**base,'idempotency_key':'stale'})
    assert conflict.status_code==409
    restored=client.post(f"/api/story/entities/{original['id']}/restore",json={'expected_version':2,'version':1,'idempotency_key':'restore-one'})
    assert restored.status_code==201 and restored.json()['version']==3
    history=client.get(f"/api/story/entities/{original['id']}/versions").json()
    assert [x['version'] for x in history]==[3,2,1]
    assert history[-1]['content'] is None
    assert client.get(f"/api/story/versions/{history[-1]['version_id']}").json()['content']['appearance']=='黑发，灰色外套'
    assert client.get(f"/api/story/versions/{history[1]['version_id']}").json()['content']['appearance']=='黑发，蓝色外套'
    diff=client.get(f"/api/story/entities/{original['id']}/compare?left=1&right=2").json()
    assert '灰色外套' in diff['diff'] and '蓝色外套' in diff['diff'] and not diff['truncated']
    repeat=client.post(f"/api/story/entities/{original['id']}/restore",json={'expected_version':2,'version':1,'idempotency_key':'restore-one'})
    assert repeat.json()['version_id']==restored.json()['version_id']

def test_concurrent_edit_only_one_wins(creative):
    studio,create=creative;client,project,*_=studio
    entity=create('scene','旧街',{'description':'雨夜'})
    def save(index):
        return client.post(f"/api/story/entities/{entity['id']}/versions",json={'expected_version':1,'title':'旧街','content':{'description':str(index)},'idempotency_key':str(uuid4())})
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,range(2)))
    assert sorted(r.status_code for r in results)==[201,409]

def test_pinned_refs_relationship_and_export_include_history(creative):
    studio,create=creative;client,project,asset,upload,submit,task,resolve,factory=studio
    a=create('character','阿青',{'description':'信使'})
    b=create('character','阿岚',{'description':'守门人'})
    scene=create('scene','城门',{'description':'黎明城门'})
    script=create('script','开场',{'body':'阿青递出信件。','character_version_ids':[a['version_id'],b['version_id']],'scene_version_ids':[scene['version_id']]})
    create('relationship','人物关系',{'relationships':[{'from_character_version_id':a['version_id'],'to_character_version_id':b['version_id'],'description':'多年未见的旧友'}]})
    client.post(f"/api/story/entities/{a['id']}/versions",json={'expected_version':1,'title':'阿青','content':{'description':'新的设定'},'idempotency_key':'v2'})
    exported=client.get(f'/api/projects/{project}/story/export')
    assert exported.status_code==200 and 'attachment' in exported.headers['content-disposition']
    data=exported.json();versions={v['version_id']:v for v in data['versions']}
    assert versions[script['version_id']]['content']['character_version_ids'][0]==a['version_id']
    assert versions[a['version_id']]['content']['description']=='信使'
    assert len([v for v in data['versions'] if v['id']==a['id']])==2

def test_cross_project_and_wrong_type_reference_rejected(creative):
    studio,create=creative;client,project,asset,upload,submit,task,resolve,factory=studio
    other=client.post('/api/projects',json={'name':'隔离项目'}).json()['id']
    try:
        foreign=client.post(f'/api/projects/{other}/story/entities',json={'kind':'character','title':'他人项目角色','content':{},'idempotency_key':'foreign'}).json()
        response=client.post(f'/api/projects/{project}/story/entities',json={'kind':'script','title':'错误引用','content':{'body':'test','character_version_ids':[foreign['version_id']]},'idempotency_key':'invalid-cross'})
        assert response.status_code==422
        wrong=create('scene','场景',{})
        response=client.post(f'/api/projects/{project}/story/entities',json={'kind':'script','title':'错误类型','content':{'body':'test','character_version_ids':[wrong['version_id']]},'idempotency_key':'invalid-kind'})
        assert response.status_code==422
    finally:
        with factory.begin() as db:db.execute(delete(Project).where(Project.id==other))

def test_rule_drafts_are_real_persisted_and_not_ai(creative):
    studio,create=creative;client,project,asset,upload,submit,task,resolve,factory=studio
    text='林舟走进城门。\n\n守门人抬头问：你是谁？\n\n林舟：我是送信的人。'
    novel=create('novel','原创测试小说',{'text':text,'authorization':'测试自行编写'})
    def derive(source,operation,key):
        response=client.post(f'/api/projects/{project}/story/derive',json={'source_version_id':source,'operation':operation,'unit_chars':100,'idempotency_key':key})
        assert response.status_code==201,response.text
        assert response.json()['ai_generated'] is False
        return response.json()['items']
    script=derive(novel['version_id'],'structure_script','to-script')[0]
    assert script['content']['body']==text
    assert derive(novel['version_id'],'structure_script','to-script')[0]['version_id']==script['version_id']
    episodes=derive(script['version_id'],'split_episodes','episodes')
    assert episodes and episodes[0]['kind']=='episode'
    board=derive(episodes[0]['version_id'],'split_shots','shots')[0]
    assert board['content']['shots'][0]['description']
    assert board['provenance']['method']=='local_rules'
    with factory() as db:assert db.scalar(select(func.count()).select_from(StoryOperation).where(StoryOperation.project_id==project))==3

def test_text_import_reference_and_model_unknown_cost(creative):
    studio,create=creative;client,project,asset,upload,submit,task,resolve,factory=studio
    text='原创中文长文本\n第一章：回家。'
    source=upload('novel.txt',text.encode('utf-8'))
    novel=create('novel','导入小说',{'text':text,'authorization':'自行编写','source_asset_id':source['id']})
    plan=create('generation_plan','模型输入计划',{'capability':'text','prompt':'后续授权后再改写','input_version_ids':[novel['version_id']]})
    estimate=client.get(f"/api/story/entities/{plan['id']}/model-estimate").json()
    assert estimate['available'] is False and estimate['estimated_cost_minor'] is None
    assert client.get('/api/model-capabilities').json()['enabled'] is False
    invalid=client.post(f'/api/projects/{project}/assets',files={'file':('invalid.txt',b'\xff\xfe')},data={'authorization':'测试'})
    assert invalid.status_code==422

def test_real_render_pins_story_version_and_batch_retry_compatibility(creative):
    studio,create=creative;client,project,asset,upload,submit,task,resolve,factory=studio
    script=create('script','已审核剧本',{'body':'人物从门口走过。'})
    request={'asset_ids':[asset['id']],'parameters':{'duration':1},'idempotency_key':'production-story','story_version_id':script['version_id']}
    response=client.post(f'/api/projects/{project}/batches',json=request)
    assert response.status_code==201,response.text
    tid=response.json()['tasks'][0]['id']
    client.post(f"/api/story/entities/{script['id']}/versions",json={'expected_version':1,'title':'已审核剧本','content':{'body':'新剧本内容'},'idempotency_key':'next'})
    worker.run_once();result=task(tid)
    assert result['status']=='succeeded' and result['story_version_id']==script['version_id']
    assert resolve(result['output']['storage_key']).is_file()
    assert client.post(f'/api/projects/{project}/batches',json=request).json()['tasks'][0]['id']==tid
    assert client.post(f'/api/projects/{project}/batches',json={**request,'story_version_id':None}).status_code==409
    # P3 request JSON omitted story_version_id; omission still hashes the same way.
    legacy={**request,'idempotency_key':'p3-format'};legacy.pop('story_version_id')
    first=client.post(f'/api/projects/{project}/batches',json=legacy)
    assert first.status_code==201
    assert client.post(f'/api/projects/{project}/batches',json=legacy).json()['batch']['id']==first.json()['batch']['id']

def test_real_reference_image_and_immutable_source(creative,tmp_path):
    import subprocess
    studio,create=creative;client,project,asset,upload,submit,task,resolve,factory=studio
    path=tmp_path/'reference.png'
    subprocess.run(['ffmpeg','-v','error','-i',str(resolve(asset['storage_key'])),'-frames:v','1',str(path)],check=True,timeout=30)
    image=upload('角色参考.png',path.read_bytes())
    char=create('character','参考角色',{'reference_asset_ids':[image['id']]})
    assert client.get(f"/api/assets/{image['id']}/media").headers['x-content-type-options']=='nosniff'
    exported=client.get(f'/api/projects/{project}/story/export').json()
    assert image['sha256']==exported['assets'][0]['sha256']
    assert resolve(image['storage_key']).read_bytes()==path.read_bytes()
    invalid=client.post(f'/api/projects/{project}/assets',files={'file':('invalid.png',b'not an image')},data={'authorization':'测试无效输入'})
    assert invalid.status_code==422

def test_large_text_listing_is_metadata_only_and_export_is_bounded(creative,monkeypatch):
    from app import creative as module
    studio,create=creative;client,project,*_=studio
    entity=create('novel','长文本',{'text':'长文本内容。'*1000,'authorization':'自行编写'})
    listed=client.get(f'/api/projects/{project}/story/entities').json()
    assert listed['total']==1 and listed['items'][0]['content'] is None
    assert client.get(f"/api/story/versions/{entity['version_id']}").json()['content']['text']
    monkeypatch.setattr(module,'MAX_EXPORT_BYTES',1024)
    assert client.get(f'/api/projects/{project}/story/export').status_code==422
    assert client.get(f'/api/projects/{project}/story/entities?offset=-1').status_code==422

def test_derive_limit_rolls_back_without_partial_assets(creative):
    studio,create=creative;client,project,asset,upload,submit,task,resolve,factory=studio
    script=create('script','大文本',{'body':'测试'*3000})
    response=client.post(f'/api/projects/{project}/story/derive',json={'source_version_id':script['version_id'],'operation':'split_episodes','unit_chars':100,'idempotency_key':'too-many'})
    assert response.status_code==422
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(StoryOperation).where(StoryOperation.project_id==project))==0
        assert db.scalar(select(func.count()).select_from(StoryEntity).where(StoryEntity.project_id==project))==1

def test_creative_data_downgrade_is_refused(creative):
    import subprocess,sys,os
    studio,create=creative;client,project,asset,upload,submit,task,resolve,factory=studio
    saved=create('novel','不可丢失的文本',{'text':'这是历史记录。','authorization':'自行编写'})
    result=subprocess.run([sys.executable,'-m','alembic','downgrade','0004'],env={**os.environ,'DATABASE_URL':os.environ['TEST_DATABASE_URL']},capture_output=True,text=True)
    assert result.returncode!=0 and 'P4 creative records exist' in result.stderr
    assert client.get(f"/api/story/versions/{saved['version_id']}").status_code==200

def test_concurrent_entity_create_reuses_one_version(creative):
    studio,create=creative;client,project,asset,upload,submit,task,resolve,factory=studio
    payload={'kind':'scene','title':'并发创建场景','content':{'description':'相同内容'},'idempotency_key':'same-create'}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:client.post(f'/api/projects/{project}/story/entities',json=payload),range(2)))
    assert all(r.status_code==201 for r in results)
    assert results[0].json()['version_id']==results[1].json()['version_id']

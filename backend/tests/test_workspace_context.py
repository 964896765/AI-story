from sqlalchemy import delete

from app.models import Project
from test_creative import creative
from test_postgres import database
from test_render_postgres import studio


def test_workspace_location_resolves_pinned_versions_and_rejects_conflicts(creative):
    fixture, create = creative
    client, project, *_, factory = fixture
    specs = f'/api/projects/{project}/production-specs'
    settings = {'episode_count':2,'episode_duration_ms':1500,'style':'线稿','profile':'square',
                'width':720,'height':720,'fps':24,'platform':'local-test','region':'CN','budget_cents':0}
    spec = client.post(specs,json={'expected_version':0,'idempotency_key':'spec','settings':settings}).json()
    script = create('script','原创剧本',{'body':'灯塔值守。'})
    episodes = []
    boards = []
    for number in (1,2):
        episode = create('episode',f'分集 {number}',{'number':number,'body':'灯塔值守。','source_version_id':script['version_id']})
        board = create('storyboard',f'分镜 {number}',{'source_version_id':episode['version_id'],
            'production_spec_version_id':spec['id'],'shots':[{'number':1,'shot_id':f'ep{number}-shot',
                                                           'description':'灯塔画面','planned_duration':1.5}]})
        episodes.append({'episode_version_id':episode['version_id'],'storyboard_version_id':board['version_id'],
                         'target_duration_ms':1500})
        boards.append(board)
    draft = create('story_bible','固定计划',{'script_version_id':script['version_id'],'theme':'守望','world':'港口',
                                         'production_spec_version_id':spec['id'],'episodes':episodes})
    approve = f'/api/series/entities/{draft["id"]}/approve'
    decision = client.post(approve,json={'expected_version':1,'note':'验收固定计划','idempotency_key':'approval'})
    assert decision.status_code==201,decision.text
    plan = decision.json()['version_id']
    new = client.post(specs,json={'expected_version':1,'idempotency_key':'new','settings':{**settings,'style':'水彩'}})
    assert new.status_code==201,new.text
    route = f'/api/projects/{project}/workspace-context'
    assert client.get(route,params={'plan':draft['version_id']}).status_code==404
    assert client.get(route,params={'plan':plan,'shot':'missing'}).status_code==404
    assert client.get(route,params={'plan':plan,'episode':1,'shot':'ep2-shot'}).status_code==409
    matched = client.get(route,params={'plan':plan,'shot':'ep2-shot'})
    assert matched.status_code==200,matched.text
    result = matched.json()
    assert result['plan']['id']==plan and result['shot']=='ep2-shot'
    assert result['production_spec']['id']==spec['id'] and result['production_spec']['sha256']==spec['sha256']
    assert result['episode']['number']==2 and result['episode']['storyboard_version_id']==boards[1]['version_id']
    assert result['run_id'] is None
    other = client.post('/api/projects',json={'name':'制作定位隔离'}).json()['id']
    try:
        assert client.get(f'/api/projects/{other}/workspace-context',params={'plan':plan}).status_code==404
    finally:
        with factory.begin() as db:
            db.execute(delete(Project).where(Project.id==other))

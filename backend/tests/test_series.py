from copy import deepcopy

from test_creative import creative
from test_postgres import database
from test_render_postgres import studio


def test_three_episode_continuity_and_versioned_review(creative):
    studio, create = creative
    client, project, *_ = studio
    main = create('script','塔灯约定',{'body':'阿青要在灯塔熄灭前归还旧信。'})
    actor = create('character','阿青',{'appearance':'灰围巾，绿风衣'})
    dock = create('scene','旧码头',{'location':'海湾东侧'})
    actor_id, dock_id = actor['version_id'],dock['version_id']
    boundary = {'character_version_id':actor_id,'scene_version_id':dock_id,
                'wardrobe':'绿风衣','prop_state':'信在左手','condition':'没有受伤'}
    storyline = [
        ('收到信','阿青走到灯塔，拆开旧信。'),
        ('穿过港口','阿青绕过码头警戒线。'),
        ('交还信','阿青把信递给守塔人。'),
    ]
    entries = []
    boards = []
    for number,(name,body) in enumerate(storyline,1):
        episode=create('episode',name,{'body':body,'number':number,'source_version_id':main['version_id'],
                                      'character_version_ids':[actor_id],'scene_version_ids':[dock_id]})
        board=create('storyboard','分镜 '+name,{'source_version_id':episode['version_id'],'shots':[
            {'number':1,'shot_id':f'lighthouse-{number}-opening','description':body,'planned_duration':3,
             'framing':'medium','character_version_ids':[actor_id],'scene_version_id':dock_id},
            {'number':2,'shot_id':f'lighthouse-{number}-close','description':'看向灯塔',
             'planned_duration':3,'dialogue':'我会按约定来。','speaker_version_id':actor_id,
             'dialogue_ms':1300,'character_version_ids':[actor_id],'scene_version_id':dock_id}
        ]})
        boards.append(board)
        entries.append({'episode_version_id':episode['version_id'],'storyboard_version_id':board['version_id'],
                      'target_duration_ms':6000,'opener':[deepcopy(boundary)],'closer':[deepcopy(boundary)]})
    entries[1]['opener'][0]['prop_state']='信在右手'
    entries[1]['target_duration_ms']=5000
    payload={'script_version_id':main['version_id'],'theme':'信守约定','world':'低科技海港',
             'episodes':entries,'threads':[{'label':'旧信','setup_episode':1,'payoff_episode':3}]}
    bible=create('story_bible','塔灯故事圣经',payload)
    doc=client.get(f"/api/series/versions/{bible['version_id']}/continuity").json()
    assert {item['code'] for item in doc['issues']}=={'boundary_change','duration_mismatch'}
    assert not doc['ready_for_review']
    approve_path=f"/api/series/entities/{bible['id']}/approve"
    approval={'expected_version':1,'note':'人工同意进入本地制作。','idempotency_key':'approve'}
    assert client.post(approve_path,json=approval).status_code==422

    entries[1]['target_duration_ms']=6000
    entries[1]['bridge_note']='上集结束后把信换到右手，接上一集画面。'
    version_path=f"/api/story/entities/{bible['id']}/versions"
    update=client.post(version_path,json={'title':bible['title'],'content':payload,
                                      'expected_version':1,'idempotency_key':'correct'})
    assert update.status_code==201,update.text
    draft=update.json()
    updated_report=client.get(f"/api/series/versions/{draft['version_id']}/continuity").json()
    assert updated_report['ready_for_review']
    assert [item['severity'] for item in updated_report['issues']]==['warning']
    assert client.post(approve_path,json=approval).status_code==409
    approval['expected_version']=2
    result=client.post(approve_path,json=approval)
    assert result.status_code==201,result.text
    approved=result.json()
    assert client.post(approve_path,json=approval).json()['version_id']==approved['version_id']
    assert approved['provenance']['reviewed_version_id']==draft['version_id']
    final=client.get(f"/api/series/versions/{approved['version_id']}/continuity").json()
    assert final['approved'] and len(final['episodes'])==3
    assert final['episodes'][0]['shots'][1]['start_ms']==3000
    assert final['episodes'][0]['shots'][1]['shot_id']=='lighthouse-1-close'

    changed=client.post(f"/api/story/entities/{boards[0]['id']}/versions",json={
        'title':'另一版分镜','expected_version':1,'idempotency_key':'board-v2',
        'content':{**boards[0]['content'],'shots':list(reversed(boards[0]['content']['shots']))},
    })
    assert changed.status_code==201,changed.text
    assert client.get(f"/api/series/versions/{approved['version_id']}/continuity").json()==final
    items=client.get(f'/api/projects/{project}/story/entities?kind=story_bible').json()['items']
    assert [item['version_id'] for item in items]==[approved['version_id']]


def test_advanced_shot_checks_preserve_legacy_payload(creative):
    studio,create=creative
    client,project,*_=studio
    script=create('script','片段',{'body':'只有一行。'})
    path=f'/api/projects/{project}/story/entities'
    basic={'source_version_id':script['version_id'],'shots':[{'number':1,'description':'读信'}]}
    request={'title':'最小历史分镜','kind':'storyboard','content':basic,'idempotency_key':'minimal-board'}
    created=client.post(path,json=request)
    assert created.status_code==201,created.text
    assert set(created.json()['content']['shots'][0])=={
        'number','description','dialogue','planned_duration','scene_version_id','character_version_ids'
    }
    assert client.post(path,json=request).json()['version_id']==created.json()['version_id']
    bad=deepcopy(request)
    bad['idempotency_key']='long-voice'
    bad['content']['shots'][0]['dialogue_ms']=3100
    assert client.post(path,json=bad).status_code==422

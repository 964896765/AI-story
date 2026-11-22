from copy import deepcopy
import subprocess

from app import worker
from test_creative import creative
from test_postgres import database
from test_render_postgres import studio


def test_guardian_contracts_and_continuity(creative, tmp_path):
    studio, create = creative
    client, project, _, upload, _, task_status, resolve, _ = studio
    artwork = tmp_path/'ref.png'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=96x96',
                    '-frames:v','1','-threads','1',str(artwork)],check=True,timeout=15)
    image = upload('原创角色-reference.png',artwork.read_bytes())
    stray = upload('不在镜头合同.png',artwork.read_bytes())
    novel = create('novel','灯塔小说',{'text':'阿青把信带到灯塔。','authorization':'本测试原创'})
    script = create('script','灯塔剧本',{'body':'阿青在灯塔熄灭前交信。','source_version_id':novel['version_id']})
    identity = {'traits':'灰围巾','wardrobes':{'green':'绿风衣'},'local_voice':'固定音色'}
    actor_a = create('character','阿青',{'identity':identity,'reference_asset_ids':[image['id']]})
    actor_b = create('character','守塔人',{'identity':{**identity,'traits':'宽帽檐'},'reference_asset_ids':[image['id']]})
    scene_a = create('scene','灯塔外',{'description':'海岸高台'})
    scene_b = create('scene','灯塔内',{'description':'灯室'})
    actor_ids = [actor_a['version_id'],actor_b['version_id']]
    scene_ids = [scene_a['version_id'],scene_b['version_id']]
    canon = {'facts':{'promise':'日落前交信'},'props':{'letter':'原来的纸信'},'character_version_ids':actor_ids,
             'scene_version_ids':scene_ids,'style':{'description':'低饱和手绘','reference_asset_ids':[image['id']]}}
    plans, boards, clean_shots = [], [], []
    for number, scene_id in enumerate(scene_ids,1):
        episode = create('episode',f'灯塔 {number}',{'number':number,'body':'信一直在左手。','source_version_id':script['version_id']})
        states = [{'character_version_id':actor,'wardrobe_id':'green','left_hand':'letter' if index==0 else None,
                   'action':'站定','position':'廊道入口'} for index,actor in enumerate(actor_ids)]
        shots = [{'number':index,'shot_id':f'ep{number}-shot{index}','description':'两人等待日落','planned_duration':1,
                  'scene_version_id':scene_id,'character_version_ids':actor_ids,'strategy':'still_motion',
                  'contract':{'visual':'两人保持服装与持信手','facts':{'promise':'日落前交信'},
                              'source_image_asset_ids':[image['id']],'opening':deepcopy(states),'closing':deepcopy(states)}}
                 for index in range(1,6)]
        clean_shots.append(deepcopy(shots))
        if number == 1:
            shots[1]['contract']['opening'][0].update(left_hand=None,right_hand='letter',action='起身')
            shots[2]['contract']['facts']['promise'] = '午夜交信'
            shots[3]['contract']['opening'][0]['wardrobe_id'] = 'red'
            shots[4]['scene_version_id'] = create('scene','未批准市场',{})['version_id']
        board = create('storyboard',f'分镜 {number}',{'source_version_id':episode['version_id'],'shots':shots})
        boards.append(board)
        plans.append({'episode_version_id':episode['version_id'],'storyboard_version_id':board['version_id'],
                      'target_duration_ms':5000,'bridge_note':'从灯塔外切到灯室' if number==2 else ''})
    payload = {'script_version_id':script['version_id'],'theme':'守信','world':'灯塔','episodes':plans,'guardian':canon}
    bible = create('story_bible','灯塔制作合同',payload)
    review = f"/api/series/entities/{bible['id']}/approve"

    def report(edition):
        return client.get(f"/api/series/versions/{edition['version_id']}/continuity").json()

    def save(edition, content, key):
        result = client.post(f"/api/story/entities/{edition['id']}/versions",json={
            'title':edition['title'],'content':content,'expected_version':edition['version'],'idempotency_key':key})
        assert result.status_code==201,result.text
        return result.json()

    def approve(edition, key):
        return client.post(review,json={'note':'逐项审核固定版本','expected_version':edition['version'],'idempotency_key':key})

    failed = report(bible)
    assert failed['guardian']['shot_count']==10
    assert {'canon_fact_conflict','shot_state_change','wardrobe_not_in_canon','scene_not_in_canon'} <= {
        item['code'] for item in failed['issues']}
    hand = next(item for item in failed['issues'] if item['code']=='shot_state_change')
    assert hand['start_ms']==1000 and hand['shot']=='ep1-shot2'
    assert hand['evidence']['fields']['left_hand']=={'expected':'letter','observed':None}
    assert approve(bible,'bad').status_code==422

    clean_shots[0][0].update(dialogue='好。',dialogue_ms=300,speaker_version_id=actor_a['version_id'])
    fixed_board = save(boards[0],{**boards[0]['content'],'shots':clean_shots[0]},'repair-board')
    plans[0]['storyboard_version_id'] = fixed_board['version_id']
    corrected = save(bible,payload,'repair-bible')
    first = approve(corrected,'first')
    assert first.status_code==201,first.text
    approved = first.json()
    assert len(approved['provenance']['guardian_manifest'])==10
    assert not any(item['severity']=='error' for item in report(approved)['issues'])
    voice_request = {'storyboard_version_id':fixed_board['version_id'],'series_version_id':approved['version_id'],
                     'bindings':[{'character_version_id':actor_a['version_id'],'voice':'错误音色','authorization':'本测试原创对白'}],
                     'idempotency_key':'wrong-voice'}
    wrong = client.post(f'/api/voice/projects/{project}/tasks',json=voice_request)
    assert wrong.status_code==422 and '固定音色不符' in wrong.text

    queue = f'/api/generation/projects/{project}/still-motion'
    body = {'asset_id':image['id'],'story_version_id':approved['version_id'],'shot_id':'ep1-shot1',
            'candidates':[{'preset':'push_in','aspect':'square','frames':24}],'idempotency_key':'motion'}
    assert client.post(queue,json={**body,'asset_id':stray['id']}).status_code==422
    job = client.post(queue,json=body)
    assert job.status_code==201,job.text
    job = job.json()[0]
    assert worker.run_once()
    job_path = f"/api/generation/candidates/{job['id']}"
    select = {'title':'候选','note':'内容核对完成'}
    assert client.post(job_path+'/select',json=select).status_code==409
    assert client.get(job_path+'/guardian-frames/1').headers['content-type']=='image/jpeg'
    bad_review = {'decision':'rejected','category':'wardrobe','frame':1,'note':'预置错误服装验收'}
    verdict = client.post(job_path+'/guardian-review',json=bad_review)
    assert verdict.status_code==200 and verdict.json()['evidence']['time_ms']==500
    assert client.post(job_path+'/guardian-review',json=bad_review).json()==verdict.json()
    assert client.post(job_path+'/select',json=select).status_code==409

    new_task = client.post(queue,json={**body,'idempotency_key':'replacement',
                                     'candidates':[{'preset':'pan_right','aspect':'square','frames':24}]}).json()[0]
    assert worker.run_once()
    replacement_path = f"/api/generation/candidates/{new_task['id']}"
    assert client.post(replacement_path+'/guardian-review',json={'decision':'approved','note':'已人工复核'}).status_code==200
    task = task_status(new_task['id'])
    media = resolve(task['output']['storage_key'])
    original = media.read_bytes()
    try:
        media.write_bytes(b'\x00'*len(original))
        assert client.post(replacement_path+'/select',json=select).status_code==409
    finally:
        media.write_bytes(original)
    assert client.post(replacement_path+'/select',json=select).status_code==201

    revising = save(actor_a,{**actor_a['content'],'identity':{**identity,'traits':'灰围巾与护目镜'}},'actor-v2')
    # A draft using a different identity must update every reference through the fixed board.
    drifted = deepcopy(payload)
    drifted['guardian']['character_version_ids'][0] = revising['version_id']
    unbound = save(approved,drifted,'identity-conflict')
    assert 'character_not_in_canon' in {item['code'] for item in report(unbound)['issues']}
    assert approve(unbound,'identity-conflict').status_code==422
    stale_task = client.post(queue,json={**body,'idempotency_key':'queued-before-approval'}).json()[0]
    for index, board in enumerate((fixed_board,boards[1])):
        revised_shots = deepcopy(clean_shots[index])
        for shot in revised_shots:
            shot['character_version_ids'][0] = revising['version_id']
            if shot.get('speaker_version_id')==actor_a['version_id']:
                shot['speaker_version_id'] = revising['version_id']
            for edge in ('opening','closing'):
                shot['contract'][edge][0]['character_version_id'] = revising['version_id']
        revision = save(board,{**board['content'],'shots':revised_shots},'update-locked-actor')
        drifted['episodes'][index]['storyboard_version_id'] = revision['version_id']
    draft = save(unbound,drifted,'identity-resolved')
    result = approve(draft,'identity-approved')
    assert result.status_code==201,result.text
    latest = result.json()
    impact = client.get(f"/api/series/versions/{latest['version_id']}/impact",params={'baseline_version_id':approved['version_id']}).json()
    assert {item['kind'] for item in impact['shots']}=={'contract_changed'}
    assert client.post(queue,json={**body,'idempotency_key':'stale-contract'}).status_code==409
    assert client.post(queue,json=body).json()[0]['id']==job['id']
    assert client.post(replacement_path+'/select',json=select).status_code==201
    assert worker.run_once()
    stale_path = f"/api/generation/candidates/{stale_task['id']}"
    assert client.post(stale_path+'/guardian-review',json={'decision':'approved','note':'过期提交'}).status_code==409
    assert client.post(stale_path+'/select',json=select).status_code==409
    assert media.read_bytes()==original

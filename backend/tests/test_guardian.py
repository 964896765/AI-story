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

    reworks = f'/api/generation/projects/{project}/shot-reworks'
    rework = {'series_version_id':approved['version_id'],'shot_id':'ep1-shot1','asset_id':image['id'],
              'aspect':'square','preset':'pan_right','reason':'重做指定镜头','idempotency_key':'replacement'}
    assert client.post(reworks,json={**rework,'asset_id':stray['id']}).status_code==422
    result = client.post(reworks,json=rework)
    assert result.status_code==201,result.text
    new_task = result.json()
    assert new_task['parameters']['frames']==24 and new_task['rework']['reason']=='重做指定镜头'
    assert client.post(reworks,json=rework).json()['id']==new_task['id']
    assert client.post(reworks,json={**rework,'reason':'不同返工原因'}).status_code==409
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
    queued_rework = client.post(reworks,json={**rework,'idempotency_key':'rework-before-approval'}).json()
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
    assert worker.run_once()
    stale_rework = task_status(queued_rework['id'])
    assert stale_rework['status']=='failed' and '已有新版获批' in stale_rework['error']
    assert media.read_bytes()==original


def test_guardian_replacement_keeps_other_clips_and_audio(creative, tmp_path):
    fixture, create = creative
    client, project, audio, upload, _, task_status, resolve, _ = fixture
    picture = tmp_path/'replacement.png'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=128x96',
                    '-frames:v','1','-threads','1',str(picture)],check=True,timeout=15)
    image = upload('原创灯室.png',picture.read_bytes())
    black = tmp_path/'black.png'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=black:s=128x96',
                    '-frames:v','1','-threads','1',str(black)],check=True,timeout=15)
    black_image = upload('全黑检查样本.png',black.read_bytes())
    source = create('script','灯室剧本',{'body':'灯室的两个定场镜头。'})
    scene = create('scene','灯室',{'description':'虚构灯室'})
    episode = create('episode','灯室首集',{'number':1,'body':'镜头从灯到窗。','source_version_id':source['version_id']})
    shots = [{'number':n,'shot_id':f'room-{n}','description':f'灯室视角 {n}','planned_duration':1,
              'scene_version_id':scene['version_id'],'strategy':'still_motion',
              'contract':{'visual':'固定灯室','source_image_asset_ids':[image['id'],black_image['id']] if n==1 else [image['id']]}}
              for n in (1,2)]
    shots[0]['contract']['screen_text'] = {'language':'qaa-ZZ','required':['灯室']}
    board = create('storyboard','灯室分镜',{'source_version_id':episode['version_id'],'shots':shots})
    bible = create('story_bible','灯室制作计划',{'script_version_id':source['version_id'],'theme':'灯光','world':'虚构灯室',
        'guardian':{'facts':{'location':'两个镜头都在灯室内'},'scene_version_ids':[scene['version_id']],
                    'style':{'description':'写实'}},
        'episodes':[{'episode_version_id':episode['version_id'],'storyboard_version_id':board['version_id'],
                     'target_duration_ms':2000}]})
    approved = client.post(f"/api/series/entities/{bible['id']}/approve",json={
        'expected_version':1,'note':'固定两镜','idempotency_key':'approve'})
    assert approved.status_code==201,approved.text
    plan = approved.json()['version_id']
    generate = f'/api/generation/projects/{project}/shot-reworks'

    def candidate(shot, preset, source=image):
        result = client.post(generate,json={
            'series_version_id':plan,'shot_id':shot,'asset_id':source['id'],'preset':preset,'aspect':'square',
            'reason':'灯室验收','idempotency_key':shot+preset+source['id']})
        assert result.status_code==201,result.text
        task = result.json()
        assert worker.run_once()
        return task['id']

    def adopt(task):
        root = f'/api/generation/candidates/{task}'
        review = {'decision':'approved','note':'逐帧核对'}
        output = task_status(task)['output']
        if screen := output.get('guardian_screen_text'):
            assert screen['reason']=='language_unavailable' and screen['status']=='unavailable'
            assert screen['output_sha256']==output['sha256'] and not screen['samples'] and screen['evidence']
            assert client.post(root+'/guardian-review',json=review).status_code==409
            review['screen_text_verified'] = True
        approved = client.post(root+'/guardian-review',json=review)
        assert approved.status_code==200,approved.text
        if 'screen_text_verified' in review:
            assert approved.json()['request']['screen_text_verified'] is True
        selected = client.post(root+'/select',json={'title':'灯室镜头','note':'实测采纳'})
        assert selected.status_code==201,selected.text
        return selected.json()

    black_task = candidate('room-1','push_in',black_image)
    output = task_status(black_task)['output']
    visual = output['guardian_visual']
    issue, = visual['findings']
    assert visual['status']=='blocked' and visual['checked_frames']==visual['black_frames']==24
    assert visual['output_sha256']==output['sha256']
    point = issue['evidence']['index']
    root = f'/api/generation/candidates/{black_task}'
    assert point>=3 and client.get(f'{root}/guardian-frames/{point}').status_code==200
    assert client.post(root+'/guardian-review',json={'decision':'approved','note':'试图通过全黑候选'}).status_code==409
    assert client.post(root+'/guardian-review',json={
        'decision':'approved','note':'人工核验不能解除技术阻断','screen_text_verified':True}).status_code==409
    assert client.post(root+'/select',json={'title':'全黑候选','note':'试图采纳'}).status_code==409
    rejected = client.post(root+'/guardian-review',json={
        'decision':'rejected','category':'technical','frame':point,'note':'全黑证据'})
    assert rejected.status_code==200,rejected.text
    assert rejected.json()['evidence']['sha256']==issue['evidence']['sha256']

    first = adopt(candidate('room-1','push_in'))
    second = adopt(candidate('room-2','push_in'))
    edit = create('timeline','灯室多轨时间轴',{'source_version_id':plan,'profile':'square','frames':48,'tracks':[
        {'id':'main','role':'main','clips':[{'id':'a','asset_id':first['id'],'at':0,'frames':24},
                                         {'id':'b','asset_id':second['id'],'at':24,'frames':24}]},
        {'id':'music','role':'music','volume':.25,'clips':[{'id':'mix','asset_id':audio['id'],'at':0,'frames':48}]},
    ]})
    replacement = candidate('room-1','pull_out')
    root = f'/api/timeline/projects/{project}/shot-replacements'
    body = {'series_version_id':plan,'timeline_version_id':edit['version_id'],'shot_id':'room-1',
            'candidate_id':replacement,'note':'仅替换首镜','idempotency_key':'apply'}
    assert client.post(root,json=body).status_code==409
    new_asset = adopt(replacement)
    path = resolve(new_asset['storage_key'])
    before = path.read_bytes()
    try:
        path.write_bytes(b'\x00'*len(before))
        assert client.post(root,json=body).status_code==409
    finally:
        path.write_bytes(before)
    options = client.get(root+'/options',params={'series_version_id':plan,'shot_id':'room-1'}).json()
    assert [item['version_id'] for item in options]==[edit['version_id']]
    saved = client.post(root,json=body)
    assert saved.status_code==201,saved.text
    new = saved.json()
    assert new['id']==edit['id'] and new['version']==2
    assert client.post(root,json=body).json()['version_id']==new['version_id']
    assert client.post(root,json={**body,'note':'冲突'}).status_code==409
    assert client.post(root,json={**body,'idempotency_key':'stale'}).status_code==409
    expected = deepcopy(edit['content'])
    expected['tracks'][0]['clips'][0]['asset_id'] = new_asset['id']
    assert new['content']==expected
    assert client.get(f"/api/story/versions/{edit['version_id']}").json()['content']==edit['content']
    render = client.post(f'/api/timeline/projects/{project}/renders',json={
        'version_id':new['version_id'],'idempotency_key':'render-replacement'})
    assert render.status_code==201,render.text
    assert worker.run_once()
    result = task_status(render.json()['id'])
    assert result['status']=='succeeded',result['error']
    assert result['output']['frames']==48 and result['output']['has_audio']

from pathlib import Path
import subprocess

from app import worker
from test_creative import creative
from test_postgres import database
from test_render_postgres import studio


def make_fixture(args):
    subprocess.run(['ffmpeg','-v','error',*map(str,args)],check=True,timeout=45)


def test_real_multitrack_timeline_render_and_restore(creative,tmp_path):
    studio,create = creative
    client,project,video,upload,_,task,resolve,_=studio
    picture=tmp_path/'still.png'
    audio=tmp_path/'audio.wav'
    make_fixture(['-f','lavfi','-i','testsrc2=size=320x240','-frames:v','1','-threads','1','-update','1',picture])
    make_fixture(['-f','lavfi','-i','sine=frequency=660:sample_rate=48000:duration=2','-c:a','pcm_s16le',audio])
    still=upload('自有图片.png',picture.read_bytes())
    wav=upload('配音.wav',audio.read_bytes())
    subtitles=upload('字幕.srt',b'1\n00:00:00,100 --> 00:00:01,500\nTimeline QA\n')
    tracks=[
        {'id':'main','role':'main','clips':[
            {'id':'video','asset_id':video['id'],'at':0,'source_in':12,'frames':24},
            {'id':'still','asset_id':still['id'],'at':24,'frames':24,'still_motion':'push_in'}]},
        {'id':'overlay','role':'overlay','clips':[{'id':'pip','asset_id':still['id'],'at':3,'frames':12,'fade_in':3}]},
        {'id':'speech','role':'dialogue','clips':[{'id':'dialogue','asset_id':wav['id'],'at':0,'frames':48}]},
        {'id':'music','role':'music','volume':.2,'clips':[{'id':'bed','asset_id':wav['id'],'at':6,'frames':40,'fade_out':4}]},
        {'id':'subtitles','role':'caption','clips':[{'id':'caption-cues','asset_id':subtitles['id'],'at':0,'frames':48}]},
    ]
    content={'profile':'square','frames':48,'tracks':tracks}
    initial=create('timeline','测试多轨时间轴',content)
    render_path=f'/api/timeline/projects/{project}/renders'
    body={'version_id':initial['version_id'],'idempotency_key':'real-timeline'}
    result=client.post(render_path,json=body)
    assert result.status_code==201,result.text
    job=result.json()
    assert client.post(render_path,json=body).json()['id']==job['id']
    assert worker.run_once()
    output=task(job['id'])
    assert output['status']=='succeeded',output['error']
    assert output['output']['frames']==48 and output['output']['has_audio']
    assert output['output']['duration']==2
    assert client.get(f"/api/tasks/{job['id']}/output",headers={'Range':'bytes=0-99'}).status_code==206
    probe = subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=codec_name','-of','csv=p=0',
                                     str(resolve(output['output']['storage_key']))],timeout=30,text=True)
    assert probe.splitlines()==['h264','aac']
    manifest=client.get(f"/api/timeline/versions/{initial['version_id']}/manifest").json()
    assert manifest['assets'][video['id']]['sha256']==video['sha256']
    assert all('storage_key' not in item for item in manifest['assets'].values())

    version_path=f"/api/story/entities/{initial['id']}"
    tracks[1]['clips'][0]['at']=6
    updated=client.post(version_path+'/versions',json={'title':initial['title'],'content':content,
        'idempotency_key':'move-overlay','expected_version':1})
    assert updated.status_code==201,updated.text
    restored=client.post(version_path+'/restore',json={'version':1,'expected_version':2,'idempotency_key':'restore-timeline'})
    assert restored.status_code==201,restored.text
    assert restored.json()['content']==initial['content'] and restored.json()['version']==3


def test_assemble_and_render_three_fixed_episodes(creative,tmp_path):
    studio,create=creative
    client,project,_,upload,_,task,_,_=studio
    main=create('script','三个镜头的故事',{'body':'港湾的三个时刻。'})
    picture=tmp_path/'fixture.png'
    make_fixture(['-f','lavfi','-i','testsrc2=size=320x240','-frames:v','1','-threads','1','-update','1',picture])
    asset=upload('海港图.png',picture.read_bytes())
    entries=[]
    for number in range(1,4):
        episode=create('episode',f'第 {number} 集',{'number':number,'body':'港湾色彩片段。','source_version_id':main['version_id']})
        board=create('storyboard',f'镜头 {number}',{'source_version_id':episode['version_id'],'shots':[
            {'number':1,'shot_id':f'port-{number}','description':'海港画面','planned_duration':.5}
        ]})
        entries.append({'episode_version_id':episode['version_id'],'storyboard_version_id':board['version_id'],
                        'target_duration_ms':500})
    series=create('story_bible','港湾三集',{'script_version_id':main['version_id'],'theme':'光线','world':'虚构海湾','episodes':entries})
    approve=client.post(f"/api/series/entities/{series['id']}/approve",json={
        'expected_version':1,'note':'人工审核自编三集','idempotency_key':'approved-bible'})
    assert approve.status_code==201,approve.text
    pinned=approve.json()['version_id']
    for number in range(1,4):
        gen=client.post(f'/api/generation/projects/{project}/still-motion',json={
            'asset_id':asset['id'],'candidates':[{'preset':'push_in','frames':12,'aspect':'square'}],
            'idempotency_key':f'gen-{number}','story_version_id':pinned,'shot_id':f'port-{number}'})
        assert gen.status_code==201,gen.text
        item=gen.json()[0]
        assert worker.run_once()
        assert task(item['id'])['status']=='succeeded',task(item['id'])['error']
        chosen=client.post(f"/api/generation/candidates/{item['id']}/select",json={
            'title':f'镜头候选 {number}','note':'已确认与自有分镜一致'})
        assert chosen.status_code==201,chosen.text
        assemble_path=f'/api/timeline/projects/{project}/assemble'
        request={'series_version_id':pinned,'episode':number,'title':f'第 {number} 集剪辑',
                 'idempotency_key':f'assemble-{number}','profile':'square'}
        assembled=client.post(assemble_path,json=request)
        assert assembled.status_code==201,assembled.text
        timeline=assembled.json()
        assert client.post(assemble_path,json=request).json()['version_id']==timeline['version_id']
        frame=timeline['content']['tracks'][0]['clips'][0]
        assert frame['asset_id']==chosen.json()['id'] and frame['frames']==12
        render=client.post(f'/api/timeline/projects/{project}/renders',json={
            'version_id':timeline['version_id'],'idempotency_key':f'episode-{number}'})
        assert render.status_code==201,render.text
        assert worker.run_once()
        completed=task(render.json()['id'])
        assert completed['status']=='succeeded',completed['error']
        assert completed['output']['frames']==12

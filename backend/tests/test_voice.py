from pathlib import Path
import wave

import pytest

from app import worker
from test_creative import creative
from test_postgres import database
from test_render_postgres import studio


def test_installed_voice_alignment_and_assets(creative):
    studio,create=creative
    client,project,_,_,_,task,resolve,_=studio
    available=client.get('/api/voice/capabilities').json()
    voices={voice['locale']:voice['name'] for voice in available['voices']}
    if not {'zh-CN','en-US'}.issubset(voices):
        pytest.skip('Requires installed offline Microsoft Huihui and Zira desktop voices')
    assert available['network_enabled'] is False
    source=create('script','配音验收对白',{'body':'阿青：晚安。\n灯塔守卫：Good night.'})
    characters=[create('character',speaker,{}) for speaker in ('阿青','灯塔守卫')]
    dialogue=['海港见。','Good night.']
    board=create('storyboard','配音分镜',{'source_version_id':source['version_id'],'shots':[
        {'number':i,'shot_id':f'voice-{i}','description':'读台词','planned_duration':5,
         'character_version_ids':[role['version_id']],'speaker_version_id':role['version_id'],'dialogue':line}
        for i,(line,role) in enumerate(zip(dialogue,characters),1)]})
    bindings=[{'character_version_id':role['version_id'],'voice':voices[locale],
               'authorization':'自编测试对白与本机音色，仅在本机验收中使用'}
              for role,locale in zip(characters,('zh-CN','en-US'))]
    route=f'/api/voice/projects/{project}/tasks'
    body={'storyboard_version_id':board['version_id'],'bindings':bindings,'idempotency_key':'voice-smoke'}
    invalid=client.post(route,json={**body,'bindings':bindings[:1]})
    assert invalid.status_code==422
    created=client.post(route,json=body)
    assert created.status_code==201,created.text
    job=created.json()
    assert client.post(route,json=body).json()==job
    assert client.post(route,json={**body,'bindings':[bindings[0],{**bindings[1],'rate':2}]}).status_code==409
    assert worker.run_once()
    rendered=task(job['id'])
    assert rendered['status']=='succeeded',rendered['error']
    output=rendered['output']
    assert output['actual_external_cost_micros']==0
    assert [cue['start_ms'] for cue in output['cues']]==[0,5000]
    assert all(cue['start_ms']<cue['end_ms']<cue['start_ms']+5000 for cue in output['cues'])
    wav=resolve(output['files']['dialogue.wav']['storage_key'])
    with wave.open(str(wav),'rb') as audio:
        assert audio.getframerate()==48000 and audio.getnframes()==480000
        assert any(audio.readframes(48000))
        audio.setpos(4*48000)
        assert not any(audio.readframes(48000))
        audio.setpos(5*48000)
        assert any(audio.readframes(48000))
    files=f"/api/voice/tasks/{job['id']}/files/"
    assert client.get(files+'dialogue.vtt').text.startswith('WEBVTT\n')
    assert '00:00:05,000' in client.get(files+'dialogue.srt').text
    assert client.get(files+'dialogue.wav',headers={'Range':'bytes=0-99'}).status_code==206
    select_path=f"/api/voice/tasks/{job['id']}/select"
    chosen={'title':'验证用双角色配音','note':'试听两个角色与提示时间后采纳'}
    selected=client.post(select_path,json=chosen)
    assert selected.status_code==201,selected.text
    rows=selected.json()
    assert [Path(row['name']).suffix for row in rows]==['.wav','.srt']
    assert rows[0]['media_info']['story_version_id']==board['version_id']
    assert client.post(select_path,json=chosen).json()==rows

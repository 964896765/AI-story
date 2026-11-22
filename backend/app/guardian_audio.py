"""Check approved dialogue against published captions and the decoded mix."""
from array import array
from math import log10
from unicodedata import category, normalize
import wave

from fastapi import HTTPException

from .models import StoryVersion, Task
from .perception_asr import recognizer, transcribe

RULE_VERSION = 'guardian-dialogue-v1'
RATE = 16000
FLOOR_DBFS = -55
BLOCK_SAMPLES = RATE // 50
ASR_TOLERANCE_US = 250000


def text_key(text):
    return ' '.join(text.split())


def speech_key(text):
    return ''.join(char for char in normalize('NFKC',text).casefold()
                   if not char.isspace() and not category(char).startswith('P'))


def fixed_dialogue(db, project, episode, pair, duration_ms):
    task = db.get(Task,pair[0].media_info['task_id'])
    board = db.get(StoryVersion,episode['storyboard_version_id'])
    if (not task or not board or task.project_id!=project or task.story_version_id!=board.id or
        task.kind!='local_voice' or task.status!='succeeded' or task.input_snapshot.get('version_hash')!=board.content_hash):
        raise HTTPException(422,'缺少已验证的固定分镜配音任务')
    files = task.output.get('files') or {}
    for asset,name in zip(pair,('dialogue.wav','dialogue.srt')):
        entry = files.get(name) or {}
        if (asset.project_id!=project or entry.get('storage_key')!=asset.storage_key
            or entry.get('sha256')!=asset.sha256 or entry.get('size_bytes')!=asset.size_bytes):
            raise HTTPException(422,'采纳的配音或字幕与固定配音任务校验信息不符')
    shots = {shot['number']:shot for shot in board.content['shots'] if shot.get('dialogue','').strip()}
    windows = {shot['number']:shot for shot in episode['shots']}
    cues = task.output.get('cues') or []
    if [cue.get('shot_number') for cue in cues]!=sorted(shots):
        raise HTTPException(422,'配音记录未覆盖批准分镜的全部对白')
    lines = []
    for cue in cues:
        number = cue['shot_number']
        shot,window = shots[number],windows[number]
        speaker = db.get(StoryVersion,shot['speaker_version_id'])
        voice = (speaker.content.get('identity') or {}).get('local_voice') if speaker else None
        start,stop = cue['start_ms'],cue['end_ms']
        if (not voice or cue['voice']!=voice or cue['character_version_id']!=shot['speaker_version_id']
           or text_key(cue['text'])!=text_key(shot['dialogue'])
           or start!=window['start_ms'] or not start<stop<=window['start_ms']+window['duration_ms']):
            raise HTTPException(422,f'第 {number} 镜的配音记录与批准对白或固定音色不符')
        lines.append({'shot_id':window['shot_id'],'shot_number':number,'text':text_key(shot['dialogue']),
                      'start_ms':start,'end_ms':min(stop,duration_ms),'voice':voice,'character_version_id':speaker.id,
                      'speaker':speaker.title})
    return {'rule_version':RULE_VERSION,'storyboard_version_id':board.id,'storyboard_hash':board.content_hash,
            'voice_task_id':task.id,'voice_sha256':pair[0].sha256,'caption_source_sha256':pair[1].sha256,'lines':lines}


def compare_captions(lines, cues, add):
    remaining = {cue['start_us']:cue for cue in cues}
    for line in lines:
        start,stop = line['start_ms'],line['end_ms']
        cue = remaining.pop(start*1000,None)
        status = 'matched'
        if not cue:
            status = 'missing'
            add('subtitle_dialogue_missing','error',f"第 {line['shot_number']} 镜缺少固定对白字幕",start,stop)
        elif text_key(cue['text'])!=line['text'] or cue['end_us']!=stop*1000:
            status = 'different'
            add('subtitle_dialogue_mismatch','error',f"第 {line['shot_number']} 镜字幕内容或时段与批准对白不符",start,stop)
        yield {**line,'caption_status':status,'caption':cue['text'] if cue else None}
    for cue in remaining.values():
        add('subtitle_dialogue_extra','error','成片包含固定对白之外的字幕',cue['start_us']//1000,cue['end_us']//1000)


def loudest_block(waveform, start_ms, end_ms):
    start,stop = start_ms*RATE//1000,min(end_ms*RATE//1000,waveform.getnframes())
    if start>=stop:
        return None
    waveform.setpos(start)
    samples = array('h')
    samples.frombytes(waveform.readframes(stop-start))
    mean_square = max((sum(value*value for value in block)/len(block)
                       for index in range(0,len(samples),BLOCK_SAMPLES)
                       if (block := samples[index:index+BLOCK_SAMPLES])),default=0)
    return round(10*log10(mean_square/32768**2),2) if mean_square else None


def align_transcript(lines, observations):
    groups = [[] for _ in lines]
    windows = [(line['start_ms']*1000,line['end_ms']*1000) for line in lines]
    if not windows:
        return groups
    for item in observations:
        start,stop = item['start_us'],item['end_us']
        overlap = [min(stop,end)-max(start,begin) for begin,end in windows]
        index = max(range(len(windows)),key=overlap.__getitem__)
        if overlap[index]>=-ASR_TOLERANCE_US:
            groups[index].append(item)
    return groups


def check_dialogue(commands, path, duration_ms, snapshot, cues, has_audio, language, add, *, muted):
    lines = list(compare_captions(snapshot['lines'],cues,add))
    result = {**snapshot,'lines':lines,'silence_floor_dbfs':FLOOR_DBFS,
              'recognition':{'status':'disabled' if language is None else 'unavailable','adapter':None}}
    if not has_audio:
        for line in lines:
            line.update(audio_status='missing',max_window_rms_dbfs=None)
        return result
    target = commands.work/'guardian-mix.wav'
    try:
        commands.run(['ffmpeg','-nostdin','-v','error','-n','-xerror','-protocol_whitelist','file,pipe',
                      '-i',str(path),'-map','0:a:0','-t',str(duration_ms/1000),'-ac','1','-ar',str(RATE),
                      '-c:a','pcm_s16le',str(target)],'qc_dialogue_audio',88,timeout=180)
        with wave.open(str(target),'rb') as samples:
            for line in lines:
                commands.update('qc_dialogue_audio',90)
                dbfs = loudest_block(samples,line['start_ms'],line['end_ms'])
                line['max_window_rms_dbfs'] = dbfs
                line['audio_status'] = 'silent' if dbfs is None or dbfs<FLOOR_DBFS else 'signal'
                if line['audio_status']=='silent':
                    add('dialogue_silent','error',f"第 {line['shot_number']} 镜的成片对白窗口近静音",line['start_ms'],line['end_ms'])
                if muted:
                    line['audio_status'] = 'muted'
                    add('dialogue_track_muted','error',f"第 {line['shot_number']} 镜的时间轴对白轨音量为零",
                        line['start_ms'],line['end_ms'])
            duration_us = samples.getnframes()*1_000_000//RATE
        if language:
            check_transcription(commands,target,language,duration_us,lines,result,add)
    except (EOFError,wave.Error,ValueError,TimeoutError):
        for line in lines:
            line.setdefault('audio_status','unavailable')
            line.setdefault('max_window_rms_dbfs',None)
        add('dialogue_decode_failed','error','成片混音无法完成对白窗口检查')
    finally:
        target.unlink(missing_ok=True)
    return result


def check_transcription(commands,target,language,duration_us,lines,result,add):
    try:
        adapter = recognizer(language)
        observations = transcribe(commands,target,adapter,0,duration_us,progress=94,stage='qc_dialogue_asr')
    except (ValueError,TimeoutError,FileNotFoundError):
        result['recognition']['language'] = language
        add('dialogue_asr_unavailable','warning','本机对白听写未完成，请回听实际成片')
        return
    result['recognition'] = {'status':'checked','adapter':adapter}
    for line,segments in zip(lines,align_transcript(lines,observations)):
        observed = ' '.join(item['text'] for item in segments)
        status = 'matched' if speech_key(observed) and speech_key(observed)==speech_key(line['text']) else 'review'
        line['recognition'] = {'status':status,'observed':observed,'segments':segments}
        if status=='review':
            add('dialogue_asr_review','warning',f"第 {line['shot_number']} 镜的本机听写需要回听确认",
                line['start_ms'],line['end_ms'])

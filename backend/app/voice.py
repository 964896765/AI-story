"""Local Windows system speech, with exact sample placement and subtitle export."""
from array import array
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import wave

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import select

from . import storage
from .analysis_engine import Commands
from .config import ROOT
from .creative import require, version_ref
from .db import session
from .models import Asset, Project, Task, TaskEvent
from .render import file_hash, write_manifest
from .story_schemas import Strict

router = APIRouter(prefix='/api/voice',tags=['local-voice'])
SAMPLE_RATE = 48000
ENGINE = 'windows-system-speech-v1'
OUTPUTS = {'dialogue.wav':'audio/wav','dialogue.srt':'text/plain','dialogue.vtt':'text/vtt'}


class Binding(Strict):
    character_version_id: str=Field(min_length=1,max_length=36)
    voice: str=Field(min_length=1,max_length=100)
    rate: int=Field(default=0,ge=-5,le=5)
    authorization: str=Field(min_length=4,max_length=2000,pattern=r'.*\S.*')


class VoiceRequest(Strict):
    storyboard_version_id: str=Field(min_length=1,max_length=36)
    bindings: list[Binding]=Field(min_length=1,max_length=16)
    idempotency_key: str=Field(min_length=1,max_length=64)


class VoiceSelection(Strict):
    title: str=Field(min_length=1,max_length=180,pattern=r'.*\S.*')
    note: str=Field(min_length=1,max_length=2000,pattern=r'.*\S.*')


def powershell():
    path = Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
    if os.name!='nt' or not path.is_file():
        raise ValueError('本机不提供 Windows 系统语音')
    return [str(path),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
            str(ROOT/'scripts'/'synthesize_dialogue.ps1')]


def installed_voices():
    try:
        result = subprocess.run([*powershell(),'-List'],capture_output=True,timeout=15,check=True)
        return json.loads(result.stdout.decode('utf-8-sig'))
    except (ValueError,OSError,subprocess.SubprocessError):
        return []


@router.get('/capabilities')
def capabilities():
    voices = installed_voices()
    return {'engine':ENGINE,'available':bool(voices),'voices':voices,'network_enabled':False,
            'source_separation_available':False}


def plan_lines(storyboard,bindings):
    voices = {binding['character_version_id']:binding for binding in bindings}
    if len(voices)!=len(bindings):
        raise HTTPException(422,'同一角色只能分配一种音色')
    lines, cursor = [], 0
    for shot in sorted(storyboard['shots'],key=lambda row:row['number']):
        duration = round(shot['planned_duration']*1000)
        text = shot.get('dialogue','').strip()
        if text:
            character = shot.get('speaker_version_id')
            binding = voices.get(character)
            if not binding:
                raise HTTPException(422,f"镜头 {shot['number']} 缺少固定说话者或音色")
            if len(text)>1000:
                raise HTTPException(422,'每段对白最多 1000 字符')
            lines.append({
                'text':text,'start_ms':cursor,'end_ms':cursor+duration,'shot_number':shot['number'],
                'shot_id':shot.get('shot_id'),'character_version_id':character,'voice':binding['voice'],
                'rate':binding['rate'],
            })
        cursor += duration
    if not 1 <= len(lines) <= 40 or cursor>600000:
        raise HTTPException(422,'本地配音支持每次 1–40 条对白且计划最长十分钟')
    return lines,cursor


def public(task):
    return {'id':task.id,'storyboard_version_id':task.story_version_id,'status':task.status,'stage':task.stage,
            'error':task.error,'attempt':task.attempt,'output':{key:value for key,value in task.output.items()
             if key!='files'},'created_at':task.created_at}


@router.post('/projects/{project_id}/tasks',status_code=201)
def submit(project_id: str,body:VoiceRequest,db=Depends(session)):
    if not db.scalar(select(Project).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    _, version = version_ref(db,project_id,body.storyboard_version_id,{'storyboard'})
    bindings = [item.model_dump() for item in body.bindings]
    lines,duration = plan_lines(version.content,bindings)
    params = {'engine':ENGINE,'bindings':bindings}
    key = 'local-voice:'+body.idempotency_key
    prior = db.scalar(select(Task).where(Task.project_id==project_id,Task.idempotency_key==key))
    if prior:
        if prior.kind!='local_voice' or prior.story_version_id!=version.id or prior.parameters!=params:
            raise HTTPException(409,'请求键已用于其他配音参数')
        return public(prior)
    available = {voice['name'] for voice in installed_voices()}
    if not available or any(binding['voice'] not in available for binding in bindings):
        raise HTTPException(409,'所选语音未在本机安装')
    for binding in bindings:
        version_ref(db,project_id,binding['character_version_id'],{'character'})
    task = Task(project_id=project_id,asset_id=None,kind='local_voice',idempotency_key=key,
        story_version_id=version.id,parameters=params,input_snapshot={
            'version_hash':version.content_hash,'lines':lines,'duration_ms':duration})
    db.add(task)
    db.flush()
    db.add(TaskEvent(task_id=task.id,attempt=0,message='本机配音已按固定分镜排队'))
    db.commit()
    return public(task)


@router.get('/projects/{project_id}/tasks')
def tasks(project_id:str,db=Depends(session)):
    require(db,Project,project_id)
    rows = db.scalars(select(Task).where(Task.project_id==project_id,Task.kind=='local_voice')
        .order_by(Task.created_at.desc(),Task.id).limit(100)).all()
    return [public(task) for task in rows]


def ready(db,task_id):
    task = require(db,Task,task_id)
    if task.kind!='local_voice' or task.status!='succeeded':
        raise HTTPException(409,'配音尚未完成验证')
    return task


@router.get('/tasks/{task_id}/files/{name}')
def media(task_id:str,name:str,download:bool=False,db=Depends(session)):
    task = ready(db,task_id)
    entry = task.output['files'].get(name)
    if not entry or name not in OUTPUTS:
        raise HTTPException(404,'产物不存在')
    path = storage.resolve_key(entry['storage_key'])
    if not path.is_file() or path.stat().st_size!=entry['size_bytes']:
        raise HTTPException(404,'产物已缺失或不完整')
    return FileResponse(path,media_type=OUTPUTS[name],filename=name if download else None,
                        headers={'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})


@router.post('/tasks/{task_id}/select',status_code=201)
def select_assets(task_id:str,body:VoiceSelection,db=Depends(session)):
    task = ready(db,task_id)
    db.scalar(select(Project).where(Project.id==task.project_id).with_for_update())
    rows = []
    for name in ('dialogue.wav','dialogue.srt'):
        entry = task.output['files'][name]
        existing = db.scalar(select(Asset).where(Asset.storage_key==entry['storage_key']))
        filename = body.title.strip()+Path(name).suffix
        if existing:
            if existing.name!=filename or existing.media_info.get('selection_note')!=body.note:
                raise HTTPException(409,'配音已有采纳记录')
            rows.append(existing)
            continue
        path = storage.resolve_key(entry['storage_key'])
        if not path.is_file() or file_hash(path)!=entry['sha256']:
            raise HTTPException(409,'产物校验失败，请重新制作')
        note = '\n'.join(item['authorization'] for item in task.parameters['bindings'])
        asset = Asset(project_id=task.project_id,name=filename,storage_key=entry['storage_key'],
            sha256=entry['sha256'],size_bytes=entry['size_bytes'],authorization=note,media_info={
                'origin':ENGINE,'story_version_id':task.story_version_id,'task_id':task.id,'selection_note':body.note})
        db.add(asset)
        rows.append(asset)
    if db.new:
        db.add(TaskEvent(task_id=task.id,attempt=task.attempt,message='配音音轨与字幕已人工采纳'))
    db.commit()
    return rows


def stamp(ms, separator):
    hours, rest = divmod(ms,3_600_000)
    minutes, rest = divmod(rest,60_000)
    seconds, millis = divmod(rest,1000)
    return f'{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{millis:03d}'


def write_subtitles(path,cues,is_vtt):
    blocks = ['WEBVTT'] if is_vtt else []
    for index,cue in enumerate(cues,1):
        start,end = [stamp(cue[label],'.' if is_vtt else ',') for label in ('start_ms','end_ms')]
        content = ' '.join(cue['text'].split())
        if is_vtt:
            content = content.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
        blocks.append(f"{index}\n{start} --> {end}\n{content}")
    path.write_text('\n\n'.join(blocks)+'\n',encoding='utf-8',newline='\n')


def write_silence(target,frame_count):
    block = bytes(SAMPLE_RATE*2)
    while frame_count>=SAMPLE_RATE:
        target.writeframesraw(block)
        frame_count-=SAMPLE_RATE
    if frame_count:
        target.writeframesraw(block[:frame_count*2])


def compose_speech(folder,lines,duration_ms,update):
    cues = []
    cursor = 0
    audible = 0
    with wave.open(str(folder/'dialogue.wav'),'wb') as target:
        target.setparams((1,2,SAMPLE_RATE,0,'NONE','not compressed'))
        for index,line in enumerate(lines,1):
            with wave.open(str(folder.parent/f'line-{index:03d}.wav'),'rb') as source:
                if (source.getnchannels(),source.getsampwidth(),source.getframerate())!=(1,2,SAMPLE_RATE):
                    raise ValueError('语音采样率、位深或声道验证失败')
                frames = source.getnframes()
                pcm = source.readframes(frames)
            if not frames or len(pcm)!=frames*2:
                raise ValueError('语音合成返回了空或不完整音轨')
            samples = array('h')
            samples.frombytes(pcm)
            peak = max(abs(min(samples)),abs(max(samples)))
            if peak<100:
                raise ValueError(f"镜头 {line['shot_number']} 未生成可听语音")
            end_ms = line['start_ms']+(frames+47)//48
            if end_ms>line['end_ms']:
                actual_ms = end_ms-line['start_ms']
                raise ValueError(f"镜头 {line['shot_number']} 语音 {actual_ms} ms，超出计划窗口")
            start_frame = line['start_ms']*48
            write_silence(target,start_frame-cursor)
            target.writeframesraw(pcm)
            cursor = start_frame+frames
            audible += frames
            cues.append({**line,'end_ms':end_ms})
            update('voice_align',80)
        write_silence(target,duration_ms*48-cursor)
    with wave.open(str(folder/'dialogue.wav'),'rb') as check:
        if check.getnframes()!=duration_ms*48 or not audible:
            raise ValueError('合成总时长验证失败')
    for name in ('dialogue.srt','dialogue.vtt'):
        write_subtitles(folder/name,cues,name.endswith('.vtt'))
    return cues


def render_voice(task_id,attempt,parameters,input_snapshot,update):
    target = storage.resolve_key(f'outputs/{task_id}/speech')
    signature = hashlib.sha256(json.dumps([ENGINE,parameters,input_snapshot],sort_keys=True).encode()).hexdigest()
    if target.exists():
        manifest = json.loads((target/'manifest.json').read_text(encoding='utf-8'))
        if manifest['signature']!=signature:
            raise ValueError('已发布配音和固定分镜参数不匹配')
        for entry in manifest['files'].values():
            update('voice_verify',94)
            if file_hash(storage.resolve_key(entry['storage_key']))!=entry['sha256']:
                raise ValueError('已发布配音未通过哈希验证')
        return manifest
    work = storage.resolve_key(f'tmp/{task_id}/{attempt}')
    commands = Commands(work,update)
    if shutil.disk_usage(work).free<256*1024**2:
        raise OSError('磁盘可用空间不足 256 MiB')
    lines = input_snapshot['lines']
    duration = input_snapshot['duration_ms']
    write_manifest(work/'dialogue-input.json',{'lines':lines})
    commands.run(powershell(),'voice_synthesis',15,timeout=240)
    cues = compose_speech(commands.output,lines,duration,update)
    files = {}
    for name in OUTPUTS:
        path = commands.output/name
        files[name] = {'storage_key':f'outputs/{task_id}/speech/{name}','size_bytes':path.stat().st_size,
                       'sha256':file_hash(path,lambda *_:update('voice_verify',94))}
    manifest = {'engine':ENGINE,'actual_external_cost_micros':0,'duration_ms':duration,'cues':cues,
                'files':files,'signature':signature}
    update('voice_publish',97)
    write_manifest(commands.output/'manifest.json',manifest)
    target.parent.mkdir(parents=True,exist_ok=True)
    commands.output.rename(target)
    return manifest

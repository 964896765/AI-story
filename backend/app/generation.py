"""Real local still-image motion candidates queued through the existing Worker."""
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import select

from . import storage
from .analysis_engine import Commands
from .asset_validation import IMAGE_SUFFIXES
from .creative import require, version_ref
from .db import session
from .media import probe
from .guardian import require_active_plan
from .guardian_ocr import inspect_screen_text
from .models import Asset, Project, StoryVersion, Task, TaskEvent, now
from .render import execute_ffmpeg, file_hash, validate_output, write_manifest
from .series import approved_guardian_shot, series_report
from .story_schemas import Strict
from .visual_quality import MAX_FINDINGS, inspect_video

router = APIRouter(prefix='/api/generation', tags=['generation'])
PIPELINE = 'local-still-motion-v1'
DEMUXERS = {'.png':'png_pipe','.jpg':'jpeg_pipe','.jpeg':'jpeg_pipe','.webp':'webp_pipe'}
SIZES = {'portrait':(720,1280),'landscape':(1280,720),'square':(720,720)}


class StillMotion(Strict):
    preset: Literal['push_in','pull_out','pan_right']
    aspect: Literal['portrait','landscape','square']='portrait'
    frames: int=Field(default=72,ge=12,le=240)


class StillRequest(Strict):
    asset_id: str=Field(min_length=1,max_length=36)
    story_version_id: str | None=Field(default=None,min_length=1,max_length=36)
    shot_id: str | None=Field(default=None,min_length=1,max_length=48)
    candidates: list[StillMotion]=Field(min_length=1,max_length=3)
    idempotency_key: str=Field(min_length=1,max_length=64)


class Selection(Strict):
    title: str=Field(min_length=1,max_length=200,pattern=r'.*\S.*')
    note: str=Field(min_length=1,max_length=2000,pattern=r'.*\S.*')


class CandidateReview(Strict):
    decision: Literal['approved','rejected']
    category: Literal['identity','wardrobe','prop','scene','continuity','shot_mismatch','technical','screen_text','other'] | None=None
    frame: int | None=Field(default=None,ge=0,le=2+MAX_FINDINGS)
    note: str=Field(min_length=1,max_length=2000,pattern=r'\S')
    screen_text_verified: bool | None = Field(default=None,strict=True)


class ShotRework(Strict):
    series_version_id: str = Field(min_length=1,max_length=36)
    shot_id: str = Field(min_length=1,max_length=48)
    asset_id: str = Field(min_length=1,max_length=36)
    preset: Literal['push_in','pull_out','pan_right']
    aspect: Literal['portrait','landscape','square']
    reason: str = Field(min_length=1,max_length=2000,pattern=r'\S')
    idempotency_key: str = Field(min_length=1,max_length=64)


def shot_frames(shot):
    return round((shot['start_ms']+shot['duration_ms'])*24/1000)-round(shot['start_ms']*24/1000)


def guardian_input(series_id, contract):
    return {'series_id':series_id,'contract_sha256':contract['contract_sha256'],
            **({'screen_text':contract['screen_text']} if contract.get('screen_text') else {})}


@router.get('/capabilities')
def capabilities():
    return {'modes': [
        {'id':'local_still_motion','available':True,'external':False,'price_micros':0,'label':'本地静图运镜'},
        {'id':'ai_image','available':False,'external':True,'price_micros':None,'label':'AI 图片生成'},
        {'id':'ai_video','available':False,'external':True,'price_micros':None,'label':'AI 视频生成'},
        {'id':'remote_gpu','available':False,'external':True,'price_micros':None,'label':'远程 GPU'},
    ]}


def public(task):
    output = {key:value for key,value in task.output.items() if key not in ('storage_key','files')}
    return {'id':task.id,'asset_id':task.asset_id,'story_version_id':task.story_version_id,
            'mode':'local_still_motion','status':task.status,'stage':task.stage,'progress':task.progress,
            'parameters':task.parameters,'cancel_requested':task.cancel_requested,'error':task.error,
            'output':output,'guardian':task.input_snapshot.get('guardian'),
            'rework':task.input_snapshot.get('rework'),
            'created_at':task.created_at}


@router.post('/projects/{project_id}/still-motion',status_code=201)
def submit(project_id: str, body: StillRequest, db=Depends(session)):
    if not db.scalar(select(Project).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    image = require(db,Asset,body.asset_id)
    if image.project_id!=project_id or Path(image.storage_key).suffix.lower() not in IMAGE_SUFFIXES:
        raise HTTPException(422,'请选择同项目的图片素材')
    if bool(body.story_version_id)!=bool(body.shot_id):
        raise HTTPException(422,'制作计划和镜头 ID 必须一起固定')
    parameters = [{**candidate.model_dump(),'shot_id':body.shot_id} for candidate in body.candidates]
    if any(item in parameters[:i] for i,item in enumerate(parameters)):
        raise HTTPException(422,'候选参数不得重复')
    keys = [f'still-motion:{body.idempotency_key}:{i}' for i in range(3)]
    existing = {task.idempotency_key:task for task in db.scalars(select(Task).where(
        Task.project_id==project_id,Task.idempotency_key.in_(keys)))}
    if existing:
        result = [existing.get(key) for key in keys[:len(parameters)]]
        if len(existing)!=len(parameters) or any(task is None or task.kind!='still_motion'
            or task.asset_id!=image.id or task.story_version_id!=body.story_version_id
            or task.parameters!=option for task,option in zip(result,parameters)):
            raise HTTPException(409,'请求键已用于其他候选配置')
        return [public(task) for task in result]
    guardian = None
    if body.story_version_id:
        entity, version = version_ref(db,project_id,body.story_version_id,{'story_bible'})
        require_active_plan(db,version)
        report = series_report(db,entity,version)
        shot = next((shot for episode in report['episodes'] for shot in episode['shots']
                     if shot['shot_id']==body.shot_id),None)
        if not report['approved'] or not shot:
            raise HTTPException(422,'只能使用已批准计划中存在的镜头')
        if report.get('guardian'):
            contract = shot['guardian']
            if not contract or (version.provenance.get('guardian_manifest') or {}).get(body.shot_id)!=contract['contract_sha256']:
                raise HTTPException(409,'镜头合同与批准记录不符')
            if shot['strategy']!='still_motion' or contract['source_images'].get(image.id)!=image.sha256:
                raise HTTPException(422,'运镜方式或源图不符合已批准镜头合同')
            frames = shot_frames(shot)
            if any(candidate.frames!=frames for candidate in body.candidates):
                raise HTTPException(422,f'镜头合同要求候选输出 {frames} 帧')
            guardian = guardian_input(entity.id,contract)
    tasks = enqueue_motion(db, image, body.story_version_id, parameters, keys, guardian)
    db.commit()
    return [public(task) for task in tasks]


def enqueue_motion(db, image, version_id, parameters, keys, guardian, rework=None):
    snapshot = {'image':{'id':image.id,'storage_key':image.storage_key,'sha256':image.sha256}}
    if guardian:
        snapshot['guardian'] = guardian
    if rework:
        snapshot['rework'] = rework
    timestamp = now()
    tasks = [Task(project_id=image.project_id,asset_id=image.id,kind='still_motion',story_version_id=version_id,
        idempotency_key=key,parameters=option,created_at=timestamp+timedelta(microseconds=index),
        input_snapshot=snapshot)
        for index,(option,key) in enumerate(zip(parameters,keys))]
    db.add_all(tasks)
    db.flush()
    message = 'Guardian 单镜头返工候选已排队' if rework else '静图运镜候选已排队'
    db.add_all([TaskEvent(task_id=task.id,attempt=0,message=message) for task in tasks])
    return tasks


@router.post('/projects/{project_id}/shot-reworks',status_code=201)
def rework_shot(project_id: str,body: ShotRework,db=Depends(session)):
    if not db.scalar(select(Project.id).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    key = 'shot-rework:'+body.idempotency_key
    request = body.model_dump(exclude={'idempotency_key'})
    previous = db.scalar(select(Task).where(Task.project_id==project_id,Task.idempotency_key==key))
    if previous:
        if previous.kind!='still_motion' or previous.input_snapshot.get('rework')!=request:
            raise HTTPException(409,'请求键已用于其他镜头返工')
        return public(previous)
    entity,version,_,shot = approved_guardian_shot(db,project_id,body.series_version_id,body.shot_id)
    image = require(db,Asset,body.asset_id)
    contract = shot['guardian']
    if (shot['strategy']!='still_motion' or image.project_id!=project_id
        or Path(image.storage_key).suffix.lower() not in IMAGE_SUFFIXES
        or contract['source_images'].get(image.id)!=image.sha256):
        raise HTTPException(422,'返工须使用合同允许的本机运镜源图')
    frames = shot_frames(shot)
    if not 12<=frames<=240:
        raise HTTPException(422,'本机运镜支持 12 至 240 帧，请先修订镜头合同')
    parameters = {'preset':body.preset,'aspect':body.aspect,'frames':frames,'shot_id':body.shot_id}
    guardian = guardian_input(entity.id,contract)
    task, = enqueue_motion(db,image,version.id,[parameters],[key],guardian,rework=request)
    db.commit()
    return public(task)


@router.get('/projects/{project_id}/candidates')
def candidates(project_id: str,shot_id: str|None=None,series_id: str|None=None,db=Depends(session)):
    require(db,Project,project_id)
    statement = select(Task).where(Task.kind=='still_motion',Task.project_id==project_id)
    if shot_id:
        statement = statement.where(Task.parameters['shot_id'].as_string()==shot_id)
    if series_id:
        statement = statement.where(Task.input_snapshot['guardian']['series_id'].as_string()==series_id)
    rows = db.scalars(statement
                      .order_by(Task.created_at.desc(),Task.id).limit(100)).all()
    published = {task.output['storage_key'] for task in rows if task.status=='succeeded'}
    assets = {asset.storage_key:asset.id for asset in db.scalars(select(Asset).where(Asset.storage_key.in_(published)))}
    return [{**public(task),'selected_asset_id':assets.get(task.output.get('storage_key'))} for task in rows]


def finished_candidate(db, task_id):
    task = require(db,Task,task_id)
    if task.kind!='still_motion' or task.status!='succeeded':
        raise HTTPException(409,'候选仍未通过视频验证')
    path = storage.resolve_key(task.output['storage_key'])
    if not path.is_file() or path.stat().st_size!=task.output['size_bytes']:
        raise HTTPException(404,'候选文件已缺失或不完整')
    return task,path


@router.get('/candidates/{task_id}/video')
def video(task_id: str,db=Depends(session)):
    _,path = finished_candidate(db,task_id)
    return FileResponse(path,media_type='video/mp4',headers={'X-Content-Type-Options':'nosniff'})


def checked_frame(task, index):
    frame = task.output.get('files',{}).get(f'guardian-{index}')
    if not frame:
        raise HTTPException(404,'候选证据帧不存在')
    path = storage.resolve_key(frame['storage_key'])
    if not path.is_file() or file_hash(path)!=frame['sha256']:
        raise HTTPException(409,'候选证据帧完整性检查失败')
    return frame,path


@router.get('/candidates/{task_id}/guardian-frames/{index}')
def guardian_frame(task_id: str,index: int,db=Depends(session)):
    task,_ = finished_candidate(db,task_id)
    _,path = checked_frame(task,index)
    return FileResponse(path,media_type='image/jpeg',headers={'X-Content-Type-Options':'nosniff'})


def require_visual_clearance(task):
    visual = task.output.get('guardian_visual')
    if visual and (visual['output_sha256']!=task.output['sha256'] or visual['status']=='blocked'):
        raise HTTPException(409,'候选未通过本机视觉技术检查，可记录退回并制作新候选')


def require_screen_text_clearance(task, confirmed):
    expected = task.input_snapshot['guardian'].get('screen_text')
    if not expected:
        return
    report = task.output.get('guardian_screen_text') or {}
    if (report.get('contract')!=expected or report.get('output_sha256')!=task.output['sha256']
        or report.get('status') not in ('matched','review','unavailable')):
        raise HTTPException(409,'缺少与当前候选匹配的画面文字报告，请重新制作')
    if report['status']!='matched' and confirmed is not True:
        raise HTTPException(409,'请对照实际画面，确认已人工核验必现和禁现文字')


@router.post('/candidates/{task_id}/guardian-review')
def review_candidate(task_id: str,body: CandidateReview,db=Depends(session)):
    task,path = finished_candidate(db,task_id)
    db.scalar(select(Project).where(Project.id==task.project_id).with_for_update())
    db.refresh(task)
    if not task.input_snapshot.get('guardian'):
        raise HTTPException(422,'该候选没有已锁定的 Guardian 镜头合同')
    request = body.model_dump()
    if body.screen_text_verified is None:
        request.pop('screen_text_verified')
    previous = task.output.get('guardian_review')
    if previous:
        if previous['request']!=request:
            raise HTTPException(409,'此候选已有审核记录，可提交新的返工候选')
        return previous
    require_active_plan(db,require(db,StoryVersion,task.story_version_id))
    if body.decision=='rejected' and (not body.category or body.frame is None):
        raise HTTPException(422,'退回候选需要选择问题类别与证据帧')
    if body.decision=='rejected' and body.screen_text_verified is not None:
        raise HTTPException(422,'文字核验确认仅用于通过候选')
    if body.screen_text_verified is not None and not task.input_snapshot['guardian'].get('screen_text'):
        raise HTTPException(422,'此候选没有固定画面文字规则')
    if body.decision=='approved' and (body.category is not None or body.frame is not None):
        raise HTTPException(422,'通过候选时只需填写审核说明')
    if body.decision=='approved':
        require_visual_clearance(task)
        require_screen_text_clearance(task,body.screen_text_verified)
    checked = {item['index']:checked_frame(task,item['index'])[0] for item in task.output['guardian_frames']}
    if file_hash(path)!=task.output['sha256']:
        raise HTTPException(409,'候选文件校验失败，请重新制作')
    evidence = checked.get(body.frame)
    if body.frame is not None and evidence is None:
        raise HTTPException(422,'所选时间点没有候选证据帧')
    review = {'request':request,'source':'local_operator','created_at':now().isoformat(),
              'output_sha256':task.output['sha256'],
              'evidence':{'time_ms':evidence['time_ms'],'sha256':evidence['sha256']} if evidence else None}
    task.output = {**task.output,'guardian_review':review}
    db.add(TaskEvent(task_id=task.id,attempt=task.attempt,message='Guardian 候选人工审核 · '+body.decision))
    db.commit()
    return review


@router.post('/candidates/{task_id}/select',status_code=201)
def select_candidate(task_id: str,body: Selection,db=Depends(session)):
    task,path = finished_candidate(db,task_id)
    db.scalar(select(Project).where(Project.id==task.project_id).with_for_update())
    selected = db.scalar(select(Asset).where(Asset.storage_key==task.output['storage_key']))
    name = body.title.strip()+'.mp4'
    if selected:
        if selected.name!=name or selected.media_info.get('selection_note')!=body.note:
            raise HTTPException(409,'该候选已有采纳记录')
        return selected
    if file_hash(path)!=task.output['sha256']:
        raise HTTPException(409,'候选文件校验失败，请重新制作')
    guardian=task.input_snapshot.get('guardian')
    if task.story_version_id:
        require_active_plan(db,require(db,StoryVersion,task.story_version_id))
    review = task.output.get('guardian_review')
    if guardian and (not review or review['request']['decision']!='approved' or review['output_sha256']!=task.output['sha256']):
        raise HTTPException(409,'候选须通过 Guardian 人工内容审核后采纳')
    if guardian:
        require_visual_clearance(task)
        require_screen_text_clearance(task,review['request'].get('screen_text_verified'))
    source = require(db,Asset,task.asset_id)
    asset = Asset(project_id=task.project_id,name=name,storage_key=task.output['storage_key'],
                  sha256=task.output['sha256'],size_bytes=task.output['size_bytes'],
                  authorization=source.authorization,media_info={
                      'origin':'local_still_motion','generated_from_asset':source.id,'task_id':task.id,
                      'story_version_id':task.story_version_id,'shot_id':task.parameters.get('shot_id'),
                      'selection_note':body.note,'fps':24,'duration':task.output['duration'],
                      **({'guardian_series_id':guardian['series_id'],'guardian_contract_sha256':guardian['contract_sha256'],
                          'guardian_aspect':task.parameters['aspect']}
                         if guardian else {}),
                  })
    db.add(asset)
    db.add(TaskEvent(task_id=task.id,attempt=task.attempt,message='已人工采纳为项目视频素材'))
    db.commit()
    return asset


def image_dimensions(source, demuxer):
    result = subprocess.run(['ffprobe','-v','error','-protocol_whitelist','file,pipe',
        '-f',demuxer,'-select_streams','v:0','-show_entries','stream=width,height','-of','json',str(source)],
        timeout=20, check=True,capture_output=True)
    streams = json.loads(result.stdout).get('streams',[])
    if not streams:
        raise ValueError('无法解码图片')
    width,height = streams[0]['width'],streams[0]['height']
    if min(width,height)<2 or max(width,height)>8192 or width*height>36_000_000:
        raise ValueError('图片尺寸超过静图运镜限制')


def sample_candidate(path, commands, frames, visual):
    indices = list(dict.fromkeys([0,frames//2,frames-1]+[item['frame_number'] for item in visual['findings']]))
    decoded_positions = {number:index for index,number in enumerate(sorted(indices),1)}
    selection = '+'.join(f'eq(n\\,{index})' for index in indices)
    commands.run(['ffmpeg','-v','error','-nostdin','-n','-xerror','-filter_threads','2',
                  '-protocol_whitelist','file,pipe','-i',str(path),'-map','0:v:0',
                  '-vf',f'select={selection},scale=640:-2','-fps_mode','passthrough',
                  '-frames:v',str(len(indices)),'-threads','1',str(commands.output/'frame-%02d.jpg')],
                 'guardian_frames',98,timeout=45)
    evidence, files = [], {}
    for index, frame_number in enumerate(indices):
        image = commands.output/f'frame-{decoded_positions[frame_number]:02d}.jpg'
        if not image.is_file() or not image.stat().st_size:
            raise ValueError('候选缺少完整的 Guardian 证据帧')
        descriptor = {'time_ms':round(frame_number*1000/24),'index':index,'sha256':file_hash(image)}
        evidence.append(descriptor)
        files[f'guardian-{index}'] = {**descriptor,'storage_key':image.relative_to(storage.resolve_key('tmp').parent).as_posix()}
    for item in visual['findings']:
        item['evidence'] = evidence[indices.index(item['frame_number'])]
    return {'guardian_frames':evidence,'files':files}


def build_motion(task_id,attempt,parameters,input_snapshot,update,factory):
    options = StillMotion.model_validate({key:value for key,value in parameters.items() if key!='shot_id'})
    item = input_snapshot['image']
    source = storage.resolve_key(item['storage_key'])
    work = storage.resolve_key(f'tmp/{task_id}/{attempt}')
    storage_key = f'outputs/{task_id}/motion.mp4'
    target = storage.resolve_key(storage_key)
    manifest = target.parent / 'motion.json'
    expected = {'size':SIZES[options.aspect],'audio':False,'duration':options.frames/24}
    guardian = input_snapshot.get('guardian')
    if rework := input_snapshot.get('rework'):
        with factory() as db:
            try:
                require_active_plan(db,require(db,StoryVersion,rework['series_version_id']))
            except HTTPException as exc:
                raise ValueError(exc.detail) from exc
    signature_parts = [PIPELINE,item['sha256'],options.model_dump()]
    if guardian:
        signature_parts.append(guardian)
    signature = hashlib.sha256(json.dumps(signature_parts,sort_keys=True).encode()).hexdigest()

    def check():
        update('inspecting',0)
    check()
    if file_hash(source,lambda *_:check())!=item['sha256']:
        raise ValueError('图片源文件已变化')
    if target.is_file():
        prior = json.loads(manifest.read_text(encoding='utf-8'))
        if prior['signature']!=signature or prior['sha256']!=file_hash(target,lambda *_:check()):
            raise ValueError('已发布候选的哈希或参数不匹配')
        validate_output(target,expected)
        return prior

    work.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(work).free<256*1024**2:
        raise OSError('磁盘可用空间不足 256 MiB')
    with factory() as db:
        previous = db.scalars(select(Task).where(Task.asset_id==item['id'],Task.kind=='still_motion',
            Task.status=='succeeded').order_by(Task.created_at.desc()).limit(20)).all()
    cached = None
    for prior in previous:
        if prior.output.get('signature')!=signature:
            continue
        candidate = storage.resolve_key(prior.output['storage_key'])
        if candidate.is_file() and file_hash(candidate,lambda *_:check())==prior.output['sha256']:
            cached = prior
            temporary = candidate
            break
    if not cached:
        demuxer = DEMUXERS[source.suffix.lower()]
        image_dimensions(source,demuxer)
        temporary = work/'motion.mp4'
        steps = options.frames-1
        wobble = {'push_in':f'1+0.12*on/{steps}', 'pull_out':f'1.12-0.12*on/{steps}', 'pan_right':'1.12'}
        x = f'(iw-iw/zoom)*on/{steps}' if options.preset=='pan_right' else '(iw-iw/zoom)/2'
        width,height = expected['size']
        graph = (f"crop='min(iw,ih*{width}/{height})':'min(ih,iw*{height}/{width})',"
                 f'scale={width*2}:{height*2},setsar=1,zoompan=z={wobble[options.preset]}:x={x}:'
                 f'y=(ih-ih/zoom)/2:d={options.frames}:s={width}x{height}:fps=24')
        argv = ['ffmpeg','-hide_banner','-nostdin','-n','-loglevel','warning','-xerror','-filter_threads','2',
                '-progress','pipe:1','-protocol_whitelist','file,pipe','-f',demuxer,'-i',str(source),
                '-map','0:v:0','-vf',graph,'-an','-frames:v',str(options.frames),'-c:v','libx264',
                '-pix_fmt','yuv420p','-crf','19','-preset','veryfast','-threads','2','-movflags','+faststart',str(temporary)]
        write_manifest(work/'command.json',argv)
        execute_ffmpeg(argv,work,expected['duration'],update,timeout=180)
    update('validating',98)
    metadata = validate_output(temporary,expected)
    stream = probe(temporary)['streams'][0]
    if stream['codec_name']!='h264' or int(stream.get('nb_frames',0))!=options.frames or stream['avg_frame_rate']!='24/1':
        raise ValueError('候选编码、帧数或帧率校验失败')
    digest = file_hash(temporary,lambda *_:update('validating',98))
    output = {**metadata,'storage_key':storage_key,'sha256':digest,'signature':signature,
              'pipeline':PIPELINE,'actual_external_cost_micros':0,'reused_from_task_id':cached.id if cached else None}
    if guardian:
        commands = Commands(work,update)
        visual = inspect_video(commands,temporary,options.frames,digest)
        output['guardian_visual'] = visual
        output.update(sample_candidate(temporary,commands,options.frames,visual))
        if screen_text := guardian.get('screen_text'):
            output['guardian_screen_text'] = inspect_screen_text(commands,screen_text,output['files'],digest)
    update('publishing',99)
    target.parent.mkdir(parents=True,exist_ok=True)
    write_manifest(manifest,output)
    os.link(temporary,target)
    if not cached:
        temporary.unlink()
    return output

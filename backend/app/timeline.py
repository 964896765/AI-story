"""Persist a frame-based timeline request and enqueue a fixed local rendering task."""
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select

from .creative import create_entity, pack, require, version_ref
from .db import session
from .models import Asset, Project, StoryEntity, StoryVersion, Task, TaskEvent
from .series import series_report
from .story_schemas import Strict, Timeline

router = APIRouter(prefix='/api/timeline',tags=['multitrack-timeline'])


class Enqueue(Strict):
    version_id: str=Field(min_length=1,max_length=36)
    idempotency_key: str=Field(min_length=1,max_length=60)


class AutoAssemble(Strict):
    series_version_id: str=Field(min_length=1,max_length=36)
    episode: int=Field(ge=1,le=60)
    title: str=Field(min_length=1,max_length=200,pattern=r'.*\S.*')
    profile: str=Field(default='portrait',pattern=r'^(portrait|landscape|square)$')
    idempotency_key: str=Field(min_length=1,max_length=64)


def all_source_versions(db, project_id, content):
    ids = {clip['asset_id'] for track in content['tracks'] if track['enabled'] for clip in track['clips']}
    rows = db.scalars(select(Asset).where(Asset.project_id==project_id,Asset.id.in_(ids))).all()
    if set(item.id for item in rows)!=ids:
        raise HTTPException(422,'时间轴包含不可用素材')
    return {row.id:{'storage_key':row.storage_key,'sha256':row.sha256,'version':row.version}
            for row in rows}


@router.post('/projects/{project_id}/renders',status_code=201)
def render(project_id:str,body:Enqueue,db=Depends(session)):
    if not db.scalar(select(Project).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    _,version = version_ref(db,project_id,body.version_id,{'timeline'})
    timeline = Timeline.model_validate(version.content)
    key = 'render-timeline:'+body.idempotency_key
    previous = db.scalar(select(Task).where(Task.project_id==project_id,Task.idempotency_key==key))
    if previous:
        if previous.kind!='timeline_render' or previous.story_version_id!=version.id:
            raise HTTPException(409,'请求键已用于不同时间轴版本')
        return previous
    if not any(track.role=='main' and track.enabled and track.clips for track in timeline.tracks):
        raise HTTPException(422,'主画面轨道必须含已启用片段')
    task = Task(project_id=project_id,asset_id=None,kind='timeline_render',idempotency_key=key,
        story_version_id=version.id,parameters={'timeline':version.content},input_snapshot={
            'version_hash':version.content_hash,'assets':all_source_versions(db,project_id,version.content)})
    db.add(task)
    db.flush()
    db.add(TaskEvent(task_id=task.id,attempt=0,message='固定版本的多轨渲染任务已排队'))
    db.commit()
    return task


@router.get('/projects/{project_id}/renders')
def renders(project_id:str,db=Depends(session)):
    require(db,Project,project_id)
    return db.scalars(select(Task).where(Task.project_id==project_id,Task.kind=='timeline_render')
                      .order_by(Task.created_at.desc(),Task.id).limit(100)).all()


@router.get('/versions/{version_id}/manifest')
def manifest(version_id:str,db=Depends(session)):
    version = require(db,StoryVersion,version_id)
    entity = require(db,StoryEntity,version.entity_id)
    if entity.kind!='timeline':
        raise HTTPException(422,'只有时间轴版本可导出此清单')
    assets = all_source_versions(db,entity.project_id,version.content)
    return {'format':'ai-story-timeline-v1','version_id':version.id,'title':version.title,
            'content_hash':version.content_hash,'timeline':version.content,
            'assets':{key:{k:v for k,v in item.items() if k!='storage_key'} for key,item in assets.items()}}


@router.post('/projects/{project_id}/assemble',status_code=201)
def assemble(project_id:str,body:AutoAssemble,db=Depends(session)):
    if not db.scalar(select(Project).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    key = 'timeline-assemble:'+body.idempotency_key
    request = body.model_dump(exclude={'idempotency_key'})
    series_entity,series = version_ref(db,project_id,body.series_version_id,{'story_bible'})
    previous = db.scalar(select(StoryEntity).where(StoryEntity.project_id==project_id,StoryEntity.creation_key==key))
    if previous:
        first = db.scalar(select(StoryVersion).where(StoryVersion.entity_id==previous.id,StoryVersion.number==1))
        if first.provenance.get('assembly_request')!=request:
            raise HTTPException(409,'请求键已用于不同的自动剪辑')
        return pack(db,previous,first)
    report = series_report(db,series_entity,series)
    if not report['approved']:
        raise HTTPException(422,'只有已批准的计划可以自动剪辑')
    episode = next((entry for entry in report['episodes'] if entry['number']==body.episode),None)
    if not episode:
        raise HTTPException(422,'所选分集不在固定制作计划中')
    keys = {shot['shot_id'] for shot in episode['shots']}
    assets = db.scalars(select(Asset).where(Asset.project_id==project_id,
        Asset.media_info['story_version_id'].as_string()==series.id)).all()
    by_shot = {}
    for asset in assets:
        shot_id = asset.media_info.get('shot_id')
        if shot_id in keys and asset.media_info.get('origin')=='local_still_motion':
            by_shot.setdefault(shot_id,[]).append(asset)
    clips = []
    for shot in episode['shots']:
        shot_id = shot['shot_id']
        choices = by_shot.get(shot_id,[])
        if len(choices)!=1:
            raise HTTPException(422,f'镜头 {shot_id} 需要唯一已采纳候选，当前 {len(choices)} 条')
        asset=choices[0]
        start = round(shot['start_ms']*24/1000)
        stop = round((shot['start_ms']+shot['duration_ms'])*24/1000)
        frames = stop-start
        if round(asset.media_info['duration']*24)<frames:
            raise HTTPException(422,f'镜头 {shot_id} 采纳候选短于计划时长')
        clips.append({'id':str(uuid5(NAMESPACE_URL,series.id+'/'+shot_id)),'asset_id':asset.id,
                      'at':start,'frames':frames})
    payload = {'source_version_id':series.id,'profile':body.profile,'frames':clips[-1]['at']+clips[-1]['frames'],
               'tracks':[{'id':'video-main','role':'main','clips':clips}]}
    entity,version = create_entity(db,project_id,'timeline',body.title,payload,key,
        provenance={'assembly_request':request,'rule_version':'timeline-auto-v1'})
    db.commit()
    return pack(db,entity,version)

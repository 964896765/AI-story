"""Persist a frame-based timeline request and enqueue a fixed local rendering task."""
from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select

from .creative import append_version, create_entity, pack, require, validate_content, version_ref
from .db import session
from .generation import finished_candidate
from .guardian import candidate_matches, require_active_plan, require_reviewed_timeline
from .models import Asset, Project, StoryEntity, StoryVersion, Task, TaskEvent
from .render import file_hash
from .series import approved_guardian_shot, series_report
from .production_specs import approval_spec, task_fields, verify_profile, verify_timeline
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


class ShotReplacement(Strict):
    series_version_id: str = Field(min_length=1,max_length=36)
    timeline_version_id: str = Field(min_length=1,max_length=36)
    shot_id: str = Field(min_length=1,max_length=48)
    candidate_id: str = Field(min_length=1,max_length=36)
    note: str = Field(min_length=1,max_length=2000,pattern=r'\S')
    idempotency_key: str = Field(min_length=1,max_length=64)


def primary_clips(content):
    return sorted((clip for track in content['tracks'] if track['enabled'] and track['role']=='main'
                   for clip in track['clips']),key=lambda clip:clip['at'])


@router.get('/projects/{project_id}/shot-replacements/options')
def replacement_options(project_id: str,series_version_id: str,shot_id: str,db=Depends(session)):
    series,_,episode,_ = approved_guardian_shot(db,project_id,series_version_id,shot_id)
    editions = select(StoryVersion.id).where(StoryVersion.entity_id==series.id,
                                           StoryVersion.provenance['series_approved'].as_boolean().is_(True))
    asset_ids = set(db.scalars(select(Asset.id).where(
        Asset.project_id==project_id,Asset.media_info['guardian_series_id'].as_string()==series.id,
        Asset.media_info['shot_id'].as_string()==shot_id)))
    rows = db.scalars(select(StoryVersion).join(StoryEntity,StoryEntity.id==StoryVersion.entity_id).where(
        StoryEntity.project_id==project_id,StoryEntity.kind=='timeline',StoryEntity.current_version==StoryVersion.number,
        StoryVersion.content['source_version_id'].as_string().in_(editions))
        .order_by(StoryVersion.created_at.desc(),StoryVersion.id))
    return [{'version_id':row.id,'title':row.title,'version':row.number,'profile':row.content['profile']} for row in rows
            if (row.provenance.get('assembly_request') or {}).get('episode',episode['number'])==episode['number']
            and any(clip['asset_id'] in asset_ids for clip in primary_clips(row.content))]


@router.post('/projects/{project_id}/shot-replacements',status_code=201)
def replace_shot(project_id: str,body: ShotReplacement,db=Depends(session)):
    if not db.scalar(select(Project.id).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    entity,base = version_ref(db,project_id,body.timeline_version_id,{'timeline'})
    entity = db.scalar(select(StoryEntity).where(StoryEntity.id==entity.id).with_for_update()
                       .execution_options(populate_existing=True))
    key = 'guardian-replace:'+body.idempotency_key
    request = body.model_dump(exclude={'idempotency_key'})
    previous = db.scalar(select(StoryVersion).where(StoryVersion.entity_id==entity.id,StoryVersion.request_key==key))
    if previous:
        if (previous.provenance.get('shot_replacement') or {}).get('request')!=request:
            raise HTTPException(409,'请求键已用于其他镜头替换')
        return pack(db,entity,previous)
    if base.number!=entity.current_version:
        raise HTTPException(409,'时间轴已更新，请重新选择当前版本')
    series,target,episode,shot = approved_guardian_shot(db,project_id,body.series_version_id,body.shot_id)
    origin_id = base.content.get('source_version_id')
    if not origin_id:
        raise HTTPException(422,'时间轴缺少固定 Guardian 计划来源')
    origin_entity,origin = version_ref(db,project_id,origin_id,{'story_bible'})
    if origin_entity.id!=series.id or not origin.provenance.get('guardian_manifest'):
        raise HTTPException(422,'时间轴须引用同一故事圣经的已批准 Guardian 版本')
    baseline = episode if origin.id==target.id else next((item for item in series_report(db,series,origin)['episodes']
                                                          if item['number']==episode['number']),None)
    if not baseline or not any(item['shot_id']==body.shot_id for item in baseline['shots']):
        raise HTTPException(422,'原时间轴分集没有对应镜头，请在多轨工作台重新装配')
    require_reviewed_timeline(db,origin,baseline,base.content)
    job,path = finished_candidate(db,body.candidate_id)
    review = job.output.get('guardian_review') or {}
    if (job.project_id!=project_id or job.story_version_id!=target.id or job.parameters.get('shot_id')!=body.shot_id
        or review.get('request',{}).get('decision')!='approved' or review.get('output_sha256')!=job.output['sha256']):
        raise HTTPException(409,'候选须属于当前批准镜头并通过人工内容审核')
    asset = db.scalar(select(Asset).where(Asset.project_id==project_id,Asset.storage_key==job.output['storage_key']))
    if not asset or not candidate_matches(asset,target,shot) or asset.sha256!=job.output['sha256']:
        raise HTTPException(409,'请先采纳已审核候选')
    if file_hash(path)!=asset.sha256:
        raise HTTPException(409,'采纳候选文件校验失败')
    content = deepcopy(base.content)
    clip = next(clip for item,clip in zip(baseline['shots'],primary_clips(content)) if item['shot_id']==body.shot_id)
    old_asset = clip['asset_id']
    if old_asset==asset.id:
        raise HTTPException(422,'所选片段已使用这个候选')
    clip['asset_id'] = asset.id
    content['source_version_id'] = target.id
    require_reviewed_timeline(db,target,episode,content)
    normalized,refs = validate_content(db,project_id,'timeline',content)
    provenance = {'shot_replacement':{'request':request,'old_asset_id':old_asset,'new_asset_id':asset.id,
                                      'episode':episode['number'],'contract_sha256':shot['guardian']['contract_sha256']}}
    if assembly := base.provenance.get('assembly_request'):
        provenance['assembly_request'] = {**assembly,'series_version_id':target.id}
    entity.current_version += 1
    version = append_version(db,entity,base.title,normalized,refs,key,body.note,provenance)
    db.commit()
    return pack(db,entity,version)


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
    task = enqueue_render(db,project_id,version,key,render_snapshot(db,project_id,version,timeline))
    db.commit()
    return task


def render_snapshot(db,project_id,version,timeline):
    spec = approval_spec(db,project_id,version.content)
    verify_timeline(spec,timeline)
    if not any(track.role=='main' and track.enabled and track.clips for track in timeline.tracks):
        raise HTTPException(422,'主画面轨道必须含已启用片段')
    if timeline.source_version_id:
        entity, source = version_ref(db,project_id,timeline.source_version_id,{'storyboard','story_bible'})
        if entity.kind=='story_bible' and source.content.get('guardian'):
            require_active_plan(db,source)
            if not source.provenance.get('guardian_manifest'):
                raise HTTPException(422,'Guardian 整剧渲染须引用批准版本')
            first = min((clip for track in timeline.tracks if track.enabled and track.role=='main'
                         for clip in track.clips),key=lambda clip: clip.at)
            asset = require(db,Asset,first.asset_id)
            report = series_report(db,entity,source)
            episode = next((item for item in report['episodes'] if candidate_matches(asset,source,item['shots'][0])),None)
            if not episode:
                raise HTTPException(422,'主画面未引用批准计划的分集开场镜头')
            require_reviewed_timeline(db,source,episode,version.content)
        if entity.kind=='storyboard' and any(shot.get('contract') for shot in source.content['shots']):
            raise HTTPException(422,'锁定分镜的渲染须引用已批准 Guardian 故事圣经')
    return {'version_hash':version.content_hash,'assets':all_source_versions(db,project_id,version.content),**task_fields(spec)}


def enqueue_render(db,project_id,version,key,snapshot):
    task = Task(project_id=project_id,asset_id=None,kind='timeline_render',idempotency_key=key,
        story_version_id=version.id,parameters={'timeline':version.content},input_snapshot=snapshot)
    db.add(task)
    db.flush()
    db.add(TaskEvent(task_id=task.id,attempt=0,message='固定版本的多轨渲染任务已排队'))
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
    require_active_plan(db,series)
    verify_profile(report.get('production_spec'),body.profile)
    episode = next((entry for entry in report['episodes'] if entry['number']==body.episode),None)
    if not episode:
        raise HTTPException(422,'所选分集不在固定制作计划中')
    shots = {shot['shot_id']:shot for shot in episode['shots']}
    scope = (Asset.media_info['guardian_series_id'].as_string()==series.entity_id if report.get('guardian')
             else Asset.media_info['story_version_id'].as_string()==series.id)
    assets = db.scalars(select(Asset).where(Asset.project_id==project_id,
        scope)).all()
    by_shot = {}
    for asset in assets:
        shot_id = asset.media_info.get('shot_id')
        if shot_id in shots and asset.media_info.get('origin')=='local_still_motion' and candidate_matches(asset,series,shots[shot_id]):
            if report.get('guardian') and asset.media_info.get('guardian_aspect')!=body.profile:
                continue
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

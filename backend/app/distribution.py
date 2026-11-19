"""Manual theater and publication records, plus locally produced promo archives."""
import json
import os
from urllib.parse import urlsplit
from zipfile import ZipFile, ZIP_STORED

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import AwareDatetime, Field, field_validator
from sqlalchemy import select

from . import storage
from .analysis_service import fingerprint
from .creative import require
from .db import session
from .delivery import eligible, make_cover
from .library import Region, Slug
from .models import ChannelProfile, Project, Publication, PublicationEvent, Task, TaskEvent
from .render import RenderOptions, file_hash, render, write_manifest
from .story_schemas import Strict

router=APIRouter(prefix='/api/distribution',tags=['local-distribution'])
TRANSITIONS={'draft':{'planned','cancelled'},'planned':{'submitted','cancelled'},
             'submitted':{'published','rejected','cancelled'},'rejected':{'planned','cancelled'},
             'published':{'withdrawn'},'cancelled':set(),'withdrawn':set()}


class ChannelInput(Strict):
    label: str=Field(min_length=1,max_length=180,pattern=r'.*\S.*')
    organization: str=Field(min_length=1,max_length=300,pattern=r'.*\S.*')
    account_label: str=Field(min_length=1,max_length=120,pattern=r'.*\S.*')
    platform: Slug
    region: Region
    rules_url: str=Field(default='',max_length=700)
    verification_note: str=Field(default='',max_length=4000)
    verified: bool=False
    idempotency_key: str=Field(min_length=1,max_length=64)

    @field_validator('rules_url')
    @classmethod
    def validate_link(cls,value):
        if not value:return value
        url=urlsplit(value)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('规则出处须为无凭据、查询参数或片段的 HTTPS 地址')
        return value


class PublicationInput(Strict):
    channel_id: str=Field(min_length=1,max_length=36)
    delivery_task_id: str=Field(min_length=1,max_length=36)
    title: str=Field(min_length=1,max_length=180,pattern=r'.*\S.*')
    planned_for: AwareDatetime | None=None
    idempotency_key: str=Field(min_length=1,max_length=64)


class EventInput(Strict):
    expected_status: str=Field(min_length=1,max_length=30)
    status: str=Field(min_length=1,max_length=30)
    evidence: str=Field(min_length=6,max_length=4000,pattern=r'.*\S.*')
    idempotency_key: str=Field(min_length=1,max_length=64)


class PromotionInput(Strict):
    delivery_task_id: str=Field(min_length=1,max_length=36)
    episode: int=Field(ge=1,le=60)
    title: str=Field(min_length=1,max_length=180,pattern=r'.*\S.*')
    description: str=Field(min_length=1,max_length=2000,pattern=r'.*\S.*')
    start_seconds: float=Field(ge=0,le=3600)
    duration_seconds: float=Field(ge=.2,le=30)
    idempotency_key: str=Field(min_length=1,max_length=64)


def channel_public(row):
    return {'id':row.id,'label':row.label,'organization':row.details['organization'],
            'account_label':row.details['account_label'],'platform':row.platform,'region':row.region,
            'rule_version':row.revision,'rules_url':row.details['rules_url'],'verified':row.details['verified'],
            'verification_note':row.details['verification_note'],'created_at':row.created_at}


@router.get('/projects/{project_id}/channels')
def channels(project_id:str,db=Depends(session)):
    require(db,Project,project_id)
    return [channel_public(row) for row in db.scalars(select(ChannelProfile).where(
        ChannelProfile.project_id==project_id).order_by(ChannelProfile.created_at.desc(),ChannelProfile.id).limit(100))]


@router.post('/projects/{project_id}/channels',status_code=201)
def create_channel(project_id:str,body:ChannelInput,db=Depends(session)):
    if not db.scalar(select(Project.id).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    data=body.model_dump(exclude={'idempotency_key'})
    digest=fingerprint(data)
    old=db.scalar(select(ChannelProfile).where(ChannelProfile.project_id==project_id,
                  ChannelProfile.request_key==body.idempotency_key))
    if old:
        if old.request_hash!=digest:raise HTTPException(409,'请求键已用于不同渠道')
        return channel_public(old)
    if body.verified and (not body.rules_url or len(body.verification_note.strip())<6):
        raise HTTPException(422,'人工核验必须有规则出处和核验依据')
    latest=db.scalar(select(ChannelProfile).where(ChannelProfile.project_id==project_id,
        ChannelProfile.platform==body.platform).order_by(ChannelProfile.revision.desc()).limit(1))
    row=ChannelProfile(project_id=project_id,label=body.label,platform=body.platform,region=body.region,
          revision=(latest.revision if latest else 0)+1,details=data,request_key=body.idempotency_key,request_hash=digest)
    db.add(row);db.commit()
    return channel_public(row)


def checked_package(db,package_id):
    task=require(db,Task,package_id)
    if task.kind!='delivery' or task.status!='succeeded':
        raise HTTPException(409,'请先生成已验证的授权交付包')
    _,batch,rights=eligible(db,task.parameters,task.input_snapshot['rights'])
    path=storage.resolve_key(task.output['storage_key'])
    if not path.is_file() or path.stat().st_size!=task.output['size_bytes'] or file_hash(path)!=task.output['sha256']:
        raise HTTPException(409,'交付包已经缺失或未通过原文件哈希')
    return task,batch,rights


def public_publication(db,row):
    channel=require(db,ChannelProfile,row.channel_id)
    events=db.scalars(select(PublicationEvent).where(PublicationEvent.publication_id==row.id)
                     .order_by(PublicationEvent.created_at,PublicationEvent.id)).all()
    return {'id':row.id,'title':row.title,'channel':channel_public(channel),'status':row.status,
            'planned_for':row.planned_for,'delivery_task_id':row.delivery_task_id,'mode':'manual_record',
            'events':[{'from_status':item.from_status,'status':item.status,'evidence':item.evidence,
                       'created_at':item.created_at} for item in events]}


@router.get('/projects/{project_id}/publications')
def publications(project_id:str,db=Depends(session)):
    require(db,Project,project_id)
    rows=db.scalars(select(Publication).where(Publication.project_id==project_id)
                   .order_by(Publication.created_at.desc()).limit(50)).all()
    return [public_publication(db,row) for row in rows]


@router.post('/projects/{project_id}/publications',status_code=201)
def create_publication(project_id:str,body:PublicationInput,db=Depends(session)):
    if not db.scalar(select(Project.id).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    digest=fingerprint(body.model_dump(mode='json',exclude={'idempotency_key'}))
    old=db.scalar(select(Publication).where(Publication.project_id==project_id,Publication.request_key==body.idempotency_key))
    if old:
        if old.request_hash!=digest:raise HTTPException(409,'请求键已用于其他发行记录')
        return public_publication(db,old)
    channel=require(db,ChannelProfile,body.channel_id)
    package,_,_=checked_package(db,body.delivery_task_id)
    if channel.project_id!=project_id or package.project_id!=project_id or (
        (channel.platform,channel.region)!=(package.parameters['platform'],package.parameters['region'])
    ):
        raise HTTPException(422,'渠道、交付包和平台地域必须匹配')
    row=Publication(project_id=project_id,channel_id=channel.id,delivery_task_id=package.id,
        title=body.title,planned_for=body.planned_for,request_key=body.idempotency_key,request_hash=digest)
    db.add(row);db.commit()
    return public_publication(db,row)


@router.post('/publications/{publication_id}/events',status_code=201)
def record_event(publication_id:str,body:EventInput,db=Depends(session)):
    row=db.scalar(select(Publication).where(Publication.id==publication_id).with_for_update())
    if not row:raise HTTPException(404,'发行记录不存在')
    prior=db.scalar(select(PublicationEvent).where(PublicationEvent.publication_id==row.id,
                    PublicationEvent.request_key==body.idempotency_key))
    if prior:
        if (prior.from_status,prior.status,prior.evidence)!=(body.expected_status,body.status,body.evidence):
            raise HTTPException(409,'请求键已用于其他状态记录')
        return public_publication(db,row)
    if row.status!=body.expected_status or body.status not in TRANSITIONS[row.status]:
        raise HTTPException(409,'当前发行记录不允许这次状态变化')
    if body.status in ('planned','submitted','published'):
        if not require(db,ChannelProfile,row.channel_id).details['verified']:
            raise HTTPException(409,'渠道的平台规则仍待人工核验')
        checked_package(db,row.delivery_task_id)
    db.add(PublicationEvent(publication_id=row.id,from_status=row.status,status=body.status,
                    evidence=body.evidence,request_key=body.idempotency_key))
    row.status=body.status
    db.commit()
    return public_publication(db,row)


def promo_public(task):
    return {'id':task.id,'status':task.status,'error':task.error,'title':task.parameters['title'],
            'episode':task.parameters['episode'],'sha256':task.output.get('sha256'),'created_at':task.created_at}


@router.get('/projects/{project_id}/promotions')
def promotions(project_id:str,db=Depends(session)):
    require(db,Project,project_id)
    return [promo_public(task) for task in db.scalars(select(Task).where(Task.project_id==project_id,
        Task.kind=='promotion').order_by(Task.created_at.desc()).limit(100))]


@router.post('/projects/{project_id}/promotions',status_code=201)
def create_promotion(project_id:str,body:PromotionInput,db=Depends(session)):
    if not db.scalar(select(Project.id).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    params=body.model_dump(exclude={'idempotency_key'})
    key='promotion:'+body.idempotency_key
    old=db.scalar(select(Task).where(Task.project_id==project_id,Task.idempotency_key==key))
    if old:
        if old.kind!='promotion' or old.parameters!=params:raise HTTPException(409,'请求键已用于其他推广包')
        return promo_public(old)
    package,report,rights=checked_package(db,body.delivery_task_id)
    if package.project_id!=project_id:raise HTTPException(422,'交付包不属于当前项目')
    unit=next((entry for entry in report['episodes'] if entry['number']==body.episode),None)
    if not unit:raise HTTPException(422,'交付包没有该分集')
    source=require(db,Task,unit['render_task_id'])
    if body.start_seconds+body.duration_seconds>source.output['duration']:
        raise HTTPException(422,'推广区间超过原成片时长')
    task=Task(project_id=project_id,kind='promotion',story_version_id=source.story_version_id,
              parameters=params,idempotency_key=key,input_snapshot={'video':{
                  'storage_key':source.output['storage_key'],'sha256':source.output['sha256']},'rights':rights})
    db.add(task);db.flush()
    db.add(TaskEvent(task_id=task.id,attempt=0,message='推广包已排队，来源为已授权固定成片'))
    db.commit()
    return promo_public(task)


@router.get('/promotions/{task_id}/file')
def promo_file(task_id:str,db=Depends(session)):
    task=require(db,Task,task_id)
    if task.kind!='promotion' or task.status!='succeeded':
        raise HTTPException(409,'推广包待验证')
    checked_package(db,task.parameters['delivery_task_id'])
    path=storage.resolve_key(task.output['storage_key'])
    if not path.is_file() or file_hash(path)!=task.output['sha256']:
        raise HTTPException(404,'推广包缺失或未通过哈希校验')
    return FileResponse(path,media_type='application/zip',filename='promo-'+task.id+'.zip',
                        headers={'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})


def render_promotion(task_id,attempt,params,snapshot,update,factory):
    with factory() as db:
        try:
            _,_,rights=checked_package(db,params['delivery_task_id'])
        except HTTPException as exc:
            raise ValueError(str(exc.detail)) from None
        if rights!=snapshot['rights']:raise ValueError('授权记录已变化')
    options=RenderOptions(start=params['start_seconds'],duration=params['duration_seconds']).model_dump()
    result=render(task_id,attempt,options,{'video':snapshot['video']},update)
    source=storage.resolve_key(result['storage_key'])
    target=storage.resolve_key(f'outputs/{task_id}/promotion.zip')
    log=target.parent/'promotion.json'
    if target.exists():
        saved=json.loads(log.read_text(encoding='utf-8'))
        if file_hash(target)!=saved['sha256']:raise ValueError('推广 ZIP 未通过原哈希')
        return saved
    work=storage.resolve_key(f'tmp/{task_id}/{attempt}')
    cover=work/'cover.jpg'
    make_cover(source,cover)
    meta={'source_delivery_id':params['delivery_task_id'],'episode':params['episode'],'title':params['title'],
          'description':params['description'],'start_seconds':params['start_seconds'],'duration_seconds':params['duration_seconds'],
          'files':{'highlight.mp4':file_hash(source),'cover.jpg':file_hash(cover)},'status':'manual_review'}
    partial=work/'promotion.zip'
    with ZipFile(partial,'x',ZIP_STORED) as archive:
        archive.write(source,'highlight.mp4');archive.write(cover,'cover.jpg')
        archive.writestr('manifest.json',json.dumps(meta,ensure_ascii=False).encode('utf-8'))
    with ZipFile(partial) as archive:
        if archive.testzip() is not None:raise ValueError('推广包 CRC 校验失败')
    payload={'storage_key':f'outputs/{task_id}/promotion.zip','sha256':file_hash(partial),
             'size_bytes':partial.stat().st_size,'manifest':meta}
    update('publishing',99)
    write_manifest(log,payload);os.link(partial,target);partial.unlink()
    return payload

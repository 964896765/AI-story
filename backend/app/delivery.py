"""Rights-gated packaging of verified production runs."""
from hashlib import sha256
import json
import os
import shutil
import subprocess
from zipfile import ZipFile, ZIP_STORED

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy import select

from . import storage
from .analysis_service import fingerprint
from .creative import require
from .db import session
from .library import Region, Slug, latest_rights, restriction
from .models import Asset, ProductionRun, Project, StoryReference, Task, TaskEvent, now
from .production import public as run_public
from .render import file_hash, write_manifest
from .story_schemas import Strict

router=APIRouter(prefix='/api/delivery',tags=['verified-delivery'])
SCHEMA='ai-story-delivery-v1'


class Packaging(Strict):
    run_id: str=Field(min_length=1,max_length=36)
    title: str=Field(min_length=1,max_length=180,pattern=r'.*\S.*')
    platform: Slug
    region: Region
    idempotency_key: str=Field(min_length=1,max_length=60)


def source_lineage(db,project,asset_ids,versions):
    visited_versions, items = set(), {}
    assets=set(asset_ids)
    pending=set(versions)
    while pending or assets:
        if pending:
            visited_versions|=pending
            if len(visited_versions)>6000:
                raise HTTPException(422,'此交付范围的创作引用超过 6000 条')
            refs=db.scalars(select(StoryReference).where(StoryReference.from_version_id.in_(pending))).all()
            pending={row.target_version_id for row in refs if row.target_version_id and row.target_version_id not in visited_versions}
            assets|={row.asset_id for row in refs if row.asset_id and row.asset_id not in items}
        if assets:
            records=db.scalars(select(Asset).where(Asset.project_id==project,Asset.id.in_(assets))).all()
            if {asset.id for asset in records}!=assets:
                raise HTTPException(422,'交付来源包含跨项目或缺失素材')
            items.update((asset.id,asset) for asset in records)
            assets=set()
            for asset in records:
                for role in ('derived_from_asset','generated_from_asset'):
                    parent=asset.media_info.get(role)
                    if isinstance(parent,str) and parent not in items:
                        assets.add(parent)
                version=asset.media_info.get('story_version_id')
                if isinstance(version,str) and version not in visited_versions:
                    pending.add(version)
    return items


def authorization_manifest(db,run,units,platform,region):
    assets=set()
    versions={run.plan_version_id}
    for unit in units:
        task=require(db,Task,unit['render_task_id'])
        versions.add(task.story_version_id)
        assets.update(task.input_snapshot['assets'])
    items=source_lineage(db,run.project_id,assets,versions)
    latest=latest_rights(db,items.keys())
    current=now()
    blockers=[]
    result=[]
    for key,asset in sorted(items.items()):
        right=latest.get(key)
        problem=restriction(right,platform,region,current)
        if problem:
            blockers.append({'asset_id':key,'name':asset.name,'reason':problem})
            continue
        result.append({
            'asset_id':key,'asset_sha256':asset.sha256,'right_id':right.id,'revision':right.revision,
            'holder':right.holder,'source_type':right.source_type,
            'starts_at':right.starts_at.isoformat() if right.starts_at else None,
            'expires_at':right.expires_at.isoformat() if right.expires_at else None,
            'platform':platform,'region':region,'scope':right.scope,
        })
    if blockers:
        raise HTTPException(409,{'message':'交付授权尚未通过','assets':blockers})
    return result


def eligible(db,params,expected=None):
    run=require(db,ProductionRun,params['run_id'])
    report=run_public(db,run)
    if report['status']!='passed':
        raise HTTPException(409,'整剧须通过全部技术质检和要求的人工复核')
    rights=authorization_manifest(db,run,report['episodes'],params['platform'],params['region'])
    if expected is not None and rights!=expected:
        raise HTTPException(409,'授权记录已更新，请重新提交交付')
    return run,report,rights


def public(task):
    return {'id':task.id,'status':task.status,'stage':task.stage,'error':task.error,
            'parameters':task.parameters,'created_at':task.created_at,'sha256':task.output.get('sha256'),
            'size_bytes':task.output.get('size_bytes')}


@router.post('/projects/{project_id}/packages',status_code=201)
def submit(project_id:str,body:Packaging,db=Depends(session)):
    if not db.scalar(select(Project.id).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    key='delivery:'+body.idempotency_key
    params=body.model_dump(exclude={'idempotency_key'})
    previous=db.scalar(select(Task).where(Task.project_id==project_id,Task.idempotency_key==key))
    if previous:
        if previous.kind!='delivery' or previous.parameters!=params:
            raise HTTPException(409,'请求键已用于其他交付')
        return public(previous)
    run=require(db,ProductionRun,body.run_id)
    if run.project_id!=project_id:
        raise HTTPException(422,'生产批次不属于当前项目')
    _,report,rights=eligible(db,params)
    task=Task(project_id=project_id,kind='delivery',story_version_id=run.plan_version_id,
              parameters=params,idempotency_key=key,input_snapshot={'rights':rights,
              'qc_files':[unit['qc']['output_sha256'] for unit in report['episodes']]})
    db.add(task);db.flush()
    db.add(TaskEvent(task_id=task.id,attempt=0,message='权利和技术质检已核对，交付任务已排队'))
    db.commit()
    return public(task)


@router.get('/projects/{project_id}/packages')
def packages(project_id:str,db=Depends(session)):
    require(db,Project,project_id)
    return [public(task) for task in db.scalars(select(Task).where(Task.project_id==project_id,
        Task.kind=='delivery').order_by(Task.created_at.desc()).limit(100))]


@router.get('/packages/{task_id}/file')
def download(task_id:str,db=Depends(session)):
    task=require(db,Task,task_id)
    if task.kind!='delivery' or task.status!='succeeded':
        raise HTTPException(409,'交付包没有完成验证')
    eligible(db,task.parameters,task.input_snapshot['rights'])
    path=storage.resolve_key(task.output['storage_key'])
    if not path.is_file() or path.stat().st_size!=task.output['size_bytes'] or file_hash(path)!=task.output['sha256']:
        raise HTTPException(404,'交付包不存在或不完整')
    return FileResponse(path,media_type='application/zip',filename='ai-story-'+task.id+'.zip',
                        headers={'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})


def make_cover(src,dst):
    result=subprocess.run(['ffmpeg','-hide_banner','-v','error','-nostdin','-n','-protocol_whitelist','file,pipe',
        '-i',str(src),'-map','0:v:0','-vf','scale=320:-2','-frames:v','1','-update','1',str(dst)],
        capture_output=True,timeout=30)
    if result.returncode or not dst.is_file() or dst.stat().st_size<12:
        raise ValueError('无法从已质检成片提取封面')


def deliver(task_id,attempt,params,snapshot,update,factory):
    key=f'outputs/{task_id}/delivery.zip'
    target=storage.resolve_key(key)
    signature=fingerprint([SCHEMA,params,snapshot])
    with factory() as db:
        try:
            _,report,rights=eligible(db,params,snapshot['rights'])
        except HTTPException as exc:
            raise ValueError(json.dumps(exc.detail,ensure_ascii=False)) from None
        units=report['episodes']
        if [unit['qc']['output_sha256'] for unit in units]!=snapshot['qc_files']:
            raise ValueError('生产质检依据已变化')
        batches=[]
        for unit in units:
            render=require(db,Task,unit['render_task_id'])
            batches.append((unit,render.output,render.parameters['timeline'],render.attempt))
    manifest_file=target.parent/'delivery.json'
    if target.is_file():
        saved=json.loads(manifest_file.read_text(encoding='utf-8'))
        if saved['signature']!=signature or saved['sha256']!=file_hash(target,lambda *_:update('delivery_verify',95)):
            raise ValueError('已发布交付包校验失败')
        return saved
    work=storage.resolve_key(f'tmp/{task_id}/{attempt}')
    work.mkdir(parents=True,exist_ok=True)
    total=sum(output['size_bytes'] for _,output,_,_ in batches)
    if shutil.disk_usage(work).free < max(256*1024**2,total+128*1024**2):
        raise OSError('交付磁盘空间不足')
    temporary=work/'delivery.zip'
    files=[]
    with ZipFile(temporary,'x',compression=ZIP_STORED,allowZip64=True) as archive:
        def store(name,source=None,data=None,expected=None):
            digest=sha256()
            size=0
            if source:
                with archive.open(name,'w',force_zip64=True) as out, source.open('rb') as inp:
                    for chunk in iter(lambda:inp.read(1024*1024),b''):
                        out.write(chunk)
                        digest.update(chunk)
                        size+=len(chunk)
                        update('delivery_pack',40)
            else:
                archive.writestr(name,data)
                digest.update(data)
                size=len(data)
            if expected and digest.hexdigest()!=expected:
                raise ValueError('交付读到的成片与质检哈希不一致')
            files.append({'path':name,'sha256':digest.hexdigest(),'size_bytes':size})
        def save_json(name,payload):
            store(name,data=json.dumps(payload,ensure_ascii=False,sort_keys=True,indent=2).encode('utf-8'))
        for unit,output,timeline,render_attempt in batches:
            prefix=f"episode-{unit['number']:03d}"
            src=storage.resolve_key(output['storage_key'])
            store(prefix+'/video.mp4',source=src,expected=unit['qc']['output_sha256'])
            image=work/(prefix+'.jpg')
            make_cover(src,image)
            store(prefix+'/cover.jpg',source=image)
            if any(track['role']=='caption' and track['enabled'] for track in timeline['tracks']):
                caption_key=output.get('caption_storage_key') or f"tmp/{unit['render_task_id']}/{render_attempt}/timeline.srt"
                captions=storage.resolve_key(caption_key)
                if captions.is_file():
                    store(prefix+'/subtitles.srt',source=captions,expected=output.get('caption_sha256'))
            save_json(prefix+'/timeline.json',{'version_id':unit['timeline_version_id'],'timeline':timeline})
            save_json(prefix+'/quality.json',{'technical':unit['qc'],'human_review':unit['review']})
        save_json('rights.json',rights)
        archive.writestr('manifest.json',json.dumps({'schema':SCHEMA,'run_id':params['run_id'],'title':params['title'],
            'platform':params['platform'],'region':params['region'],'files':files},ensure_ascii=False,indent=2).encode('utf-8'))
    with ZipFile(temporary,'r') as archive:
        for entry in files:
            check=sha256()
            with archive.open(entry['path']) as item:
                for chunk in iter(lambda:item.read(1024*1024),b''):
                    check.update(chunk)
                    update('delivery_verify',90)
            if check.hexdigest()!=entry['sha256']:
                raise ValueError('ZIP 内部文件校验失败')
    result={'storage_key':key,'sha256':file_hash(temporary,lambda *_:update('delivery_verify',95)),
            'size_bytes':temporary.stat().st_size,'files':files,'signature':signature,'schema':SCHEMA}
    update('delivery_publish',98)
    with factory() as db:
        try:
            eligible(db,params,snapshot['rights'])
        except HTTPException as exc:
            raise ValueError(json.dumps(exc.detail,ensure_ascii=False)) from None
    target.parent.mkdir(parents=True,exist_ok=True)
    write_manifest(manifest_file,result)
    os.link(temporary,target)
    temporary.unlink()
    return result

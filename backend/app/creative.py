"""Versioned creative assets. Deterministic draft tools never impersonate AI."""
import hashlib
import json
import re
import difflib
from pathlib import Path
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import select,func
from sqlalchemy.orm import defer
from .db import session
from .models import Project,Asset,StoryEntity,StoryVersion,StoryReference,StoryOperation,Task
from .story_schemas import CONTENT_MODELS,Kind,Shot,EntityInput,VersionInput,RestoreInput,DeriveInput
from .model_adapters import adapter_for,ModelRequest
from .production_specs import resolve as resolve_spec

router=APIRouter(prefix='/api',tags=['creative'])
IMAGES={'.png','.jpg','.jpeg','.webp'}
VIDEO={'.mp4','.mov','.mkv','.webm','.avi'}
MAX_EXPORT_BYTES=20*1024**2

def require(db,model,key):
    row=db.get(model,key)
    if not row:raise HTTPException(404,'记录不存在')
    return row

def pack(db,entity,version,include_content=True):
    return {'id':entity.id,'project_id':entity.project_id,'kind':entity.kind,'current_version':entity.current_version,'version':version.number,'version_id':version.id,'title':version.title,'content':version.content if include_content else None,'content_hash':version.content_hash,'note':version.note,'provenance':version.provenance,'created_at':version.created_at}

def version_ref(db,project_id,version_id,kinds=None):
    version=require(db,StoryVersion,version_id)
    entity=require(db,StoryEntity,version.entity_id)
    if entity.project_id!=project_id:raise HTTPException(422,'不允许跨项目引用创作版本')
    if kinds and entity.kind not in kinds:raise HTTPException(422,'引用的创作资产类型不符')
    return entity,version

def validate_content(db,project_id,kind,content):
    try:normalized=CONTENT_MODELS[kind].model_validate(content).model_dump()
    except ValidationError as exc:raise HTTPException(422,str(exc)) from exc
    if len(json.dumps(normalized,ensure_ascii=False).encode())>2*1024**2:raise HTTPException(422,'创作内容超过2 MiB限制')
    refs=[]
    def version(role,key,kinds=None):
        if key:
            version_ref(db,project_id,key,kinds)
            refs.append((role,key,None))
    def asset(role,key,suffixes):
        if key:
            row=require(db,Asset,key)
            if row.project_id!=project_id:raise HTTPException(422,'不允许跨项目引用素材')
            if Path(row.storage_key).suffix.lower() not in suffixes:raise HTTPException(422,'引用素材格式不符')
            refs.append((role,None,key))
    spec_id = normalized.get('production_spec_version_id')
    source_id = normalized.get('source_version_id') or normalized.get('script_version_id')
    if source_id and (not spec_id or kind=='timeline'):
        source_spec = version_ref(db,project_id,source_id)[1].content.get('production_spec_version_id')
        if kind=='timeline' and spec_id and source_spec!=spec_id:
            raise HTTPException(422,'时间轴规格须与来源版本一致')
        if source_spec and not spec_id:
            spec_id = normalized['production_spec_version_id'] = source_spec
    if spec_id:
        resolve_spec(db,project_id,spec_id)
    if kind=='novel':asset('source_text',normalized['source_asset_id'],{'.txt'})
    if kind in ('character','scene'):
        for key in normalized['reference_asset_ids']:asset('reference_image',key,IMAGES)
    if kind=='character':asset('voice_reference',normalized['voice']['reference_audio_asset_id'],{'.wav','.mp3'})
    if kind=='character' and normalized['identity'] is None:
        normalized.pop('identity')
    if kind in ('script','episode'):
        version('source',normalized['source_version_id'],{'novel','script','episode'})
        for key in normalized['character_version_ids']:version('character',key,{'character'})
        for key in normalized['scene_version_ids']:version('scene',key,{'scene'})
    if kind=='relationship':
        for item in normalized['relationships']:
            version('from_character',item['from_character_version_id'],{'character'})
            version('to_character',item['to_character_version_id'],{'character'})
    if kind=='storyboard':
        version('source',normalized['source_version_id'],{'script','episode'})
        old_fields={'number','description','dialogue','planned_duration','scene_version_id','character_version_ids'}
        for shot in normalized['shots']:
            version(f"shot:{shot['number']}:scene",shot['scene_version_id'],{'scene'})
            for key in shot['character_version_ids']:version(f"shot:{shot['number']}:character",key,{'character'})
            contract=shot['contract']
            if contract:
                if contract['screen_text'] is None:
                    contract.pop('screen_text')
                for key in contract['source_image_asset_ids']:asset(f"shot:{shot['number']}:source_image",key,IMAGES)
                for state in contract['opening']+contract['closing']:
                    version(f"shot:{shot['number']}:state",state['character_version_id'],{'character'})
            # Legacy request hashes include exactly the original shot keys and defaults.
            for field, definition in Shot.model_fields.items():
                if field not in old_fields and shot[field]==definition.default:
                    shot.pop(field)
    if kind=='story_bible':
        version('series_source',normalized['script_version_id'],{'script'})
        canon=normalized['guardian']
        if canon:
            for key in canon['character_version_ids']:version('guardian:character',key,{'character'})
            for key in canon['scene_version_ids']:version('guardian:scene',key,{'scene'})
            for key in canon['style']['reference_asset_ids']:asset('guardian:style',key,IMAGES)
        else:
            normalized.pop('guardian')
        for index, block in enumerate(normalized['episodes'],1):
            version(f'series:{index}:episode',block['episode_version_id'],{'episode'})
            version(f'series:{index}:board',block['storyboard_version_id'],{'storyboard'})
            for state in block['opener']+block['closer']:
                version(f'series:{index}:character',state['character_version_id'],{'character'})
                version(f'series:{index}:scene',state['scene_version_id'],{'scene'})
    if kind=='timeline':
        version('timeline_source',normalized['source_version_id'],{'storyboard','story_bible'})
        for track in normalized['tracks']:
            role=track['role']
            suffixes=(VIDEO | IMAGES if role in ('main','overlay') else
                      {'.srt'} if role=='caption' else VIDEO | {'.wav','.mp3'})
            for clip in track['clips']:
                asset('timeline:'+role,clip['asset_id'],suffixes)
    if kind=='generation_plan':
        for key in normalized['input_version_ids']:version('generation_input',key)
    refs=list(dict.fromkeys(refs))
    if len(refs)>500:raise HTTPException(422,'单版本最多500条引用')
    return normalized,refs

def digest(kind,title,content):
    return hashlib.sha256(json.dumps({'kind':kind,'title':title,'content':content},sort_keys=True,ensure_ascii=False).encode()).hexdigest()

def append_version(db,entity,title,content,refs,key,note='',provenance=None):
    version=StoryVersion(entity_id=entity.id,number=entity.current_version,title=title,content=content,content_hash=digest(entity.kind,title,content),request_key=key,note=note,provenance=provenance or {})
    db.add(version);db.flush()
    for role,target,asset in refs:db.add(StoryReference(from_version_id=version.id,target_version_id=target,asset_id=asset,role=role))
    return version

def create_entity(db,project_id,kind,title,content,key,note='',provenance=None):
    normalized,refs=validate_content(db,project_id,kind,content)
    previous=db.scalar(select(StoryEntity).where(StoryEntity.project_id==project_id,StoryEntity.creation_key==key))
    if previous:
        first=db.scalar(select(StoryVersion).where(StoryVersion.entity_id==previous.id,StoryVersion.number==1))
        if first.content_hash!=digest(kind,title,normalized) or first.note!=note:raise HTTPException(409,'创建幂等键已用于不同内容')
        return previous,first
    entity=StoryEntity(project_id=project_id,kind=kind,creation_key=key)
    db.add(entity);db.flush()
    return entity,append_version(db,entity,title,normalized,refs,key,note,provenance)

@router.get('/projects/{project_id}/story/entities')
def list_entities(project_id:str,offset:int=0,limit:int=200,kind:Kind|None=None,db=Depends(session)):
    require(db,Project,project_id)
    if not 0<=offset or not 1<=limit<=200:raise HTTPException(422,'分页范围无效')
    scope=[StoryEntity.project_id==project_id]
    if kind:scope.append(StoryEntity.kind==kind)
    rows=db.execute(select(StoryEntity,StoryVersion).options(defer(StoryVersion.content)).join(StoryVersion,StoryVersion.entity_id==StoryEntity.id).where(*scope,StoryVersion.number==StoryEntity.current_version).order_by(StoryEntity.created_at.desc()).offset(offset).limit(limit)).all()
    total=db.scalar(select(func.count()).select_from(StoryEntity).where(*scope))
    return {'items':[pack(db,e,v,False) for e,v in rows],'total':total}

@router.post('/projects/{project_id}/story/entities',status_code=201)
def new_entity(project_id:str,body:EntityInput,db=Depends(session)):
    if not db.scalar(select(Project).where(Project.id==project_id).with_for_update()):raise HTTPException(404,'项目不存在')
    entity,version=create_entity(db,project_id,body.kind,body.title,body.content,body.idempotency_key,body.note)
    db.commit();return pack(db,entity,version)

@router.get('/story/entities/{entity_id}/versions')
def versions(entity_id:str,offset:int=0,limit:int=100,include_content:bool=False,db=Depends(session)):
    entity=require(db,StoryEntity,entity_id)
    if offset<0 or not 1<=limit<=100:raise HTTPException(422,'分页范围无效')
    if include_content and limit>10:raise HTTPException(422,'带正文的历史请求每次最多10项')
    query=select(StoryVersion).where(StoryVersion.entity_id==entity_id).order_by(StoryVersion.number.desc()).offset(offset).limit(limit)
    if not include_content:query=query.options(defer(StoryVersion.content))
    rows=db.scalars(query).all()
    return [pack(db,entity,v,include_content) for v in rows]

@router.get('/story/versions/{version_id}')
def get_version(version_id:str,db=Depends(session)):
    version=require(db,StoryVersion,version_id)
    entity=require(db,StoryEntity,version.entity_id)
    return pack(db,entity,version)

@router.get('/story/entities/{entity_id}/compare')
def compare_versions(entity_id:str,left:int,right:int,db=Depends(session)):
    require(db,StoryEntity,entity_id)
    rows={v.number:v for v in db.scalars(select(StoryVersion).where(StoryVersion.entity_id==entity_id,StoryVersion.number.in_([left,right])))}
    if left not in rows or right not in rows:raise HTTPException(404,'比较版本不存在')
    def readable(version):
        def walk(value,key):
            if isinstance(value,dict):
                return '\n'.join(walk(v,f'{key}.{k}') for k,v in sorted(value.items()))
            return key+':\n'+(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2))
        return ('标题：'+version.title+'\n'+walk(version.content,'content')).splitlines(keepends=True)
    delta=''.join(difflib.unified_diff(readable(rows[left]),readable(rows[right]),fromfile=f'v{left}',tofile=f'v{right}'))
    return {'left_version_id':rows[left].id,'right_version_id':rows[right].id,'diff':delta[:262144],'truncated':len(delta)>262144}

@router.post('/story/entities/{entity_id}/versions',status_code=201)
def save_version(entity_id:str,body:VersionInput,db=Depends(session)):
    entity=db.scalar(select(StoryEntity).where(StoryEntity.id==entity_id).with_for_update())
    if not entity:raise HTTPException(404,'创作资产不存在')
    requested = body.content
    if 'production_spec_version_id' not in requested:
        base = db.scalar(select(StoryVersion).where(
            StoryVersion.entity_id==entity_id,StoryVersion.number==body.expected_version))
        if base and (key := base.content.get('production_spec_version_id')):
            requested = {**requested,'production_spec_version_id':key}
    content,refs=validate_content(db,entity.project_id,entity.kind,requested)
    previous=db.scalar(select(StoryVersion).where(StoryVersion.entity_id==entity_id,StoryVersion.request_key==body.idempotency_key))
    if previous:
        if previous.content_hash!=digest(entity.kind,body.title,content) or previous.note!=body.note:raise HTTPException(409,'版本幂等键已用于不同内容')
        return pack(db,entity,previous)
    if entity.current_version!=body.expected_version:raise HTTPException(409,'版本已被其他编辑更新，请刷新后合并，未覆盖已有内容')
    entity.current_version+=1
    version=append_version(db,entity,body.title,content,refs,body.idempotency_key,body.note)
    db.commit();return pack(db,entity,version)

@router.post('/story/entities/{entity_id}/restore',status_code=201)
def restore_version(entity_id:str,body:RestoreInput,db=Depends(session)):
    entity=db.scalar(select(StoryEntity).where(StoryEntity.id==entity_id).with_for_update())
    if not entity:raise HTTPException(404,'创作资产不存在')
    target=db.scalar(select(StoryVersion).where(StoryVersion.entity_id==entity_id,StoryVersion.number==body.version))
    if not target:raise HTTPException(404,'历史版本不存在')
    previous=db.scalar(select(StoryVersion).where(StoryVersion.entity_id==entity_id,StoryVersion.request_key==body.idempotency_key))
    if previous:
        if previous.provenance.get('restored_from')!=target.id:raise HTTPException(409,'恢复幂等键冲突')
        return pack(db,entity,previous)
    if entity.current_version!=body.expected_version:raise HTTPException(409,'当前版本已变化，请刷新')
    content,refs=validate_content(db,entity.project_id,entity.kind,target.content)
    refs.append(('restored_from',target.id,None))
    entity.current_version+=1
    version=append_version(db,entity,target.title,content,refs,body.idempotency_key,f'从版本{body.version}恢复',{'restored_from':target.id})
    db.commit();return pack(db,entity,version)

def split_units(text,limit):
    parts=[p.strip() for p in re.split(r'\n\s*\n',text) if p.strip()]
    chunks=[];current=''
    for part in parts:
        for index in range(0,len(part),limit):
            piece=part[index:index+limit]
            if current and len(current)+len(piece)+2>limit:chunks.append(current);current=''
            current=(current+'\n\n'+piece).strip()
    if current:chunks.append(current)
    return chunks

@router.post('/projects/{project_id}/story/derive',status_code=201)
def derive(project_id:str,body:DeriveInput,db=Depends(session)):
    if not db.scalar(select(Project).where(Project.id==project_id).with_for_update()):raise HTTPException(404,'项目不存在')
    request=body.model_dump(exclude={'idempotency_key'})
    previous=db.scalar(select(StoryOperation).where(StoryOperation.project_id==project_id,StoryOperation.request_key==body.idempotency_key))
    if previous:
        if previous.request!=request:raise HTTPException(409,'整理操作幂等键冲突')
        result=[]
        for vid in previous.result_version_ids:
            entity,version=version_ref(db,project_id,vid);result.append(pack(db,entity,version))
        return {'method':'local_rules','ai_generated':False,'items':result}
    source,version=version_ref(db,project_id,body.source_version_id)
    text=version.content.get('text') or version.content.get('body')
    if not text:raise HTTPException(422,'来源版本没有可整理的文本')
    specifications=[]
    source_ref={'source_version_id':version.id,'character_version_ids':version.content.get('character_version_ids',[]),'scene_version_ids':version.content.get('scene_version_ids',[])}
    if body.operation=='structure_script':
        if source.kind not in ('novel','script','episode'):raise HTTPException(422,'来源须为小说、剧本或分集')
        specifications=[('script',version.title+' · 规则整理草稿',{'body':text,'summary':'保留原文的结构草稿，未进行AI改写；须人工审核',**source_ref})]
    elif body.operation=='split_episodes':
        if source.kind!='script':raise HTTPException(422,'分集来源须为剧本')
        units=split_units(text,body.unit_chars)
        if len(units)>50:raise HTTPException(422,'单次最多50集，请增加分集字数或缩小来源')
        specifications=[('episode',f'{version.title[:150]} · 第{i}集草稿',{'number':i,'body':part,'summary':'规则拆分，须人工检查剧情衔接',**source_ref}) for i,part in enumerate(units,1)]
    else:
        if source.kind not in ('script','episode'):raise HTTPException(422,'分镜来源须为剧本或分集')
        units=split_units(text,min(body.unit_chars,1000))
        if len(units)>200:raise HTTPException(422,'单次最多200镜头，请缩小来源')
        specifications=[('storyboard',version.title[:175]+' · 分镜草稿',{'source_version_id':version.id,'shots':[{'number':i,'description':part,'dialogue':'','planned_duration':3,'scene_version_id':None,'character_version_ids':[]} for i,part in enumerate(units,1)]})]
    results=[]
    operation=StoryOperation(project_id=project_id,request_key=body.idempotency_key,request=request,result_version_ids=[])
    db.add(operation);db.flush()
    for index,(kind,title,content) in enumerate(specifications):
        entity,result=create_entity(db,project_id,kind,title[:200],content,f'operation:{operation.id}:{index}','规则工具草稿，非AI生成',{'method':'local_rules','source_version_id':version.id,'operation':body.operation})
        results.append((entity,result))
    operation.result_version_ids=[v.id for _,v in results]
    db.commit()
    return {'method':'local_rules','ai_generated':False,'items':[pack(db,e,v) for e,v in results]}

@router.get('/model-capabilities')
def capabilities():
    return {'enabled':False,'capabilities':['text','speech','image','video'],'providers':[],
        'text_governance':'/api/text/status','note':'默认模型仍禁用；文本模拟与可配置兼容接口见剧情改编，真实调用须单独授权；语音、图片、视频未接入'}

@router.get('/story/entities/{entity_id}/model-estimate')
def model_estimate(entity_id:str,version:int|None=None,db=Depends(session)):
    entity=require(db,StoryEntity,entity_id)
    if entity.kind!='generation_plan':raise HTTPException(422,'此资产不是模型输入计划')
    saved=db.scalar(select(StoryVersion).where(StoryVersion.entity_id==entity_id,StoryVersion.number==(version if version is not None else entity.current_version)))
    if not saved:raise HTTPException(404,'计划版本不存在')
    request=ModelRequest(entity.project_id,saved.id,saved.content['capability'],saved.content['prompt'],tuple(saved.content['input_version_ids']))
    return adapter_for().estimate(request)

@router.get('/projects/{project_id}/story/export')
def export_project(project_id:str,db=Depends(session)):
    require(db,Project,project_id)
    current=list(db.scalars(select(StoryVersion.id).join(StoryEntity,StoryVersion.entity_id==StoryEntity.id).where(StoryEntity.project_id==project_id,StoryVersion.number==StoryEntity.current_version).limit(1001)))
    if len(current)>1000:raise HTTPException(422,'当前资产超过1000项，请通过分页API分批读取')
    pending=list(current)
    pending+=list(db.scalars(select(Task.story_version_id).where(Task.project_id==project_id,Task.story_version_id.is_not(None))))
    found={};assets={};used_bytes=0
    from fastapi.encoders import jsonable_encoder
    while pending:
        key=pending.pop()
        if key in found:continue
        if len(found)>=1000:raise HTTPException(422,'导出超过1000个依赖版本，请按版本API分批读取')
        entity,version=version_ref(db,project_id,key)
        found[key]=pack(db,entity,version)
        used_bytes+=len(json.dumps(jsonable_encoder(found[key]),ensure_ascii=False).encode())
        if used_bytes>MAX_EXPORT_BYTES:raise HTTPException(422,'导出超过20 MiB，请按版本API分批读取')
        for ref in db.scalars(select(StoryReference).where(StoryReference.from_version_id==key)):
            if ref.target_version_id:pending.append(ref.target_version_id)
            if ref.asset_id:
                asset=require(db,Asset,ref.asset_id)
                assets[asset.id]={'id':asset.id,'name':asset.name,'sha256':asset.sha256,'authorization':asset.authorization,'size_bytes':asset.size_bytes}
                if len(assets)>1000:raise HTTPException(422,'引用素材超过1000项，请分批导出')
    payload={'schema_version':1,'project_id':project_id,'ai_enabled':False,'current_version_ids':current,'versions':list(found.values()),'assets':list(assets.values())}
    encoded=jsonable_encoder(payload)
    if len(json.dumps(encoded,ensure_ascii=False).encode())>MAX_EXPORT_BYTES:raise HTTPException(422,'导出超过20 MiB，请按版本API分批读取')
    return JSONResponse(encoded,headers={'Content-Disposition':f'attachment; filename="creative-{project_id}.json"'})

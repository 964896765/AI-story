"""Fixed-input image candidates, evidence review and explicit adoption."""
import json
import os
from pathlib import Path
import struct
import subprocess
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field, StringConstraints
from sqlalchemy import select

from . import image_adapter, image_budget, storage
from .analysis_service import fingerprint
from .asset_validation import IMAGE_SUFFIXES, validate_extra_asset
from .creative import digest, require, version_ref
from .db import session
from .models import Asset, Project, Task, TaskEvent, now
from .production_specs import approval_spec, task_fields
from .render import Cancelled, file_hash, write_manifest
from .series import approved_guardian_shot
from .story_schemas import Strict, VersionId
from .text_adapters import redact, configured_key

router = APIRouter(prefix='/api/generation/projects/{project_id}/images',tags=['image-candidates'])
KIND = 'image_candidate'
CHECKS = {'character':('identity','wardrobe','style'), 'scene':('scene','style'), 'story_bible':('shot','style')}
Note = Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=2000)]
Hash = Annotated[str,Field(pattern=r'^[a-f0-9]{64}$')]


class Request(Strict):
    mode: Literal['mock','openai'] = 'mock'
    spec_version_id: VersionId
    source_version_id: VersionId
    shot_id: str | None = Field(None,pattern=r'^[a-zA-Z0-9_-]{1,48}$')
    prompt: Note
    confirm_external_text: bool = Field(default=False,strict=True)
    idempotency_key: Annotated[str,Field(min_length=1,max_length=64,pattern=r'\S')]


class Review(Strict):
    decision: Literal['approved','rejected']
    expected_sha256: Hash
    note: Note
    reference_asset_id: VersionId | None = None
    checks: list[Literal['identity','wardrobe','style','scene','shot']] = Field(default_factory=list,max_length=5)


class Adoption(Strict):
    title: Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=200)]
    expected_sha256: Hash


class Invoice(Strict):
    actual_cost_micros: Annotated[int,Field(strict=True,ge=0,le=10**12)]
    evidence: Note


def event(db, task, message):
    db.add(TaskEvent(task_id=task.id,attempt=task.attempt,message=message))


def scoped(db, project_id, task_id, *, lock=False):
    statement = select(Task).where(Task.id==task_id,Task.project_id==project_id,Task.kind==KIND)
    task = db.scalar(statement.with_for_update() if lock else statement)
    if not task:
        raise HTTPException(404,'当前项目没有此图片候选')
    return task


def frozen(db, project_id, request):
    spec = approval_spec(db,project_id,{'production_spec_version_id':request['spec_version_id']})
    entity, version = version_ref(db,project_id,request['source_version_id'],
        {'story_bible'} if request['shot_id'] else {'character','scene'})
    declared = version.content.get('production_spec_version_id')
    if (declared and declared!=spec['id']) or (request['shot_id'] and not declared):
        raise HTTPException(422,'固定制作规格与来源版本不一致')
    source = {'id':version.id,'kind':entity.kind,'title':version.title,'version':version.number,'sha256':version.content_hash}
    if digest(entity.kind,version.title,version.content)!=version.content_hash:
        raise HTTPException(409,'固定来源的内容哈希不符')
    reference_ids = version.content.get('reference_asset_ids',[])
    if shot_id := request['shot_id']:
        _,_,_,shot = approved_guardian_shot(db,project_id,version.id,shot_id)
        contract = shot['guardian']
        source['contract_sha256'] = contract['contract_sha256']
        reference_ids = contract['source_images']
    references = []
    for asset_id in dict.fromkeys(reference_ids):
        asset = require(db,Asset,asset_id)
        if asset.project_id!=project_id or Path(asset.storage_key).suffix.lower() not in IMAGE_SUFFIXES:
            raise HTTPException(422,'只能使用当前项目的固定参考图')
        if request['shot_id'] and reference_ids[asset_id]!=asset.sha256:
            raise HTTPException(409,'镜头参考图片与合同哈希不符')
        references.append({'id':asset.id,'sha256':asset.sha256,'name':asset.name})
    return {**task_fields(spec),'source':source,'references':references}


def public(task):
    inputs, output = task.input_snapshot, task.output
    return {'id':task.id,'mode':task.parameters['mode'],'shot_id':task.parameters.get('shot_id'),
            'model':(inputs.get('quote') or {}).get('model'),'status':task.status,'stage':task.stage,
            'progress':task.progress,'attempt':task.attempt,'elapsed_seconds':task.elapsed_seconds,
            'error_code':task.error_code,'cancel_requested':task.cancel_requested,'created_at':task.created_at,
            'source':inputs['source'],'references':inputs['references'],'production_spec':inputs['production_spec'],
            'checks':CHECKS[inputs['source']['kind']],'input_sha256':inputs['input_sha256'],
            'actual_cost_micros':output.get('billing',{}).get('actual_cost_micros') if inputs.get('quote') else 0,
            'output':{key:value for key,value in output.items() if key in
                      ('width','height','sha256','vendor_request_id','usage','review','adoption')},
            'billing':{key:value for key,value in output.get('billing',{}).items() if key in
                       ('state','currency','reserved_micros','sent_at')}}


@router.get('/capabilities')
def capabilities(project_id: str, db=Depends(session)):
    require(db,Project,project_id)
    try:
        quote = image_budget.configuration(db,project_id)
        budget = image_budget.account(db,project_id,quote)
        if budget.reserved_micros+budget.spent_micros+quote['upper_bound_micros']>budget.limit_micros:
            raise HTTPException(409,'当前项目可用真实图片预算不足')
    except HTTPException as exc:
        return {'mock_available':True,'live_available':False,'quote':None,'reason':exc.detail}
    return {'mock_available':True,'live_available':True,'reason':None,
            'quote':{key:quote[key] for key in ('model','currency','upper_bound_micros','price_source')}}


@router.get('')
def history(project_id: str, db=Depends(session)):
    require(db,Project,project_id)
    rows = db.scalars(select(Task).where(Task.project_id==project_id,Task.kind==KIND)
                     .order_by(Task.created_at.desc(),Task.id).limit(30))
    return [public(task) for task in rows]


@router.get('/{task_id}')
def read(project_id: str, task_id: str, db=Depends(session)):
    return public(scoped(db,project_id,task_id))


@router.post('',status_code=201)
def enqueue(project_id: str, body: Request, db=Depends(session)):
    if not db.scalar(select(Project.id).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    key = 'image-candidate:'+body.idempotency_key
    request = body.model_dump(exclude={'idempotency_key'})
    previous = db.scalar(select(Task).where(Task.project_id==project_id,Task.idempotency_key==key))
    if previous:
        if previous.kind!=KIND or previous.parameters!=request:
            raise HTTPException(409,'此请求键已用于不同的图片任务')
        return public(previous)
    quote = None
    if body.mode=='openai':
        if not body.confirm_external_text:
            raise HTTPException(422,'请明确确认将提示词和制作风格发送给图片供应商')
        quote = image_budget.configuration(db,project_id)
        if configured_key(quote) in body.prompt:
            raise HTTPException(422,'提示词不能包含已配置密钥')
    inputs = {**frozen(db,project_id,request),'quote':quote}
    if quote:
        settings = inputs['production_spec']['settings']
        credential = configured_key(quote)
        if any(credential in settings[key] for key in ('style','restrictions')):
            raise HTTPException(422,'制作规格不能包含已配置密钥')
        if settings['budget_currency']!=quote['currency']:
            raise HTTPException(422,'订单币种须与固定制作规格一致')
    digest_value = fingerprint([request,inputs])
    if quote and db.scalar(select(Task.id).where(Task.project_id==project_id,Task.kind==KIND,
        Task.input_snapshot['input_sha256'].as_string()==digest_value,
        Task.output['billing']['state'].as_string().in_(('reserved','awaiting_invoice'))).limit(1)):
        raise HTTPException(409,'相同图片请求仍占用预算，请先核对之前的任务')
    task = Task(project_id=project_id,story_version_id=body.source_version_id,kind=KIND,idempotency_key=key,
        parameters=request,input_snapshot={**inputs,'input_sha256':digest_value})
    db.add(task)
    db.flush()
    if quote:
        image_budget.reserve(db,task,quote)
    event(db,task,'图片候选已排队，等待验证固定输入')
    db.commit()
    return public(task)


def candidate_file(task):
    output = task.output
    path = storage.resolve_key(f'outputs/{task.id}/candidate.png')
    if (not path.is_file() or path.stat().st_size!=output['size_bytes'] or file_hash(path)!=output['sha256']):
        raise HTTPException(409,'图片候选文件缺失或哈希不符')
    return path


def completed(task, expected=None):
    if task.status!='succeeded' or not task.output.get('sha256'):
        raise HTTPException(409,'候选尚未通过图片的技术检查')
    if expected is not None and expected!=task.output['sha256']:
        raise HTTPException(409,'候选哈希与当前审核对象不符')
    return candidate_file(task)


@router.get('/{task_id}/file')
def preview(project_id: str, task_id: str, db=Depends(session)):
    return FileResponse(completed(scoped(db,project_id,task_id)),media_type='image/png',
                        headers={'X-Content-Type-Options':'nosniff','Cache-Control':'no-store'})


def verify_snapshot(db, task):
    inputs = {key:value for key,value in task.input_snapshot.items() if key!='input_sha256'}
    if fingerprint([task.parameters,inputs])!=task.input_snapshot['input_sha256']:
        raise HTTPException(409,'图片任务输入快照已变更')
    if {**frozen(db,task.project_id,task.parameters),'quote':inputs['quote']}!=inputs:
        raise HTTPException(409,'固定输入或参考记录已变更')


@router.post('/{task_id}/review')
def review(project_id: str, task_id: str, body: Review, db=Depends(session)):
    task = scoped(db,project_id,task_id,lock=True)
    completed(task,body.expected_sha256)
    credential = configured_key(task.input_snapshot.get('quote') or {})
    if credential and credential in body.note:
        raise HTTPException(422,'审核意见不能包含已配置密钥')
    request = body.model_dump()
    if previous := task.output.get('review'):
        if previous['request']!=request:
            raise HTTPException(409,'此候选已有内容审核记录')
        return public(task)
    verify_snapshot(db,task)
    references = task.input_snapshot['references']
    reference = next((ref for ref in references if ref['id']==body.reference_asset_id),None)
    if body.reference_asset_id and not reference:
        raise HTTPException(422,'请选择固定输入中的参考图')
    if body.decision=='approved':
        required = CHECKS[task.input_snapshot['source']['kind']]
        if sorted(body.checks)!=sorted(required) or (references and not reference):
            raise HTTPException(422,'通过前须对照参考图并确认全部内容检查项')
    if reference:
        asset = require(db,Asset,reference['id'])
        source = storage.resolve_key(asset.storage_key)
        if not source.is_file() or file_hash(source)!=reference['sha256']:
            raise HTTPException(409,'参考图文件已缺失或哈希不符')
    task.output = {**task.output,'review':{'request':request,'reference':reference,'at':now().isoformat()}}
    event(db,task,'已保存图片内容审核及哈希证据')
    db.commit()
    return public(task)


@router.post('/{task_id}/adopt',status_code=201)
def adopt(project_id: str, task_id: str, body: Adoption, db=Depends(session)):
    task = scoped(db,project_id,task_id,lock=True)
    completed(task,body.expected_sha256)
    credential = configured_key(task.input_snapshot.get('quote') or {})
    if credential and credential in body.title:
        raise HTTPException(422,'素材标题不能包含已配置密钥')
    review = task.output.get('review',{}).get('request',{})
    if review.get('decision')!='approved' or review.get('expected_sha256')!=body.expected_sha256:
        raise HTTPException(409,'采纳前须通过相同图片哈希的内容审核')
    if previous := task.output.get('adoption'):
        if previous['title']!=body.title:
            raise HTTPException(409,'此候选已用另一名称入库')
        return public(task)
    verify_snapshot(db,task)
    simulated = task.parameters['mode']=='mock'
    output = task.output
    name = body.title if body.title.lower().endswith('.png') else body.title+'.png'
    asset = Asset(project_id=project_id,name=name,storage_key=output['storage_key'],sha256=output['sha256'],
        size_bytes=output['size_bytes'],authorization='离线模拟验收图，仅限测试' if simulated else '模型候选人工采纳，发行授权待登记',
        media_info={'origin':KIND,'simulated':simulated,'task_id':task.id,'source_version_id':task.story_version_id,
                    'model':(task.input_snapshot['quote'] or {}).get('model'),'width':output['width'],'height':output['height']})
    db.add(asset)
    db.flush()
    task.output = {**output,'adoption':{'asset_id':asset.id,'title':body.title,'at':now().isoformat()}}
    event(db,task,'已将人工批准的图片添加到项目素材')
    db.commit()
    return public(task)


@router.post('/{task_id}/invoice')
def reconcile(project_id: str, task_id: str, body: Invoice, db=Depends(session)):
    task = scoped(db,project_id,task_id,lock=True)
    billing = task.output.get('billing',{})
    note = redact(body.evidence,configured_key(task.input_snapshot.get('quote') or {}))
    if billing.get('state')=='settled':
        if (billing['actual_cost_micros'],billing['evidence'])!=(body.actual_cost_micros,note):
            raise HTTPException(409,'已有不同的账单凭证')
        return public(task)
    if billing.get('state')!='awaiting_invoice' or task.status in ('queued','running'):
        raise HTTPException(409,'仅已结束且已发送的真实图片任务可结算')
    image_budget.change(db,task,body.actual_cost_micros,note)
    event(db,task,'已依据人工账单凭证结算真实图片任务')
    db.commit()
    return public(task)


def verify_png(path, profile):
    validate_extra_asset(path,'.png')
    with path.open('rb') as file:
        width,height = struct.unpack('>II',file.read(24)[16:24])
    if (width,height)!=image_adapter.SIZES[profile]:
        raise ValueError('图片尺寸与申请的图片画幅规格不匹配')
    result = subprocess.run(['ffmpeg','-v','error','-nostdin','-xerror','-protocol_whitelist','file,pipe',
        '-f','png_pipe','-i',str(path),'-frames:v','1','-f','null','-'],capture_output=True,timeout=30)
    if result.returncode:
        raise ValueError('候选图片解码失败')
    return width,height


def execute(task_id, attempt, update, factory):
    update('image_verify_inputs',10)
    failure = None
    credential = None
    output_key = f'outputs/{task_id}/candidate.png'
    target = storage.resolve_key(output_key)
    manifest = target.parent/'image.json'
    with factory.begin() as db:
        task = db.scalar(select(Task).where(Task.id==task_id).with_for_update())
        if task.cancel_requested:
            raise Cancelled('已请求取消图片任务')
        request, snapshot = task.parameters, task.input_snapshot
        quote = snapshot['quote']
        if manifest.is_file():
            receipt = json.loads(manifest.read_text(encoding='utf-8'))
            if (receipt.get('input_sha256')==snapshot['input_sha256'] and receipt.get('storage_key')==output_key
                and target.is_file() and target.stat().st_size==receipt['size_bytes'] and file_hash(target)==receipt['sha256']):
                return receipt
        if quote and task.output['billing'].get('sent_at'):
            raise ValueError('图片调用结果未知，预算继续占用，请核对账单；系统不会重新发送')
        try:
            verify_snapshot(db,task)
            if quote:
                credential = image_budget.before_dispatch(db,task)
        except HTTPException as exc:
            if quote and task.output['billing']['state']=='reserved':
                image_budget.change(db,task,None,'发送前检查失败')
            failure = exc.detail
    if failure:
        raise ValueError(str(failure))
    profile = snapshot['production_spec']['settings']['profile']
    update('image_dispatch' if quote else 'image_simulate',25)
    if quote:
        settings = snapshot['production_spec']['settings']
        prompt = f"{request['prompt']}\n\n视觉风格：{settings['style']}\n制作限制：{settings['restrictions']}"
        result = image_adapter.generate(quote['model'],prompt,profile,credential,task_id)
    else:
        result = image_adapter.simulation(profile)
    update('image_decode',75)
    work = storage.resolve_key(f'tmp/{task_id}/{attempt}/candidate.partial.png')
    work.parent.mkdir(parents=True,exist_ok=True)
    with work.open('xb') as stream:
        stream.write(result.content)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        width,height = verify_png(work,profile)
        receipt = {'storage_key':output_key,'sha256':file_hash(work),'size_bytes':work.stat().st_size,
                   'width':width,'height':height,'input_sha256':snapshot['input_sha256'],
                   'vendor_request_id':result.request_id,'usage':result.usage}
        update('image_publish',95)
        target.parent.mkdir(parents=True,exist_ok=True)
        os.replace(work,target)
        write_manifest(manifest,receipt)
        return receipt
    finally:
        work.unlink(missing_ok=True)

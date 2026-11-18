import difflib
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import defer
from .db import session
from .models import TextProvider,ModelBudget,ModelCall,ModelLedger,ModelDraft,Task,StoryVersion
from .text_schemas import ProviderInput,BudgetInput,AdaptInput,ReviewInput,DraftEditInput,ReconcileInput,RetryInput,BillingInput
from .text_adapters import live_gate
from . import text_service as service
from .creative import require

router=APIRouter(prefix='/api/text',tags=['text-model-governance'])

class Availability(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled: bool

@router.get('/status')
def status():
    return {'live_authorized':live_gate(),'default_live_budget_micros':0,'real_acceptance_passed':False,'note':'本阶段仅模拟验收，真实预算0；模拟账本不计入真实费用。'}

@router.get('/providers')
def providers(db=Depends(session)):
    return [service.provider_public(p) for p in db.scalars(select(TextProvider).order_by(TextProvider.created_at.desc()))]

@router.post('/providers',status_code=201)
def create_provider(body:ProviderInput,db=Depends(session)):
    row=TextProvider(label=body.label,kind=body.kind,enabled=body.enabled,settings=body.settings.model_dump(mode='json'))
    db.add(row);db.commit();return service.provider_public(row)

@router.post('/providers/{provider_id}/availability')
def availability(provider_id:str,body:Availability,db=Depends(session)):
    row=require(db,TextProvider,provider_id);row.enabled=body.enabled;db.commit();return service.provider_public(row)

@router.get('/providers/{provider_id}/quote')
def quote(provider_id:str,max_output_tokens:int=1024,db=Depends(session)):
    if not 128<=max_output_tokens<=32768:raise HTTPException(422,'输出上限无效')
    return service.quote(require(db,TextProvider,provider_id),max_output_tokens)

@router.get('/projects/{project_id}/budgets')
def budgets(project_id:str,db=Depends(session)):
    return [service.budget_public(b) for b in db.scalars(select(ModelBudget).where(ModelBudget.project_id==project_id))]

@router.post('/projects/{project_id}/budgets')
def configure_budget(project_id:str,body:BudgetInput,db=Depends(session)):
    row=service.configure_budget(db,project_id,body);db.commit();return service.budget_public(row)

@router.post('/projects/{project_id}/calls',status_code=201)
def create_call(project_id:str,body:AdaptInput,db=Depends(session)):
    row=service.reserve_call(db,project_id,body);db.commit();return service.call_public(row)

@router.get('/projects/{project_id}/calls')
def calls(project_id:str,db=Depends(session)):
    result=[]
    for row in db.scalars(select(ModelCall).options(defer(ModelCall.draft),defer(ModelCall.receipt),defer(ModelCall.prompt),defer(ModelCall.review)).where(ModelCall.project_id==project_id).order_by(ModelCall.created_at.desc()).limit(100)):
        result.append(service.call_public(row,False))
    return result

@router.get('/calls/{call_id}')
def call(call_id:str,db=Depends(session)):return service.call_public(require(db,ModelCall,call_id))

@router.post('/calls/{call_id}/cancel')
def cancel(call_id:str,db=Depends(session)):
    existing=require(db,ModelCall,call_id)
    task=db.scalar(select(Task).where(Task.id==existing.task_id).with_for_update())
    row=service.cancel_locked(db,task);db.commit();return service.call_public(row)

@router.post('/calls/{call_id}/retry',status_code=201)
def retry(call_id:str,body:RetryInput,db=Depends(session)):
    old=require(db,ModelCall,call_id)
    if old.status not in ('failed','invalid_output','cancelled') or old.budget_status not in ('released','settled'):
        raise HTTPException(409,'结果未知或尚未结束，禁止重发；请先对账')
    if old.sent_at and not body.acknowledge_new_charge:raise HTTPException(409,'这是新的模型调用，可能再次收费，需明确确认')
    request=AdaptInput(**old.request,idempotency_key=body.idempotency_key)
    row=service.reserve_call(db,old.project_id,request);db.commit();return service.call_public(row)

@router.post('/calls/{call_id}/settle')
def settle(call_id:str,db=Depends(session)):
    row=service.finalize_receipt(db,call_id)
    service.sync_task_after_manual_action(require(db,Task,row.task_id),row)
    db.commit();return service.call_public(row)

@router.post('/calls/{call_id}/reconcile')
def reconcile(call_id:str,body:ReconcileInput,db=Depends(session)):
    row=service.reconcile(db,call_id,body);db.commit();return service.call_public(row)

@router.post('/calls/{call_id}/billing')
def billing(call_id:str,body:BillingInput,db=Depends(session)):
    row=service.record_billing(db,call_id,body);db.commit();return service.call_public(row)

@router.post('/calls/{call_id}/draft')
def save_draft(call_id:str,body:DraftEditInput,db=Depends(session)):
    row=service.save_draft(db,call_id,body);db.commit();return service.call_public(row)

@router.get('/calls/{call_id}/drafts')
def drafts(call_id:str,db=Depends(session)):
    require(db,ModelCall,call_id)
    return [{'number':d.number,'origin':d.origin,'created_at':d.created_at} for d in db.scalars(select(ModelDraft).options(defer(ModelDraft.payload)).where(ModelDraft.call_id==call_id).order_by(ModelDraft.number).limit(100))]

@router.post('/calls/{call_id}/review')
def review(call_id:str,body:ReviewInput,db=Depends(session)):
    row=service.review_call(db,call_id,body);db.commit();return service.call_public(row)

@router.get('/calls/{call_id}/drafts/{number}')
def draft_revision(call_id:str,number:int,db=Depends(session)):
    require(db,ModelCall,call_id)
    row=db.scalar(select(ModelDraft).where(ModelDraft.call_id==call_id,ModelDraft.number==number))
    if not row:raise HTTPException(404,'草稿版本不存在')
    return {'number':row.number,'origin':row.origin,'payload':row.payload,'created_at':row.created_at}

@router.get('/calls/{call_id}/compare')
def compare(call_id:str,db=Depends(session)):
    call=require(db,ModelCall,call_id);source=require(db,StoryVersion,call.source_version_id)
    if not call.draft:raise HTTPException(409,'没有通过结构校验的草稿')
    original=source.content.get('text') or source.content.get('body','')
    adapted=call.draft['body']
    delta=''.join(difflib.unified_diff((original+'\n').splitlines(keepends=True),(adapted+'\n').splitlines(keepends=True),fromfile='固定原稿',tofile='待审核改编稿'))
    return {'source_version_id':source.id,'draft_revision':call.draft_revision,'diff':delta[:262144],'truncated':len(delta)>262144}

@router.get('/projects/{project_id}/ledger')
def ledger(project_id:str,db=Depends(session)):
    rows=db.execute(select(ModelLedger,ModelBudget).join(ModelBudget,ModelLedger.budget_id==ModelBudget.id).where(ModelBudget.project_id==project_id).order_by(ModelLedger.id.desc()).limit(200)).all()
    return [{'id':entry.id,'call_id':entry.call_id,'mode':budget.mode,'currency':budget.currency,'kind':entry.kind,'amount_micros':entry.amount_micros,'created_at':entry.created_at} for entry,budget in rows]

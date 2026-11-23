"""Transactional budgets and one-dispatch text calls. No automatic paid retries."""
import hashlib
import json
import os
from fastapi import HTTPException
from sqlalchemy import func, select, text
from . import director_guidance
from .models import Project,Task,TaskEvent,TextProvider,ModelBudget,ModelCall,ModelLedger,ModelDraft,StoryEntity,StoryVersion,now,uid
from .creative import require,version_ref,create_entity,append_version,validate_content,pack
from .text_schemas import AdaptInput,AdaptedDraft,DirectorAdviceInput,DirectorAdviceDraft
from .text_adapters import approved_endpoint,build_adapter,live_gate,configured_key,redact,CallFailure
from .adaptation_policy import PROMPT_VERSION,SYSTEM_PROMPT,prompt_for,reserve_quote,priced_cost,validated_usage,validated_draft
from .model_adapters import ModelRequest
from .production_specs import pinned, task_fields

def provider_public(provider):
    return {'id':provider.id,'label':provider.label,'kind':provider.kind,'enabled':provider.enabled,'settings':provider.settings,'key_configured':bool(configured_key(provider.settings)) if provider.kind!='mock' else False,'live_authorized':live_gate(),'network_tested':False}

def budget_public(budget):
    return {'id':budget.id,'project_id':budget.project_id,'mode':budget.mode,'currency':budget.currency,'limit_micros':budget.limit_micros,'reserved_micros':budget.reserved_micros,'spent_micros':budget.spent_micros,'available_micros':max(0,budget.limit_micros-budget.reserved_micros-budget.spent_micros),'halted':budget.halted,'authorized':bool(budget.authorization_id) if budget.mode=='live' else True}

def call_public(call,detail=True):
    return {'id':call.id,'project_id':call.project_id,'task_id':call.task_id,'provider_id':call.provider_id,'source_version_id':call.source_version_id,'accepted_version_id':call.accepted_version_id,'provider_snapshot':call.provider_snapshot,'prompt_version':call.prompt_version,'simulated':call.simulated,'status':call.status,'budget_status':call.budget_status,'reserved_micros':call.reserved_micros,'calculated_cost_micros':call.calculated_cost_micros,'actual_cost_micros':call.actual_cost_micros,'usage':call.usage,'draft':call.draft if detail else None,'draft_revision':call.draft_revision,'review':call.review if detail else None,'provider_call_id':call.provider_call_id,'error_code':call.error_code,'created_at':call.created_at,'request':call.request if detail else None}

def event(db,task,message):db.add(TaskEvent(task_id=task.id,attempt=task.attempt,message=message))

def ledger(db,budget,call,kind,amount,note=''):
    db.add(ModelLedger(budget_id=budget.id,call_id=call.id,kind=kind,amount_micros=amount,reference=f'{kind}:{call.id}',note=note))

def configure_budget(db,project_id,body):
    require(db,Project,project_id)
    db.scalar(select(Project).where(Project.id==project_id).with_for_update())
    if body.mode=='live' and (body.limit_micros>0 or body.authorization_id):
        if not live_gate() or body.authorization_id!=os.getenv('AI_STORY_LIVE_AUTHORIZATION_ID'):
            raise HTTPException(403,'真实预算保持0：本机未启用且未获得后续明确调用授权')
    budget=db.scalar(select(ModelBudget).where(ModelBudget.project_id==project_id,ModelBudget.mode==body.mode,ModelBudget.currency==body.currency).with_for_update())
    if not budget:
        budget=ModelBudget(project_id=project_id,mode=body.mode,currency=body.currency)
        db.add(budget);db.flush()
    reference=f'limit:{budget.id}:{body.idempotency_key}'
    previous=db.scalar(select(ModelLedger).where(ModelLedger.reference==reference))
    request=body.model_dump(exclude={'idempotency_key'})
    note=json.dumps(request,sort_keys=True,ensure_ascii=False)
    if previous:
        if previous.note!=note:raise HTTPException(409,'预算幂等键冲突')
        return budget
    if body.limit_micros<budget.spent_micros+budget.reserved_micros:raise HTTPException(409,'预算不得低于已使用与仍占用的金额')
    budget.limit_micros=body.limit_micros
    budget.authorization_id=body.authorization_id if body.mode=='live' else ''
    db.add(ModelLedger(budget_id=budget.id,kind='limit',amount_micros=body.limit_micros,reference=reference,note=note))
    return budget

def quote(provider,max_output_tokens):
    try:upper=reserve_quote(provider.settings,max_output_tokens)
    except CallFailure as exc:raise HTTPException(422,exc.code) from None
    return {'upper_bound_micros':upper,'expected_actual_cost_micros':None,'currency':provider.settings['currency'],'simulated':provider.kind=='mock','input_token_bound':provider.settings['input_token_limit'],'note':'按配置的最大输入用量与输出上限预留；不是精确估价，也不是供应商账单。模拟价格不代表市场报价。'}

def check_live(provider,budget=None):
    settings=provider.settings
    if not live_gate():raise CallFailure('LIVE_CALLS_NOT_AUTHORIZED')
    if not approved_endpoint(settings):raise CallFailure('PROVIDER_ENDPOINT_NOT_AUTHORIZED')
    if not configured_key(settings):raise CallFailure('API_KEY_NOT_CONFIGURED')
    if not settings['billing_verified'] or not settings['price_source']:
        raise CallFailure('BILLING_BOUND_NOT_VERIFIED')
    if budget is not None and budget.authorization_id!=os.getenv('AI_STORY_LIVE_AUTHORIZATION_ID'):
        raise CallFailure('PROJECT_BUDGET_NOT_AUTHORIZED')

def lock_global_budget(db):
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': 719031005})

def enforce_global_ceiling(db, currency, upper):
    raw_limit = os.getenv(f'AI_STORY_LIVE_LIMIT_{currency}_MICROS', '0')
    try:
        limit = int(raw_limit)
    except ValueError:
        limit = 0
    if not 0 < limit <= 10**12:
        raise HTTPException(409,'本机真实额度未配置，已阻止调用')
    # Serialize reservations across projects. Settlements that exceed a quote halt live dispatch.
    lock_global_budget(db)
    total = db.scalar(select(func.coalesce(func.sum(ModelBudget.spent_micros + ModelBudget.reserved_micros),0))
        .where(ModelBudget.mode=='live',ModelBudget.currency==currency))
    halted = db.scalar(select(ModelBudget.id).where(ModelBudget.mode=='live',ModelBudget.halted).limit(1))
    if halted or total + upper > limit:
        raise HTTPException(409,'本机真实额度不足或有未处理超额，已阻止调用')

def reserve_call(db,project_id,body):
    if not db.scalar(select(Project).where(Project.id==project_id).with_for_update()):raise HTTPException(404,'项目不存在')
    request=body.model_dump(exclude={'idempotency_key'})
    director = isinstance(body,DirectorAdviceInput)
    prompt_version = director_guidance.PROMPT_VERSION if director else PROMPT_VERSION
    fingerprint=hashlib.sha256(json.dumps(request,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    previous=db.scalar(select(ModelCall).where(ModelCall.project_id==project_id,ModelCall.request_key==body.idempotency_key))
    if previous:
        if previous.request_hash!=fingerprint or previous.prompt_version!=prompt_version:
            raise HTTPException(409,'模型调用幂等键已用于不同请求')
        return previous
    provider=require(db,TextProvider,body.provider_id)
    if not provider.enabled:raise HTTPException(409,'供应商配置已停用')
    if director:
        if provider.kind!='mock':
            raise HTTPException(403,'导演规划当前仅使用离线模拟供应商')
        version,prompt=director_guidance.prepare_prompt(db,project_id,body.plan_ids,body.goal)
        system_prompt=director_guidance.SYSTEM_PROMPT
    else:
        _,version=version_ref(db,project_id,body.source_version_id,{'novel','script','episode'})
        source=version.content.get('text') or version.content.get('body')
        if not source:raise HTTPException(422,'源版本无可改编正文')
        prompt=prompt_for(source,request)
        system_prompt=SYSTEM_PROMPT
    spec = pinned(db,project_id,version.content)
    if spec and not director:
        creative_settings = {key:spec['settings'][key] for key in ('episode_count','episode_duration_ms','style','restrictions')}
        prompt += '\n固定制作规格（项目输入）：' + json.dumps(creative_settings,ensure_ascii=False)
    # Reserve the entire verified input/context bound, rather than guessing tokenizer ratios.
    if len((prompt+system_prompt).encode())+4096>provider.settings['input_token_limit']:
        raise HTTPException(422,'原文或提示词超过保守输入边界，请选择较小的分集或核实模型输入上限')
    upper=quote(provider,body.max_output_tokens)['upper_bound_micros']
    if upper is None:raise HTTPException(409,'价格未知，无法可靠预留预算，已阻止调用')
    mode='mock' if provider.kind=='mock' else 'live'
    budget=db.scalar(select(ModelBudget).where(ModelBudget.project_id==project_id,ModelBudget.mode==mode,ModelBudget.currency==provider.settings['currency']).with_for_update())
    if mode=='live':
        try:check_live(provider,budget)
        except CallFailure as exc:raise HTTPException(403,exc.code) from None
        enforce_global_ceiling(db,provider.settings['currency'],upper)
    if not budget or budget.limit_micros<=0 or budget.halted or budget.spent_micros+budget.reserved_micros+upper>budget.limit_micros:
        raise HTTPException(409,'预算不足、未设置或账户已暂停，未发起请求')
    if mode=='live' and not budget.authorization_id:raise HTTPException(403,'真实项目预算未授权')
    call_id,task_id=uid(),uid()
    parameters={'model_call_id':call_id}
    if director:
        parameters['purpose']='director_advice'
    task=Task(id=task_id,project_id=project_id,asset_id=None,kind='adapt',story_version_id=version.id,idempotency_key='text-call:'+call_id,parameters=parameters,input_snapshot={'source_version_id':version.id,'content_hash':version.content_hash,**task_fields(spec)},max_attempts=1)
    db.add(task);db.flush()
    call=ModelCall(id=call_id,project_id=project_id,task_id=task_id,provider_id=provider.id,budget_id=budget.id,source_version_id=version.id,request_key=body.idempotency_key,request_hash=fingerprint,request=request,provider_snapshot={'kind':provider.kind,'label':provider.label,**provider.settings},prompt_version=prompt_version,prompt=prompt,simulated=mode=='mock',reserved_micros=upper)
    db.add(call);db.flush()
    budget.reserved_micros+=upper
    ledger(db,budget,call,'reserve',upper,'模拟资金占用' if call.simulated else '真实调用最坏费用占用')
    event(db,task,'模拟文本调用已预留预算' if call.simulated else '真实文本调用已预留预算，等待授权检查与发送')
    return call

def locked_call(db,call_id):
    keys=db.execute(select(ModelCall.task_id,ModelCall.budget_id).where(ModelCall.id==call_id)).one_or_none()
    if keys is None:raise HTTPException(404,'模型调用记录不存在')
    task=db.scalar(select(Task).where(Task.id==keys.task_id).with_for_update().execution_options(populate_existing=True))
    budget=db.scalar(select(ModelBudget).where(ModelBudget.id==keys.budget_id).with_for_update().execution_options(populate_existing=True))
    call=db.scalar(select(ModelCall).where(ModelCall.id==call_id).with_for_update().execution_options(populate_existing=True))
    return task,budget,call

def release(db,budget,call,note):
    if call.budget_status not in ('reserved','unknown'):return
    budget.reserved_micros-=call.reserved_micros
    call.budget_status='released'
    ledger(db,budget,call,'release',call.reserved_micros,note)

def cancel_locked(db,task):
    call=require_call_by_task(db,task.id)
    _,budget,call=locked_call(db,call.id)
    if call.status=='cancelled':return call
    task.cancel_requested=True
    if not call.sent_at and call.status=='queued':
        release(db,budget,call,'发送前取消，不收费')
        call.status='cancelled';task.status=task.stage='cancelled';task.finished_at=now()
    elif call.status in ('dispatching','received','unknown','cost_unknown'):
        event(db,task,'取消已请求；发送后无法保证供应商停止生成或不收费，保留预算直到结果明确')
    else:raise HTTPException(409,'调用已结束，不能撤销已产生的费用')
    return call

def require_call_by_task(db,task_id):
    call=db.scalar(select(ModelCall).where(ModelCall.task_id==task_id))
    if not call:raise HTTPException(404,'模型调用记录不存在')
    return call


def retry_call(db,old,body):
    if old.status not in ('failed','invalid_output','cancelled') or old.budget_status not in ('released','settled'):
        raise HTTPException(409,'结果未知或尚未结束，禁止重发；请先对账')
    if old.sent_at and not body.acknowledge_new_charge:
        raise HTTPException(409,'这是新的模型调用，可能再次收费，需明确确认')
    schema = DirectorAdviceInput if old.prompt_version==director_guidance.PROMPT_VERSION else AdaptInput
    request = schema.model_validate({**old.request,'idempotency_key':body.idempotency_key})
    return reserve_call(db,old.project_id,request)

def sync_task_after_manual_action(task,call):
    # A running worker re-reads the call before its final write; don't steal ownership.
    if task.status=='running':return
    if call.status in ('awaiting_review','accepted','rejected'):
        task.status='succeeded';task.stage={'awaiting_review':'awaiting_review','accepted':'approved','rejected':'rejected'}[call.status]
        task.progress=100;task.error=task.error_code=None
        task.output={'model_call_id':call.id,'status':call.status,'simulated':call.simulated,'review_required':call.status=='awaiting_review','accepted_version_id':call.accepted_version_id}
        task.finished_at=task.finished_at or now()
    elif call.status=='cancelled':task.status=task.stage='cancelled'
    elif call.status in ('failed','invalid_output','budget_overrun','cost_unknown','unknown'):
        task.status=task.stage='failed';task.error=task.error_code=call.error_code

def finalize_receipt(db,call_id):
    task,budget,call=locked_call(db,call_id)
    if call.budget_status=='settled':return call
    if call.budget_status not in ('reserved','unknown'):
        raise HTTPException(409,'预算已释放，此调用不得重新核算或占用额度')
    if not call.receipt:raise HTTPException(409,'没有持久化响应，禁止猜测结算或重发')
    usage=validated_usage(call.receipt.get('usage'))
    call.usage=usage
    try:
        if call.prompt_version==director_guidance.PROMPT_VERSION:
            parsed=validated_draft(call.receipt,DirectorAdviceDraft)
            if parsed['choice']>len(call.request['plan_ids']):
                raise CallFailure('DIRECTOR_OPTION_OUT_OF_SCOPE')
        else:
            parsed=validated_draft(call.receipt)
    except CallFailure as exc:parsed=None;call.error_code=exc.code
    if parsed and call.draft_revision==0:
        call.draft=parsed;call.draft_revision=1
        db.add(ModelDraft(call_id=call.id,number=1,payload=parsed,origin='mock' if call.simulated else 'model',request_key='model-response'))
    cost=priced_cost(call.provider_snapshot,usage['prompt_tokens'],usage['completion_tokens']) if usage else None
    if cost is None:
        call.status='cost_unknown';call.budget_status='unknown';call.error_code='USAGE_OR_PRICE_UNKNOWN'
        return call
    if not call.simulated:lock_global_budget(db)
    budget.reserved_micros-=call.reserved_micros;budget.spent_micros+=cost
    call.calculated_cost_micros=cost;call.budget_status='settled'
    ledger(db,budget,call,'settle',cost,'按配置费率与返回用量核算；模拟结果不是真实费用，供应商账单金额仍未知')
    breached=cost>call.reserved_micros or usage['prompt_tokens']>call.provider_snapshot['input_token_limit'] or usage['completion_tokens']>call.request['max_output_tokens']
    if breached:
        budget.halted=True;call.status='budget_overrun';call.error_code='BILLING_BOUND_EXCEEDED'
    elif task.cancel_requested:call.status='cancelled';call.error_code='CANCELLED_AFTER_DISPATCH'
    elif parsed:call.status='awaiting_review';call.error_code=None
    else:call.status='invalid_output'
    return call

def execute_text_task(task_id,factory):
    failure=None;send=False
    with factory.begin() as db:
        existing=require_call_by_task(db,task_id)
        task,budget,call=locked_call(db,existing.id)
        call_id=call.id
        if call.status=='queued':
            provider=require(db,TextProvider,call.provider_id)
            director=call.prompt_version==director_guidance.PROMPT_VERSION
            try:
                if task.cancel_requested:raise CallFailure('CANCELLED_BEFORE_DISPATCH')
                if not provider.enabled:raise CallFailure('PROVIDER_DISABLED')
                if director and (not call.simulated or provider.kind!='mock' or call.provider_snapshot['kind']!='mock'):
                    raise CallFailure('DIRECTOR_LIVE_CALLS_DISABLED')
                if not call.simulated:
                    check_live(provider,budget)
                    if budget.halted:raise CallFailure('BUDGET_HALTED_BEFORE_DISPATCH')
                    try:enforce_global_ceiling(db,call.provider_snapshot['currency'],0)
                    except HTTPException:raise CallFailure('GLOBAL_BUDGET_BLOCKED_BEFORE_DISPATCH') from None
            except CallFailure as exc:
                release(db,budget,call,'未发送请求，释放预算')
                call.status='cancelled' if task.cancel_requested else 'failed';call.error_code=exc.code;failure=exc
            else:
                call.status='dispatching';call.sent_at=now();send=True
                task.stage='dispatching'
                event(db,task,'发送意图已持久化；中断后禁止自动重复调用')
                settings=dict(call.provider_snapshot)
                parameters={'max_output_tokens':call.request['max_output_tokens']}
                if director:
                    parameters.update(system_prompt=director_guidance.SYSTEM_PROMPT,director_advice=True)
                else:
                    content=require(db,StoryVersion,call.source_version_id).content
                    parameters.update(system_prompt=SYSTEM_PROMPT,source_text=content.get('text') or content.get('body',''))
                request=ModelRequest(call.project_id,call.id,'text',call.prompt,(call.source_version_id,),parameters)
        elif call.status in ('dispatching','unknown'):
            failure=CallFailure('MODEL_OUTCOME_UNKNOWN',True)
        elif call.status=='cancelled':failure=CallFailure('CANCELLED')
    if failure:raise failure
    if send:
        try:result=build_adapter(settings['kind'],settings).invoke(request)
        except CallFailure as exc:
            with factory.begin() as db:
                task,budget,call=locked_call(db,call_id)
                call.error_code=exc.code
                if exc.unknown:call.status='unknown';call.budget_status='unknown'
                else:release(db,budget,call,'供应商明确拒绝且配置确认未收费');call.status='failed'
            raise
        except Exception:
            with factory.begin() as db:
                _,_,call=locked_call(db,call_id)
                call.status='unknown';call.budget_status='unknown';call.error_code='UNEXPECTED_ADAPTER_OUTCOME_UNKNOWN'
            raise CallFailure('UNEXPECTED_ADAPTER_OUTCOME_UNKNOWN',True) from None
        # Persist response before settlement. A crash after this point needs no new API call.
        with factory.begin() as db:
            task,_,call=locked_call(db,call_id)
            call.receipt={'content':result.output['text'],'usage':validated_usage(result.usage),'finish_reason':result.finish_reason,'request_id':result.request_id}
            call.provider_call_id=result.provider_call_id
            call.status='received'
            task.stage='received'
            event(db,task,'供应商响应已持久化，准备本地核算与结构检查')
    with factory.begin() as db:
        call=finalize_receipt(db,call_id)
        status,code=call.status,call.error_code
    if status not in ('awaiting_review','accepted','rejected','cancelled'):
        raise CallFailure(code or 'MODEL_CALL_FAILED',status in ('cost_unknown','unknown'))
    return {'model_call_id':call_id,'status':status,'simulated':settings['kind']=='mock' if send else call.simulated,'review_required':status=='awaiting_review'}

def recover_adapt_task(db,task):
    existing=require_call_by_task(db,task.id)
    _,budget,call=locked_call(db,existing.id)
    if call.status=='dispatching':
        call.status='unknown';call.budget_status='unknown';call.error_code='WORKER_LOST_AFTER_DISPATCH'
    if call.status in ('queued','received'):
        if task.cancel_requested and not call.sent_at:
            release(db,budget,call,'中断恢复确认发送前取消');call.status='cancelled';task.status=task.stage='cancelled'
        else:task.status='queued';task.stage='settlement_recovery' if call.status=='received' else 'recovered';task.next_run_at=now()
    elif call.status in ('awaiting_review','accepted','rejected'):
        task.status='succeeded'
        sync_task_after_manual_action(task,call)
    elif call.status=='cancelled':task.status=task.stage='cancelled'
    else:
        task.status=task.stage='failed';task.error_code='MODEL_OUTCOME_UNKNOWN' if call.budget_status=='unknown' else call.error_code
        task.error=task.error_code
    if task.status!='queued':task.finished_at=now()
    task.worker_token,task.lease_until=None,None

def recover_detached_calls(db):
    # Covers a DB failure after the response was received, when the outer task was failed.
    rows=db.scalars(select(Task).join(ModelCall,ModelCall.task_id==Task.id).where(Task.status.in_(['failed','cancelled']),ModelCall.status.in_(['dispatching','received']))).all()
    for task in rows:recover_adapt_task(db,task)

def reconcile(db,call_id,body):
    task,budget,call=locked_call(db,call_id)
    if call.status not in ('unknown','cost_unknown','received'):raise HTTPException(409,'此调用不需要或已经完成对账')
    if body.resolution=='not_charged':
        if call.status=='received' or validated_usage((call.receipt or {}).get('usage')):
            raise HTTPException(409,'已有用量响应，请完成核算后登记实际账单')
        release(db,budget,call,'人工证据确认未收费：'+redact(body.evidence,configured_key(call.provider_snapshot)))
        call.status='failed';call.error_code='RECONCILED_NOT_CHARGED'
    else:
        if not body.receipt:raise HTTPException(422,'必须提供供应商响应和用量作为对账证据')
        if set(body.receipt)-{'content','usage','finish_reason','request_id'}:raise HTTPException(422,'仅接受内容、用量与完成状态，不接受headers或密钥')
        if len(json.dumps(body.receipt).encode())>2*1024**2:raise HTTPException(422,'对账响应超过2 MiB')
        if call.status=='cost_unknown' and body.receipt.get('content')!=call.receipt.get('content'):
            raise HTTPException(422,'补充用量不得替换原始响应内容')
        content=body.receipt.get('content')
        if not isinstance(content,str):raise HTTPException(422,'模型响应正文必须为字符串')
        secret=configured_key(call.provider_snapshot)
        call.receipt={'content':redact(content,secret),'usage':validated_usage(body.receipt.get('usage')),
            'finish_reason':'stop' if body.receipt.get('finish_reason')=='stop' else None}
        call.status='received'
        call=finalize_receipt(db,call_id)
        if call.budget_status=='unknown':raise HTTPException(422,'响应须附有效用量，才能完成核算')
        db.add(ModelLedger(budget_id=budget.id,call_id=call.id,kind='reconcile_note',amount_micros=0,reference='reconcile:'+call.id,note=redact(body.evidence,secret)))
    event(db,task,'模型调用人工对账已记录；未重发请求')
    sync_task_after_manual_action(task,call)
    return call

def record_billing(db, call_id, body):
    task,budget,call=locked_call(db,call_id)
    if not call.sent_at or call.status in ('dispatching','received'):
        raise HTTPException(409,'调用仍在执行或从未发送')
    reference=f'billing:{call.id}:{body.idempotency_key}'
    note=redact(body.evidence,configured_key(call.provider_snapshot))
    previous=db.scalar(select(ModelLedger).where(ModelLedger.reference==reference))
    if previous:
        if (previous.kind,previous.amount_micros,previous.note)!=(body.kind,body.amount_micros,note):
            raise HTTPException(409,'费用凭证幂等键冲突')
        return call
    kind,amount=body.kind,body.amount_micros
    if not call.simulated:lock_global_budget(db)
    if kind=='charge':
        prior_charge=db.scalar(select(ModelLedger.id).where(ModelLedger.call_id==call.id,ModelLedger.kind=='charge').limit(1))
        if prior_charge:raise HTTPException(409,'已有实付凭证，退款请单独登记')
        if call.budget_status in ('unknown','reserved'):
            budget.reserved_micros-=call.reserved_micros
        budget.spent_micros+=amount-(call.calculated_cost_micros or 0)
        call.budget_status='settled'
        if call.status in ('unknown','cost_unknown'):
            call.status='cancelled' if task.cancel_requested else 'failed'
            call.error_code='MODEL_RESULT_NOT_VERIFIED'
        if amount>call.reserved_micros or budget.spent_micros+budget.reserved_micros>budget.limit_micros:
            budget.halted=True
    else:
        charged=db.scalar(select(ModelLedger.amount_micros).where(ModelLedger.call_id==call.id,ModelLedger.kind=='charge'))
        refunded=db.scalar(select(func.coalesce(func.sum(ModelLedger.amount_micros),0))
            .where(ModelLedger.call_id==call.id,ModelLedger.kind=='refund'))
        if charged is None or refunded+amount>charged:
            raise HTTPException(409,'退款须有实付凭证且不得超过实付金额')
        budget.spent_micros-=amount
    if not call.simulated:
        if kind=='charge':call.actual_cost_micros=amount
        else:call.actual_cost_micros-=amount
    db.add(ModelLedger(budget_id=budget.id,call_id=call.id,kind=kind,amount_micros=amount,reference=reference,note=note))
    event(db,task,'已按人工账单凭证记录'+('费用' if kind=='charge' else '退款'))
    sync_task_after_manual_action(task,call)
    return call

def save_draft(db,call_id,body):
    _,_,call=locked_call(db,call_id)
    if call.prompt_version==director_guidance.PROMPT_VERSION:
        raise HTTPException(422,'导演建议须在总导演中审核')
    if call.status!='awaiting_review':raise HTTPException(409,'仅待审核且费用明确的草稿可编辑')
    payload=body.draft.model_dump()
    if len(json.dumps(payload,ensure_ascii=False).encode())>2*1024**2:raise HTTPException(422,'草稿超过2 MiB')
    previous=db.scalar(select(ModelDraft).where(ModelDraft.call_id==call.id,ModelDraft.request_key==body.idempotency_key))
    if previous:
        if previous.payload!=payload:raise HTTPException(409,'草稿幂等键冲突')
        return call
    if call.draft_revision!=body.expected_revision:raise HTTPException(409,'草稿已被其他编辑更新')
    call.draft_revision+=1;call.draft=payload
    db.add(ModelDraft(call_id=call.id,number=call.draft_revision,payload=payload,origin='human',request_key=body.idempotency_key))
    return call

def review_call(db,call_id,body):
    initial=require(db,ModelCall,call_id)
    db.scalar(select(Project).where(Project.id==initial.project_id).with_for_update())
    task,budget,call=locked_call(db,call_id)
    if call.prompt_version==director_guidance.PROMPT_VERSION:
        raise HTTPException(422,'导演建议须在总导演中审核')
    request=body.model_dump()
    if call.review:
        if call.review['request']!=request:raise HTTPException(409,'此调用已审核，不能覆盖原审核结果')
        return call
    if call.status!='awaiting_review' or call.budget_status!='settled':raise HTTPException(409,'仅已完成结算且结构有效的待审核草稿可确认')
    if call.draft_revision!=body.draft_revision:raise HTTPException(409,'审核版本已变化，请刷新')
    if body.action=='reject':
        call.status='rejected';call.review={'request':request,'note':'已发生调用费用不因拒稿撤销'};sync_task_after_manual_action(task,call);return call
    parsed=AdaptedDraft.model_validate(call.draft).model_dump()
    source_entity,source_version=version_ref(db,call.project_id,call.source_version_id)
    content={'body':parsed['body'],'summary':parsed['synopsis'],'source_version_id':source_version.id,'character_version_ids':source_version.content.get('character_version_ids',[]),'scene_version_ids':source_version.content.get('scene_version_ids',[])}
    provenance={'model_call_id':call.id,'provider_id':call.provider_id,'model':call.provider_snapshot['model'],'prompt_version':call.prompt_version,'simulated':call.simulated,'reviewed':True,'draft_revision':call.draft_revision}
    if body.save_mode=='source_new_version':
        if source_entity.kind!='script':raise HTTPException(422,'小说或分集改编必须保存为新剧本')
        source_entity=db.scalar(select(StoryEntity).where(StoryEntity.id==source_entity.id).with_for_update())
        if source_entity.current_version!=source_version.number or body.expected_source_version!=source_entity.current_version:raise HTTPException(409,'原稿已更新，请合并或保存为独立剧本')
        normalized,refs=validate_content(db,call.project_id,'script',content)
        source_entity.current_version+=1
        accepted=append_version(db,source_entity,parsed['title'],normalized,refs,'model-review:'+call.id,body.note,provenance)
    else:
        source_entity,accepted=create_entity(db,call.project_id,'script',parsed['title'],content,'model-review:'+call.id,body.note,provenance)
    for episode in parsed['episodes']:
        create_entity(db,call.project_id,'episode',episode['title'],{'number':episode['number'],'body':episode['synopsis'],'summary':'人工确认的分集大纲，尚需扩写为完整分集剧本','source_version_id':accepted.id},f'model-outline:{call.id}:{episode["number"]}',body.note,provenance)
    call.accepted_version_id=accepted.id;call.status='accepted';call.review={'request':request,'accepted_version_id':accepted.id,'dialogues':parsed['dialogues']}
    event(db,task,'人工确认后保存创作版本：'+accepted.id)
    sync_task_after_manual_action(task,call)
    return call

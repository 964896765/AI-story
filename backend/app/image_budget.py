"""Shared P5 budget accounting for explicitly authorized image calls."""
import os

from fastapi import HTTPException
from sqlalchemy import select

from .image_adapter import BASE_URL
from .models import ModelBudget, ModelConnectionDraft, ModelLedger, now
from .text_adapters import configured_key, redact
from .text_service import enforce_global_ceiling, lock_global_budget

MODELS = ('gpt-image-1','gpt-image-1-mini','gpt-image-1.5')


def authorized_project(project_id):
    return (os.getenv('AI_STORY_ENABLE_PAID_IMAGE')=='1'
            and os.getenv('AI_STORY_BUDGET_GUARD_APPROVED')=='1'
            and bool(os.getenv('AI_STORY_LIVE_AUTHORIZATION_ID'))
            and os.getenv('AI_STORY_IMAGE_PROJECT_ID')==project_id)


def configuration(db, project_id):
    if not authorized_project(project_id):
        raise HTTPException(403,'当前项目真实图片调用未授权')
    draft = db.get(ModelConnectionDraft,'openai-image')
    if not draft:
        raise HTTPException(409,'请先保存 OpenAI 图片连接配置')
    settings = draft.settings
    model = settings['model']
    currency = os.getenv('AI_STORY_IMAGE_CURRENCY','')
    price_source = os.getenv('AI_STORY_IMAGE_PRICE_SOURCE','').strip()
    secret_name = settings['secret_env']
    try:
        upper = int(os.getenv('AI_STORY_IMAGE_MAX_MICROS','0'))
    except ValueError:
        upper = 0
    if (settings['base_url'].rstrip('/')!=BASE_URL or model not in MODELS or model!=os.getenv('AI_STORY_IMAGE_MODEL')
        or not secret_name or secret_name!=os.getenv('AI_STORY_IMAGE_SECRET_ENV') or not configured_key(settings)):
        raise HTTPException(409,'真实图片端点、模型或本机密钥未获授权')
    if currency not in ('CNY','USD') or not 0<upper<=10**12 or not 0<len(price_source)<=500:
        raise HTTPException(409,'图片价格上限未核验，禁止发送')
    return {'model':model,'currency':currency,'upper_bound_micros':upper,
            'price_source':redact(price_source,configured_key(settings)),
            'authorization_id':os.getenv('AI_STORY_LIVE_AUTHORIZATION_ID'),'secret_env':secret_name}


def account(db, project_id, quote):
    budget = db.scalar(select(ModelBudget).where(ModelBudget.project_id==project_id,ModelBudget.mode=='live',
        ModelBudget.currency==quote['currency']).with_for_update())
    if not budget or budget.halted or budget.authorization_id!=quote['authorization_id'] or budget.limit_micros<=0:
        raise HTTPException(409,'当前项目真实预算未授权、额度为零或已冻结')
    return budget


def record(db, task, budget, kind, amount, note=''):
    db.add(ModelLedger(budget_id=budget.id,kind=kind,amount_micros=amount,
        reference=f'image:{task.id}:{kind}',note=note))


def reserve(db, task, quote):
    budget = account(db,task.project_id,quote)
    upper = quote['upper_bound_micros']
    enforce_global_ceiling(db,quote['currency'],upper)
    fixed_limit = task.input_snapshot['production_spec']['settings']['budget_cents']*10_000
    if budget.reserved_micros+budget.spent_micros+upper>min(budget.limit_micros,fixed_limit):
        raise HTTPException(409,'项目真实预算不足')
    budget.reserved_micros += upper
    record(db,task,budget,'reserve',upper)
    task.output = {'billing':{'state':'reserved','currency':quote['currency'],
                   'reserved_micros':upper,'actual_cost_micros':None,'budget_id':budget.id}}


def change(db, task, amount, note):
    """Record an invoice amount or a proven release. Task row is already locked."""
    billing = task.output['billing']
    budget = db.scalar(select(ModelBudget).where(ModelBudget.id==billing['budget_id']).with_for_update())
    lock_global_budget(db)
    budget.reserved_micros -= billing['reserved_micros']
    if amount is None:
        state, kind = 'released', 'release'
        record(db,task,budget,kind,billing['reserved_micros'],note)
    else:
        state, kind = 'settled', 'settle'
        budget.spent_micros += amount
        if amount>billing['reserved_micros'] or budget.spent_micros+budget.reserved_micros>budget.limit_micros:
            budget.halted = True
        record(db,task,budget,kind,amount,note)
    task.output = {**task.output,'billing':{**billing,'state':state,'actual_cost_micros':amount or 0,'evidence':note}}


def before_dispatch(db, task):
    quote = task.input_snapshot['quote']
    if quote!=configuration(db,task.project_id):
        raise HTTPException(409,'发送前图片授权或价格快照已变化')
    budget = account(db,task.project_id,quote)
    enforce_global_ceiling(db,quote['currency'],0)
    fixed_limit = task.input_snapshot['production_spec']['settings']['budget_cents']*10_000
    if budget.reserved_micros+budget.spent_micros>min(budget.limit_micros,fixed_limit):
        raise HTTPException(409,'发送前固定规格预算不足')
    credential = configured_key(quote)
    if not credential:
        raise HTTPException(409,'发送前图片密钥已撤销')
    task.output = {**task.output,'billing':{**task.output['billing'],'state':'awaiting_invoice','sent_at':now().isoformat()}}
    return credential


def release_unsent(db, task, note):
    if task.output.get('billing',{}).get('state')=='reserved':
        change(db,task,None,note)

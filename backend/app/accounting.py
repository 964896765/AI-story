"""Exact amounts and idempotent CSV settlement imports."""
import csv
from datetime import date
from decimal import Decimal
from io import StringIO
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, ValidationError, model_validator
from sqlalchemy import func, select

from .analysis_service import fingerprint
from .creative import require
from .db import session
from .models import ChannelProfile, CostEntry, ModelCall, Project, SettlementEntry
from .story_schemas import Strict

router=APIRouter(prefix='/api/finance',tags=['production-accounting'])
COLUMNS=['external_id','currency','kind','status','amount','period_start','period_end','evidence']
DECIMAL=re.compile(r'\d{1,12}(?:\.\d{1,6})?')


class Row(Strict):
    external_id: str=Field(min_length=1,max_length=150,pattern=r'.*\S.*')
    currency: Literal['CNY','USD']
    kind: Literal['cash','ad_credit','expense','cash_refund']
    status: Literal['confirmed','estimate','unknown']
    amount: str=Field(max_length=20)
    period_start: date
    period_end: date
    evidence: str=Field(min_length=6,max_length=4000,pattern=r'.*\S.*')

    @model_validator(mode='after')
    def amount_and_period(self):
        if self.period_start>self.period_end:raise ValueError('账期顺序无效')
        if self.status=='unknown':
            if self.amount:raise ValueError('未知金额留空')
        elif not DECIMAL.fullmatch(self.amount):
            raise ValueError('金额须为非负十进制值，最多六位小数')
        return self

    def micros(self):
        return int(Decimal(self.amount)*1_000_000) if self.amount else None


class Import(Strict):
    channel_id: str=Field(min_length=1,max_length=36)
    csv: str=Field(min_length=1,max_length=512000)


class Entry(Strict):
    channel_id: str=Field(min_length=1,max_length=36)
    line: Row


def account_scope(channel):
    details=channel.details
    return fingerprint([channel.project_id,channel.platform,channel.region,
        details['organization'].strip().casefold(),details['account_label'].strip().casefold()])


def record_rows(db,project,channel_id,lines):
    if not db.scalar(select(Project.id).where(Project.id==project).with_for_update()):
        raise HTTPException(404,'项目不存在')
    channel=require(db,ChannelProfile,channel_id)
    if channel.project_id!=project:raise HTTPException(422,'渠道不属于当前项目')
    scope=account_scope(channel)
    prior={row.external_id:row.source_hash for row in db.scalars(select(SettlementEntry).where(
        SettlementEntry.account_scope==scope,SettlementEntry.external_id.in_({item.external_id for item in lines})))}
    inserted,duplicates=0,0
    for line in lines:
        amount=line.micros()
        detail=line.model_dump(mode='json',exclude={'amount'})
        digest=fingerprint([detail,amount])
        if line.external_id in prior:
            if prior[line.external_id]!=digest:
                raise HTTPException(409,f'账单条目 {line.external_id} 与已有凭证不一致')
            duplicates+=1
            continue
        db.add(SettlementEntry(channel_id=channel.id,account_scope=scope,external_id=line.external_id,
            currency=line.currency,status=line.status,kind=line.kind,amount_micros=amount,
            source_hash=digest,details=detail))
        prior[line.external_id]=digest
        inserted+=1
    db.commit()
    return {'inserted':inserted,'duplicates':duplicates}


def parse_csv(value):
    if len(value.encode('utf-8'))>512000:raise HTTPException(422,'CSV 超过 512 KB')
    rows=[]
    try:
        reader=csv.DictReader(StringIO(value.removeprefix('\ufeff')),strict=True)
        if reader.fieldnames!=COLUMNS:
            raise HTTPException(422,'CSV 列顺序须为 '+','.join(COLUMNS))
        for index,row in enumerate(reader,2):
            if len(rows)>=1000:raise HTTPException(422,'单次最多 1000 条')
            try:
                rows.append(Row.model_validate(row))
            except ValidationError:
                raise HTTPException(422,f'CSV 第 {index} 行字段、金额或账期无效') from None
    except csv.Error:
        raise HTTPException(422,'CSV 格式无效') from None
    if not rows:raise HTTPException(422,'CSV 中没有结算记录')
    return rows


@router.post('/projects/{project_id}/settlements/import',status_code=201)
def import_csv(project_id:str,body:Import,db=Depends(session)):
    return record_rows(db,project_id,body.channel_id,parse_csv(body.csv))


@router.post('/projects/{project_id}/settlements',status_code=201)
def manual_entry(project_id:str,body:Entry,db=Depends(session)):
    return record_rows(db,project_id,body.channel_id,[body.line])


@router.get('/projects/{project_id}/settlements')
def entries(project_id:str,db=Depends(session)):
    require(db,Project,project_id)
    result=db.execute(select(SettlementEntry,ChannelProfile.label)
        .join(ChannelProfile,ChannelProfile.id==SettlementEntry.channel_id)
        .where(ChannelProfile.project_id==project_id)
        .order_by(SettlementEntry.created_at.desc(),SettlementEntry.id).limit(100)).all()
    return [{'id':row.id,'channel':label,'amount_micros':str(row.amount_micros) if row.amount_micros is not None else None,
             **row.details} for row,label in result]


@router.get('/projects/{project_id}/summary')
def summary(project_id:str,db=Depends(session)):
    require(db,Project,project_id)
    grouped=db.execute(select(SettlementEntry.currency,SettlementEntry.kind,SettlementEntry.status,
        func.sum(SettlementEntry.amount_micros),func.count())
        .join(ChannelProfile,ChannelProfile.id==SettlementEntry.channel_id)
        .where(ChannelProfile.project_id==project_id)
        .group_by(SettlementEntry.currency,SettlementEntry.kind,SettlementEntry.status)).all()
    old_cost=db.execute(select(CostEntry.currency,func.sum(CostEntry.amount_cents))
        .where(CostEntry.project_id==project_id).group_by(CostEntry.currency)).all()
    currency_label=ModelCall.provider_snapshot['currency'].as_string().label('model_cost_currency')
    model_cost=db.execute(select(currency_label,
        func.sum(ModelCall.actual_cost_micros),func.count()-func.count(ModelCall.actual_cost_micros))
        .where(ModelCall.project_id==project_id,ModelCall.simulated.is_(False),ModelCall.sent_at.is_not(None))
        .group_by('model_cost_currency')).all()
    result={}
    def group(currency):
        return result.setdefault(currency,{'cash':0,'ad_credit':0,'expense':0,'cash_refund':0,
            'booked_api':0,'unknown_entries':0,'estimate_entries':0,'unknown_model_charges':0})
    for currency,kind,status,amount,count in grouped:
        bucket=group(currency)
        if status=='confirmed':bucket[kind]+=int(amount)
        elif status=='unknown':bucket['unknown_entries']+=count
        else:bucket['estimate_entries']+=count
    for currency,cents in old_cost:
        group(currency)['booked_api']+=int(cents)*10_000
    for currency,amount,unknown in model_cost:
        bucket=group(currency)
        bucket['booked_api']+=int(amount or 0)
        bucket['unknown_model_charges']+=int(unknown)
    return {'scope':'recorded_only','by_currency':[
        {'currency':currency,'recorded_cash_difference_micros':str(bucket['cash']-bucket['cash_refund']-bucket['expense']-bucket['booked_api']),
         'amounts_micros':{name:str(bucket[name]) for name in ('cash','ad_credit','expense','cash_refund','booked_api')},
         **{name:bucket[name] for name in ('unknown_entries','estimate_entries','unknown_model_charges')}}
        for currency,bucket in sorted(result.items())]}

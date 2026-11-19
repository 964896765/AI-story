"""Local work catalog and append-only source-rights ledger."""
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import func, select

from .analysis_service import fingerprint
from .creative import VIDEO, require
from .db import session
from .models import Asset, AssetRight, LibraryEpisode, LibraryWork, Project, now
from .story_schemas import Strict

router = APIRouter(prefix='/api/library',tags=['library-and-rights'])
Slug = Annotated[str,Field(min_length=1,max_length=40,pattern=r'^[a-z0-9_-]+$')]
Region = Annotated[str,Field(pattern=r'^([A-Z]{2}|WORLD)$')]


class SourceEpisode(Strict):
    number: int=Field(ge=1,le=1000)
    title: str=Field(min_length=1,max_length=200,pattern=r'.*\S.*')
    asset_id: str=Field(min_length=1,max_length=36)


class CatalogInput(Strict):
    title: str=Field(min_length=1,max_length=200,pattern=r'.*\S.*')
    origin: str=Field(min_length=1,max_length=4000,pattern=r'.*\S.*')
    tags: list[Annotated[str,Field(min_length=1,max_length=60)]]=Field(default_factory=list,max_length=24)
    episodes: list[SourceEpisode]=Field(min_length=1,max_length=300)
    idempotency_key: str=Field(min_length=1,max_length=64)


class RightsInput(Strict):
    status: Literal['approved','pending','revoked']
    source_type: Literal['owned','licensed']
    holder: str=Field(min_length=1,max_length=300,pattern=r'.*\S.*')
    evidence: str=Field(min_length=6,max_length=8000,pattern=r'.*\S.*')
    commercial: bool=False
    regions: list[Region]=Field(default_factory=list,max_length=80)
    platforms: list[Slug]=Field(default_factory=list,max_length=24)
    valid_from: AwareDatetime | None=None
    expires_at: AwareDatetime | None=None
    idempotency_key: str=Field(min_length=1,max_length=64)

    @model_validator(mode='after')
    def valid_scope(self):
        if self.valid_from and self.expires_at and self.valid_from>=self.expires_at:
            raise ValueError('授权有效期的终点须晚于起点')
        if self.status=='approved' and self.commercial and (not self.regions or not self.platforms):
            raise ValueError('批准的商用授权需登记地域和平台')
        return self


def right_public(row):
    return {'id':row.id,'asset_id':row.asset_id,'revision':row.revision,'status':row.status,
            'source_type':row.source_type,'holder':row.holder,'scope':row.scope,
            'starts_at':row.starts_at,'expires_at':row.expires_at,'evidence':row.evidence,
            'created_at':row.created_at}


def latest_rights(db,asset_ids):
    result={}
    for row in db.scalars(select(AssetRight).distinct(AssetRight.asset_id).where(AssetRight.asset_id.in_(asset_ids))
                          .order_by(AssetRight.asset_id,AssetRight.revision.desc())):
        result.setdefault(row.asset_id,row)
    return result


def restriction(row,platform,region,at:datetime):
    if row is None or row.status!='approved':
        return '权利记录待核验或已撤回'
    if row.starts_at and at<row.starts_at:
        return '权利尚未生效'
    if row.expires_at and at>=row.expires_at:
        return '权利已到期'
    if not row.scope['commercial']:
        return '权利未覆盖商用交付'
    if platform not in row.scope['platforms'] or not ({region,'WORLD'} & set(row.scope['regions'])):
        return '目标平台或地域超出授权'
    return None


def work_public(db,work,*,detail=True):
    response={'id':work.id,'title':work.title,'origin':work.origin,'tags':work.tags,
              'created_at':work.created_at,'archived':bool(work.archived_at)}
    if detail:
        entries=db.execute(select(LibraryEpisode,Asset).join(Asset,Asset.id==LibraryEpisode.asset_id)
                           .where(LibraryEpisode.work_id==work.id).order_by(LibraryEpisode.number)).all()
        response['episodes']=[{'number':row.number,'title':row.title,'asset_id':asset.id,'name':asset.name,
                              'sha256':asset.sha256,'size_bytes':asset.size_bytes} for row,asset in entries]
    return response


@router.get('/projects/{project_id}/works')
def works(project_id:str,q:str=Query('',max_length=200),tag:str=Query('',max_length=60),
          offset:int=Query(0,ge=0),limit:int=Query(30,ge=1,le=100),db=Depends(session)):
    require(db,Project,project_id)
    conditions=[LibraryWork.project_id==project_id,LibraryWork.archived_at.is_(None)]
    if q:conditions.append(LibraryWork.title.icontains(q,autoescape=True))
    if tag:conditions.append(LibraryWork.tags.contains([tag]))
    rows=db.scalars(select(LibraryWork).where(*conditions).order_by(LibraryWork.created_at.desc(),LibraryWork.id)
                    .offset(offset).limit(limit)).all()
    total=db.scalar(select(func.count()).select_from(LibraryWork).where(*conditions))
    return {'items':[work_public(db,row,detail=False) for row in rows],'total':total}


@router.post('/projects/{project_id}/works',status_code=201)
def create_work(project_id:str,body:CatalogInput,db=Depends(session)):
    if not db.scalar(select(Project.id).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    digest=fingerprint(body.model_dump(exclude={'idempotency_key'}))
    earlier=db.scalar(select(LibraryWork).where(LibraryWork.project_id==project_id,
                        LibraryWork.request_key==body.idempotency_key))
    if earlier:
        if earlier.request_hash!=digest:raise HTTPException(409,'资源导入请求键已用于其他作品')
        return work_public(db,earlier)
    numbers=[item.number for item in body.episodes]
    if len(set(numbers))!=len(numbers):raise HTTPException(422,'分集序号不能重复')
    ids={item.asset_id for item in body.episodes}
    mapped={asset.id:asset for asset in db.scalars(select(Asset).where(Asset.project_id==project_id,Asset.id.in_(ids)))}
    if set(mapped)!=ids or any(not any(asset.storage_key.endswith(ext) for ext in VIDEO) for asset in mapped.values()):
        raise HTTPException(422,'分集素材必须是同项目已导入的音视频文件')
    work=LibraryWork(project_id=project_id,title=body.title,origin=body.origin,tags=list(dict.fromkeys(body.tags)),
                     request_key=body.idempotency_key,request_hash=digest)
    db.add(work)
    db.flush()
    db.add_all([LibraryEpisode(work_id=work.id,number=item.number,title=item.title,asset_id=item.asset_id)
                for item in body.episodes])
    db.commit()
    return work_public(db,work)


@router.get('/works/{work_id}')
def work(work_id:str,db=Depends(session)):
    return work_public(db,require(db,LibraryWork,work_id))


@router.post('/works/{work_id}/archive')
def archive(work_id:str,db=Depends(session)):
    work=require(db,LibraryWork,work_id)
    if not work.archived_at:
        work.archived_at=now()
        db.commit()
    return work_public(db,work,detail=False)


@router.get('/assets/{asset_id}/rights')
def rights(asset_id:str,db=Depends(session)):
    require(db,Asset,asset_id)
    rows=db.scalars(select(AssetRight).where(AssetRight.asset_id==asset_id)
                    .order_by(AssetRight.revision.desc()).limit(100)).all()
    return [right_public(row) for row in rows]


@router.post('/assets/{asset_id}/rights',status_code=201)
def record_right(asset_id:str,body:RightsInput,db=Depends(session)):
    asset=db.scalar(select(Asset).where(Asset.id==asset_id).with_for_update())
    if not asset:raise HTTPException(404,'素材不存在')
    digest=fingerprint(body.model_dump(mode='json',exclude={'idempotency_key'}))
    earlier=db.scalar(select(AssetRight).where(AssetRight.asset_id==asset_id,AssetRight.request_key==body.idempotency_key))
    if earlier:
        if earlier.request_hash!=digest:raise HTTPException(409,'权利记录请求键已用于其他内容')
        return right_public(earlier)
    ordinal=db.scalar(select(func.max(AssetRight.revision)).where(AssetRight.asset_id==asset_id)) or 0
    row=AssetRight(asset_id=asset_id,revision=ordinal+1,status=body.status,source_type=body.source_type,
                   holder=body.holder,evidence=body.evidence,scope={'commercial':body.commercial,
                    'regions':body.regions,'platforms':body.platforms},
                   starts_at=body.valid_from,expires_at=body.expires_at,
                   request_key=body.idempotency_key,request_hash=digest)
    db.add(row)
    db.commit()
    return right_public(row)

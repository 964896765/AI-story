"""Resolve a workspace location against one approved plan in the current project."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from .creative import require
from .db import session
from .guardian import latest_approved
from .models import ProductionEpisode, ProductionRun, Project, StoryEntity, StoryVersion
from .series import series_report

router = APIRouter(prefix='/api/projects',tags=['workspace-context'])
Identifier = Annotated[str,Query(min_length=1,max_length=36)]


@router.get('/{project_id}/workspace-context')
def resolve(project_id: str, plan: Identifier | None = None, run: Identifier | None = None,
            episode: Annotated[int,Query(ge=1,le=50)] | None = None,
            shot: Annotated[str,Query(pattern=r'^[A-Za-z0-9_-]{1,100}$')] | None = None, db=Depends(session)):
    require(db,Project,project_id)
    batch = None
    if run:
        batch = db.scalar(select(ProductionRun).where(ProductionRun.id==run,ProductionRun.project_id==project_id))
        if batch is None:
            raise HTTPException(404,'当前项目没有此批次')
        if plan and batch.plan_version_id!=plan:
            raise HTTPException(409,'批次引用了另一固定计划版本')
        plan = batch.plan_version_id
    if not plan:
        raise HTTPException(422,'请选择固定计划或生产批次')
    fixed = db.execute(select(StoryEntity,StoryVersion).join(StoryVersion,StoryVersion.entity_id==StoryEntity.id)
                       .where(StoryEntity.project_id==project_id,StoryEntity.kind=='story_bible',StoryVersion.id==plan)).one_or_none()
    if fixed is None or not fixed[1].provenance.get('series_approved'):
        raise HTTPException(404,'当前项目没有此已批准计划')
    entity, version = fixed
    report = series_report(db,entity,version)
    current = latest_approved(db,entity.id)
    by_number = {item['number']:item for item in report['episodes']}
    selected = None
    if shot:
        for item in report['episodes']:
            selected = next((row for row in item['shots'] if row['shot_id']==shot),None)
            if selected:
                if episode and item['number']!=episode:
                    raise HTTPException(409,'镜头不属于链接中的分集')
                episode = item['number']
                break
        if selected is None:
            raise HTTPException(404,'固定计划没有此镜头')
    if episode and episode not in by_number:
        raise HTTPException(404,'固定计划没有此分集')
    if batch and episode and db.get(ProductionEpisode,(batch.id,episode)) is None:
        raise HTTPException(404,'该批次没有此分集')
    detail = by_number.get(episode)
    spec = report.get('production_spec')
    return {'plan':{'id':version.id,'title':version.title,'version':version.number,'historical':current.id!=version.id},
            'run_id':batch.id if batch else None,
            'production_spec':{key:spec[key] for key in ('id','version','sha256')} if spec else None,
            'episodes':[{'number':item['number'],'title':item['title']} for item in report['episodes']],
            'episode':{key:detail[key] for key in ('number','title','storyboard_version_id','episode_version_id')}
                       if detail else None,
            'shot':selected['shot_id'] if selected else None,
            'shots':[{'id':row['shot_id'],'number':row['number'],'description':row['description'],
                      'contract_sha256':(row.get('guardian') or {}).get('contract_sha256')} for row in detail['shots']] if detail else []}

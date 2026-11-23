"""Read-only project overview built from the existing production records."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from .accounting import summary as accounting_summary
from .asset_validation import IMAGE_SUFFIXES
from .creative import require
from .db import session
from .models import Asset, DirectorPlan, ModelBudget, ModelCall, ProductionRun, Project, StoryEntity, StoryVersion, Task
from .director_guidance import PROMPT_VERSION as DIRECTOR_PROMPT_VERSION
from .production import public as production_summary
from .text_adapters import live_gate
from .production_specs import current as current_spec

router = APIRouter(prefix='/api/projects', tags=['project-overview'])


@router.get('/{project_id}/overview')
def overview(project_id: str, db=Depends(session)):
    project = require(db, Project, project_id)
    task_counts = dict(db.execute(select(Task.status, func.count()).where(
        Task.project_id == project.id).group_by(Task.status)).all())
    story_counts = dict(db.execute(select(StoryEntity.kind, func.count()).where(
        StoryEntity.project_id == project.id).group_by(StoryEntity.kind)).all())
    asset_scope = Asset.project_id == project.id
    asset_count = db.scalar(select(func.count()).select_from(Asset).where(asset_scope))
    suffix = func.lower(func.substring(Asset.name, r'\.[^.]+$'))
    cover = db.execute(select(Asset.id, Asset.name).where(asset_scope, suffix.in_(tuple(IMAGE_SUFFIXES)))
                       .order_by(Asset.created_at.desc(), Asset.id).limit(1)).mappings().first()

    renders = (Task.project_id == project.id, Task.status == 'succeeded', Task.kind.in_(('render', 'timeline_render')),
               Task.output['storage_key'].as_string().is_not(None))
    render_count = db.scalar(select(func.count()).select_from(Task).where(*renders))
    delivery_count = db.scalar(select(func.count()).select_from(Task).where(
        Task.project_id == project.id, Task.kind == 'delivery', Task.status == 'succeeded'))
    recent = db.execute(select(Task, StoryVersion.title, Asset.name).select_from(Task)
        .outerjoin(StoryVersion, StoryVersion.id == Task.story_version_id)
        .outerjoin(Asset, (Asset.id == Task.asset_id) & asset_scope)
        .where(*renders).order_by(Task.finished_at.desc().nulls_last(), Task.created_at.desc(), Task.id).limit(4))
    outputs = [{'id': task.id, 'title': title or name or '多轨成片', 'finished_at': task.finished_at or task.created_at,
                'duration': task.output.get('duration'), 'width': task.output.get('width'), 'height': task.output.get('height')}
               for task, title, name in recent]

    review_scope = (ModelCall.project_id == project.id, ModelCall.status == 'awaiting_review',
                    ModelCall.prompt_version != DIRECTOR_PROMPT_VERSION)
    draft_count = db.scalar(select(func.count()).select_from(ModelCall).where(*review_scope))
    calls = db.execute(select(ModelCall.id, ModelCall.simulated, StoryVersion.title)
        .join(StoryVersion, StoryVersion.id == ModelCall.source_version_id).where(*review_scope)
        .order_by(ModelCall.created_at.desc(), ModelCall.id).limit(4))
    draft_reviews = [{'id': call_id, 'simulated': simulated, 'title': title} for call_id, simulated, title in calls]

    batch = db.scalar(select(ProductionRun).where(ProductionRun.project_id == project.id)
                      .order_by(ProductionRun.created_at.desc(), ProductionRun.id).limit(1))
    batch_view = None
    delivery_view = None
    if batch:
        result = production_summary(db, batch)
        batch_view = {key: result[key] for key in ('id', 'status', 'passed', 'episode_count')}
        batch_view['reviews'] = sum(episode['status'] == 'needs_review' for episode in result['episodes'])
        batch_view['rework'] = sum(episode['status'] == 'needs_rework' for episode in result['episodes'])
        batch_view['attention_episodes'] = [
            {'number': episode['number'], 'status': episode['status'], 'issue_count': episode['issue_count']}
            for episode in result['episodes'] if episode['status'] in ('needs_review', 'needs_rework')
        ][:8]
        task = db.scalar(select(Task).where(Task.project_id == project.id, Task.kind == 'delivery',
                         Task.parameters['run_id'].as_string() == batch.id).order_by(
                             Task.created_at.desc(), Task.id).limit(1))
        if task:
            delivery_view = {'id': task.id, 'run_id': batch.id, 'status': task.status,
                             'title': task.parameters.get('title')}

    budgets = db.scalars(select(ModelBudget).where(ModelBudget.project_id == project.id, ModelBudget.mode == 'live')
                         .order_by(ModelBudget.currency)).all()
    accounts = accounting_summary(project.id, db)['by_currency']
    approved_series_id = db.scalar(select(StoryVersion.id).join(StoryEntity).where(
        StoryEntity.project_id == project.id, StoryEntity.kind == 'story_bible',
        StoryVersion.provenance['series_approved'].as_boolean().is_(True),
    ).order_by(StoryVersion.created_at.desc(), StoryVersion.number.desc()).limit(1))
    director_plan_id = db.scalar(select(DirectorPlan.id).where(DirectorPlan.project_id == project.id)
                                 .order_by(DirectorPlan.created_at.desc()).limit(1))
    adaptation_source_id = db.scalar(select(StoryVersion.id).join(StoryEntity).where(
        StoryEntity.project_id == project.id, StoryEntity.kind.in_(('novel', 'episode')),
        StoryVersion.number == StoryEntity.current_version,
    ).order_by((StoryEntity.kind == 'novel').desc(), StoryVersion.created_at.desc()).limit(1))
    adopted_candidates = db.scalar(select(func.count()).select_from(Asset).where(
        asset_scope, Asset.media_info['origin'].as_string() == 'local_still_motion'))
    spec = current_spec(db,project_id)
    return {'asset_count': asset_count, 'cover': dict(cover) if cover else None, 'task_counts': task_counts,
            'story_counts': story_counts, 'render_count': render_count, 'delivery_count': delivery_count, 'recent_renders': outputs,
            'workflow': {'approved_series_id': approved_series_id, 'director_plan_id': director_plan_id,
                         'adopted_candidates': adopted_candidates, 'adaptation_source_id': adaptation_source_id,
                         'production_spec': {'id':spec.id,'version':spec.number} if spec else None},
            'draft_review_count': draft_count, 'draft_reviews': draft_reviews, 'latest_run': batch_view,
            'latest_delivery': delivery_view,
            'costs': [{'currency': item['currency'], 'amount_micros': item['amounts_micros']['booked_api'],
                       'unknown': item['unknown_model_charges']} for item in accounts],
            'live_authorized': live_gate(), 'live_budgets': [{'currency': row.currency,
                'limit_micros': str(row.limit_micros), 'reserved_micros': str(row.reserved_micros), 'halted': row.halted}
                for row in budgets]}

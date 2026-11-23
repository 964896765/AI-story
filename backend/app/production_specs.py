"""Project-scoped, append-only production specifications and approval checks."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, StringConstraints
from sqlalchemy import func, select

from .analysis_service import fingerprint
from .db import session
from .models import DirectorPlan, ProductionSpec, Project, StoryEntity, StoryVersion, Task
from .story_schemas import Strict, VersionId

router = APIRouter(prefix='/api/projects/{project_id}/production-specs', tags=['production-specs'])
FRAME_SIZES = {'portrait': (720, 1280), 'landscape': (1280, 720), 'square': (720, 720)}
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]
IMPACTS = {
    'episode_count': ('导演','剧本','分镜','调度','交付'),
    'episode_duration_ms': ('导演','剧本','分镜','配音','时间轴','渲染','Guardian','交付'),
    'style': ('导演','人物与场景','分镜','图片','视频','Guardian'),
    'profile': ('分镜','图片','视频','时间轴','渲染','Guardian','交付'),
    'width': ('图片','视频','时间轴','渲染','Guardian','交付'),
    'height': ('图片','视频','时间轴','渲染','Guardian','交付'),
    'fps': ('分镜','视频','配音','时间轴','渲染','Guardian','交付'),
    'platform': ('导演','Guardian','交付'),
    'region': ('导演','交付'),
    'budget_cents': ('导演','预算','调度'),
    'budget_currency': ('导演','预算','调度'),
    'restrictions': ('导演','剧本','人物与场景','分镜','图片','视频','配音','Guardian','交付'),
}


class Settings(Strict):
    episode_count: int | None = Field(None, ge=1, le=50, strict=True)
    episode_duration_ms: int | None = Field(None, ge=500, le=600_000, strict=True)
    style: Text = ''
    profile: Literal['portrait','landscape','square'] | None = None
    width: int | None = Field(None, ge=2, le=8192, strict=True)
    height: int | None = Field(None, ge=2, le=8192, strict=True)
    fps: int | None = Field(None, ge=1, le=120, strict=True)
    platform: str = Field('', pattern=r'^(?:[a-z0-9_-]{1,40})?$')
    region: str = Field('', pattern=r'^(?:[A-Z]{2}|WORLD)?$')
    budget_cents: int | None = Field(None, ge=0, le=10**10, strict=True)
    budget_currency: Literal['CNY','USD'] = 'CNY'
    restrictions: Text = ''
    imported_note: str = Field('', max_length=4000)


class Operation(Strict):
    expected_version: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r'\S')


class SaveSpec(Operation):
    settings: Settings


class RestoreSpec(Operation):
    source_version_id: VersionId


def compatibility(settings):
    required = ('episode_count','episode_duration_ms','style','profile','width','height','fps','platform','region','budget_cents')
    missing = [key for key in required if settings.get(key) is None or settings[key] == '']
    if missing:
        return missing, []
    errors = []
    if settings['fps'] != 24:
        errors.append('本机生产固定为 24 fps')
    if (settings['width'],settings['height']) != FRAME_SIZES[settings['profile']]:
        errors.append('输出分辨率须匹配本机画幅预设')
    return [], errors


def public(row):
    missing, errors = compatibility(row.settings)
    return {'id':row.id,'version':row.number,'sha256':row.sha256,'settings':row.settings,
            'missing_fields':missing,'compatibility_errors':errors,'restored_from_id':row.restored_from_id,
            'created_at':row.created_at}


def current(db, project_id):
    return db.scalar(select(ProductionSpec).where(ProductionSpec.project_id == project_id)
                     .order_by(ProductionSpec.number.desc()).limit(1))


def resolve(db, project_id, key):
    row = db.get(ProductionSpec,key)
    if row is None or row.project_id != project_id:
        raise HTTPException(404,'规格版本不存在或不属于当前项目')
    return row


def pinned(db, project_id, content):
    key = content.get('production_spec_version_id')
    return public(resolve(db,project_id,key)) if key else None


def approval_spec(db, project_id, content, *, require_pin=False):
    spec = pinned(db,project_id,content)
    if spec and (spec['missing_fields'] or spec['compatibility_errors']):
        raise HTTPException(422,'固定制作规格不完整或超出本机生产能力')
    if not spec and require_pin and current(db,project_id):
        raise HTTPException(422,'请固定一份完整的项目制作规格')
    return spec


def task_fields(spec):
    if not spec:
        return {}
    return {'production_spec': {'id':spec['id'],'version':spec['version'],'sha256':spec['sha256'],
                               'settings':business_settings(spec['settings'])}}


def business_settings(settings):
    return {key:value for key,value in settings.items() if key!='imported_note'}


def verify_profile(spec, profile):
    if spec and profile != spec['settings']['profile']:
        raise HTTPException(422,'画幅与固定制作规格不一致')


def verify_timeline(spec, timeline):
    verify_profile(spec,timeline.profile)
    if spec:
        target = spec['settings']['episode_duration_ms']
        if abs(round(timeline.frames*1000/timeline.frame_rate)-target)>max(250,round(target*0.03)):
            raise HTTPException(422,'时间轴时长与固定制作规格不一致')


@router.get('')
def history(project_id: str, offset: int = Query(0, ge=0), db=Depends(session)):
    if not db.get(Project,project_id):
        raise HTTPException(404,'项目不存在')
    rows = db.scalars(select(ProductionSpec).where(ProductionSpec.project_id == project_id)
                      .order_by(ProductionSpec.number.desc()).offset(offset).limit(51)).all()
    return {'items':[public(row) for row in rows[:50]], 'has_more':len(rows)>50}


@router.get('/compare')
def compare(project_id: str, left: str, right: str, db=Depends(session)):
    before, after = resolve(db,project_id,left), resolve(db,project_id,right)
    fields = [{'key':key,'before':value,'after':after.settings.get(key),'modules':IMPACTS.get(key,())}
              for key,value in before.settings.items() if value != after.settings.get(key)]
    usage = dict(db.execute(select(StoryEntity.kind,func.count()).join(StoryVersion)
        .where(StoryEntity.project_id==project_id,StoryVersion.content['production_spec_version_id'].as_string()==left)
        .group_by(StoryEntity.kind)).all())
    usage['director'] = db.scalar(select(func.count()).select_from(DirectorPlan).where(
        DirectorPlan.project_id==project_id, DirectorPlan.production_spec_version_id==left))
    usage['tasks'] = db.scalar(select(func.count()).select_from(Task).where(
        Task.project_id==project_id, Task.input_snapshot['production_spec']['id'].as_string()==left))
    return {'left':public(before),'right':public(after),'changes':fields,
            'affected_modules':list(dict.fromkeys(module for field in fields for module in field['modules'])),
            'pinned_references':usage}


@router.get('/{version_id}')
def get_version(project_id: str, version_id: str, db=Depends(session)):
    return public(resolve(db,project_id,version_id))


def append(db, project_id, body, settings, restored_from=None):
    if not db.scalar(select(Project.id).where(Project.id==project_id).with_for_update()):
        raise HTTPException(404,'项目不存在')
    sha = fingerprint(business_settings(settings))
    previous = db.scalar(select(ProductionSpec).where(
        ProductionSpec.project_id==project_id, ProductionSpec.request_key==body.idempotency_key))
    if previous:
        if previous.settings != settings or previous.restored_from_id != restored_from or previous.number != body.expected_version+1:
            raise HTTPException(409,'请求键已用于另一项规格操作')
        return public(previous)
    latest = current(db,project_id)
    number = latest.number if latest else 0
    if number != body.expected_version:
        raise HTTPException(409,'当前规格已更新，刷新核对后再保存')
    row = ProductionSpec(project_id=project_id,number=number+1,settings=settings,sha256=sha,
                         request_key=body.idempotency_key,restored_from_id=restored_from)
    db.add(row)
    db.commit()
    return public(row)


@router.post('', status_code=201)
def save(project_id: str, body: SaveSpec, db=Depends(session)):
    return append(db,project_id,body,body.settings.model_dump())


@router.post('/restore', status_code=201)
def restore(project_id: str, body: RestoreSpec, db=Depends(session)):
    target = resolve(db,project_id,body.source_version_id)
    return append(db,project_id,body,target.settings,target.id)

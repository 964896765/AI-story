"""Record model connection drafts. No execution or vendor network checks."""
import shutil
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, field_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .db import session
from .models import ModelConnectionDraft, now
from .story_schemas import Strict
from .text_schemas import ProviderSettings

router = APIRouter(prefix='/api/models', tags=['model-connections'])
Connector = Literal['codex', 'openai-image', 'tongyi-image', 'wan-video', 'hailuo-video', 'seedance', 'kling', 'cloud-tts', 'visual-review']


class ConnectionInput(Strict):
    model: str = Field(min_length=1, max_length=160, pattern=r'^[a-zA-Z0-9_.:/-]+$')
    base_url: str = Field(default='', max_length=500)
    secret_env: str = Field(default='', max_length=128)
    region: str = Field(default='', max_length=64, pattern=r'^[a-zA-Z0-9_.-]*$')

    @field_validator('base_url')
    @classmethod
    def validate_url(cls, value):
        return ProviderSettings.safe_url(value)

    @field_validator('secret_env')
    @classmethod
    def validate_env(cls, value):
        return ProviderSettings.env_name(value)


@router.get('/connections')
def connections(db=Depends(session)):
    drafts = db.scalars(select(ModelConnectionDraft).order_by(ModelConnectionDraft.connector))
    return {'codex_cli_detected': bool(shutil.which('codex') or shutil.which('codex.cmd')),
            'drafts': {row.connector: row.settings for row in drafts},
            'execution_enabled': False}


@router.post('/connections/{connector}')
def save_connection(connector: Connector, body: ConnectionInput, db=Depends(session)):
    settings = body.model_dump()
    if connector == 'codex' and any((body.base_url, body.secret_env, body.region)):
        raise HTTPException(422, 'Codex 草稿只保存模型偏好')
    statement = insert(ModelConnectionDraft).values(connector=connector, settings=settings, updated_at=now())
    db.execute(statement.on_conflict_do_update(
        index_elements=[ModelConnectionDraft.connector],
        set_={'settings': statement.excluded.settings, 'updated_at': statement.excluded.updated_at},
    ))
    db.commit()
    return {'connector': connector, 'settings': settings, 'execution_enabled': False}

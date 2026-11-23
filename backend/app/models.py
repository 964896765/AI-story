from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Text, ForeignKey, DateTime, Integer, BigInteger, JSON, UniqueConstraint, CheckConstraint, Float, Boolean, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def uid():
    return str(uuid4())

def now():
    return datetime.now(timezone.utc)

class Project(Base):
    __tablename__ = 'projects'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default='')
    budget_cents: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint('budget_cents >= 0'),)

class ProductionSpec(Base):
    __tablename__ = 'production_specs'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id', ondelete='CASCADE'))
    number: Mapped[int] = mapped_column(Integer)
    settings: Mapped[dict] = mapped_column(JSONB)
    sha256: Mapped[str] = mapped_column(String(64))
    request_key: Mapped[str] = mapped_column(String(100))
    restored_from_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('project_id', 'number'), UniqueConstraint('project_id', 'request_key'))

class Asset(Base):
    __tablename__ = 'assets'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    name: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(300), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    authorization: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    media_info: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class LibraryWork(Base):
    __tablename__ = 'library_works'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'),index=True)
    title: Mapped[str] = mapped_column(String(200))
    origin: Mapped[str] = mapped_column(Text)
    tags: Mapped[list] = mapped_column(JSONB)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__ = (UniqueConstraint('project_id','request_key'),Index('ix_library_works_tags','tags',postgresql_using='gin'))

class LibraryEpisode(Base):
    __tablename__ = 'library_episodes'
    work_id: Mapped[str] = mapped_column(ForeignKey('library_works.id',ondelete='CASCADE'),primary_key=True)
    number: Mapped[int] = mapped_column(Integer,primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    asset_id: Mapped[str] = mapped_column(ForeignKey('assets.id'),index=True)

class AssetRight(Base):
    __tablename__ = 'asset_rights'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    asset_id: Mapped[str] = mapped_column(ForeignKey('assets.id'),index=True)
    revision: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    source_type: Mapped[str] = mapped_column(String(20))
    holder: Mapped[str] = mapped_column(String(300))
    scope: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[str] = mapped_column(Text)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__ = (UniqueConstraint('asset_id','revision'),UniqueConstraint('asset_id','request_key'))

class Task(Base):
    __tablename__ = 'tasks'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey('assets.id'),nullable=True)
    kind: Mapped[str] = mapped_column(String(40), default='probe')
    batch_id: Mapped[str | None] = mapped_column(ForeignKey('batches.id', ondelete='SET NULL'), nullable=True, index=True)
    story_version_id: Mapped[str | None] = mapped_column(ForeignKey('story_versions.id'),nullable=True,index=True)
    dependency_task_id: Mapped[str | None] = mapped_column(ForeignKey('tasks.id'),nullable=True,index=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, server_default=text('now()'))
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, server_default='3')
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stage: Mapped[str] = mapped_column(String(40), default='queued', server_default='queued')
    progress: Mapped[float] = mapped_column(Float, default=0, server_default='0')
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false')
    worker_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    elapsed_seconds: Mapped[float] = mapped_column(Float, default=0, server_default='0')
    input_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, server_default='{}')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    __table_args__ = (UniqueConstraint('project_id', 'idempotency_key'), CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled')", name='ck_task_status'), CheckConstraint('progress >= 0 AND progress <= 100', name='ck_task_progress'))

Index('ix_tasks_project_recent',Task.project_id,Task.created_at.desc(),Task.id)
Index('ix_tasks_dispatch_ready',Task.status,Task.next_run_at,Task.created_at,Task.id)

class DirectorPlan(Base):
    __tablename__ = 'director_plans'
    production_spec_version_id: Mapped[str | None] = mapped_column(
        ForeignKey('production_specs.id', name='fk_director_plans_production_spec'))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    request_key: Mapped[str] = mapped_column(String(64))
    instruction: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(20))
    parameters: Mapped[dict] = mapped_column(JSON)
    input_hash: Mapped[str] = mapped_column(String(64))
    task_id: Mapped[str | None] = mapped_column(ForeignKey('tasks.id'), unique=True)
    run_id: Mapped[str | None] = mapped_column(ForeignKey('production_runs.id', name='fk_director_plans_run'))
    preview: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint('project_id','request_key'), UniqueConstraint('run_id',name='uq_director_plans_run'))

class ProductionRun(Base):
    __tablename__ = 'production_runs'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'),index=True)
    plan_version_id: Mapped[str] = mapped_column(ForeignKey('story_versions.id'))
    previous_run_id: Mapped[str | None] = mapped_column(ForeignKey('production_runs.id'),nullable=True)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    policy: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__ = (UniqueConstraint('project_id','request_key'),)

class ProductionEpisode(Base):
    __tablename__ = 'production_episodes'
    run_id: Mapped[str] = mapped_column(ForeignKey('production_runs.id',ondelete='CASCADE'),primary_key=True)
    number: Mapped[int] = mapped_column(Integer,primary_key=True)
    timeline_version_id: Mapped[str] = mapped_column(ForeignKey('story_versions.id'))
    render_task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'),index=True)
    qc_task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'),index=True)
    reused: Mapped[bool] = mapped_column(Boolean,default=False)

class QualityReview(Base):
    __tablename__ = 'quality_reviews'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    qc_task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'),index=True)
    request_key: Mapped[str] = mapped_column(String(64))
    reviewed_sha256: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__ = (UniqueConstraint('qc_task_id','request_key'),)

class ChannelProfile(Base):
    __tablename__ = 'channel_profiles'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'),index=True)
    label: Mapped[str] = mapped_column(String(180))
    platform: Mapped[str] = mapped_column(String(40))
    region: Mapped[str] = mapped_column(String(5))
    revision: Mapped[int] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSON)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__ = (UniqueConstraint('project_id','request_key'),UniqueConstraint('project_id','platform','revision'))

class Publication(Base):
    __tablename__ = 'publications'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'),index=True)
    channel_id: Mapped[str] = mapped_column(ForeignKey('channel_profiles.id'))
    delivery_task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'))
    title: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(30),default='draft')
    planned_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__ = (UniqueConstraint('project_id','request_key'),)

class PublicationEvent(Base):
    __tablename__ = 'publication_events'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    publication_id: Mapped[str] = mapped_column(ForeignKey('publications.id',ondelete='CASCADE'),index=True)
    from_status: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30))
    evidence: Mapped[str] = mapped_column(Text)
    request_key: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__ = (UniqueConstraint('publication_id','request_key'),)

class SettlementEntry(Base):
    __tablename__ = 'settlement_entries'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    channel_id: Mapped[str] = mapped_column(ForeignKey('channel_profiles.id'),index=True)
    account_scope: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(150))
    currency: Mapped[str] = mapped_column(String(3))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    amount_micros: Mapped[int | None] = mapped_column(BigInteger,nullable=True)
    details: Mapped[dict] = mapped_column(JSON)
    source_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__ = (UniqueConstraint('account_scope','external_id'),)

class TaskEvent(Base):
    __tablename__ = 'task_events'
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class CostEntry(Base):
    __tablename__ = 'cost_entries'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'))
    provider: Mapped[str] = mapped_column(String(100))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3), default='CNY')
    reference: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (CheckConstraint('amount_cents >= 0'),)

class Batch(Base):
    __tablename__ = 'batches'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id',ondelete='CASCADE'),index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100))
    request: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__ = (UniqueConstraint('project_id','idempotency_key'),)

class QueueControl(Base):
    __tablename__ = 'queue_control'
    id: Mapped[str] = mapped_column(String(20),primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean,default=False,server_default='false')
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now,onupdate=now,server_default=text('now()'))

class WorkerNode(Base):
    __tablename__ = 'worker_nodes'
    id: Mapped[str] = mapped_column(String(36),primary_key=True)
    pid: Mapped[int] = mapped_column(Integer)
    hostname: Mapped[str] = mapped_column(String(255))
    state: Mapped[str] = mapped_column(String(20))
    task_id: Mapped[str | None] = mapped_column(String(36),nullable=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now,index=True)
    error: Mapped[str | None] = mapped_column(Text,nullable=True)

class TaskAttempt(Base):
    __tablename__ = 'task_attempts'
    id: Mapped[int] = mapped_column(Integer,primary_key=True,autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id',ondelete='CASCADE'),index=True)
    number: Mapped[int] = mapped_column(Integer)
    worker_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(20))
    stage: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True),nullable=True)
    elapsed_seconds: Mapped[float] = mapped_column(Float,default=0)
    parameters: Mapped[dict] = mapped_column(JSON,default=dict)
    inputs: Mapped[dict] = mapped_column(JSON,default=dict)
    output: Mapped[dict] = mapped_column(JSON,default=dict)
    checkpoints: Mapped[list] = mapped_column(JSON,default=list)
    error: Mapped[str | None] = mapped_column(Text,nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40),nullable=True)
    __table_args__ = (UniqueConstraint('task_id','number'),)

class StoryEntity(Base):
    __tablename__='story_entities'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id',ondelete='CASCADE'),index=True)
    kind: Mapped[str] = mapped_column(String(30))
    current_version: Mapped[int] = mapped_column(Integer,default=1)
    creation_key: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(UniqueConstraint('project_id','creation_key'),CheckConstraint("kind IN ('novel','script','character','scene','relationship','episode','storyboard','generation_plan','story_bible','timeline')",name='ck_story_kind'),)

class StoryVersion(Base):
    __tablename__='story_versions'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    entity_id: Mapped[str] = mapped_column(ForeignKey('story_entities.id',ondelete='CASCADE'),index=True)
    number: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    note: Mapped[str] = mapped_column(Text,default='')
    provenance: Mapped[dict] = mapped_column(JSON,default=dict)
    request_key: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(UniqueConstraint('entity_id','number'),UniqueConstraint('entity_id','request_key'),)

class StoryReference(Base):
    __tablename__='story_references'
    id: Mapped[int] = mapped_column(Integer,primary_key=True,autoincrement=True)
    from_version_id: Mapped[str] = mapped_column(ForeignKey('story_versions.id',ondelete='CASCADE'),index=True)
    target_version_id: Mapped[str | None] = mapped_column(ForeignKey('story_versions.id',ondelete='CASCADE'),nullable=True)
    asset_id: Mapped[str | None] = mapped_column(ForeignKey('assets.id'),nullable=True)
    role: Mapped[str] = mapped_column(String(40))
    __table_args__=(CheckConstraint('(target_version_id IS NOT NULL AND asset_id IS NULL) OR (target_version_id IS NULL AND asset_id IS NOT NULL)',name='ck_story_reference_target'),)

class StoryOperation(Base):
    __tablename__='story_operations'
    id: Mapped[str] = mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id',ondelete='CASCADE'),index=True)
    request_key: Mapped[str] = mapped_column(String(100))
    request: Mapped[dict] = mapped_column(JSON)
    result_version_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(UniqueConstraint('project_id','request_key'),)

class TextProvider(Base):
    __tablename__='text_providers'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    label: Mapped[str]=mapped_column(String(120))
    kind: Mapped[str]=mapped_column(String(30))
    enabled: Mapped[bool]=mapped_column(Boolean,default=False)
    settings: Mapped[dict]=mapped_column(JSON)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class ModelConnectionDraft(Base):
    __tablename__ = 'model_connection_drafts'
    connector: Mapped[str] = mapped_column(String(40), primary_key=True)
    settings: Mapped[dict] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class ModelBudget(Base):
    __tablename__='model_budgets'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id',ondelete='CASCADE'),index=True)
    mode: Mapped[str]=mapped_column(String(10))
    currency: Mapped[str]=mapped_column(String(3))
    limit_micros: Mapped[int]=mapped_column(BigInteger,default=0)
    reserved_micros: Mapped[int]=mapped_column(BigInteger,default=0)
    spent_micros: Mapped[int]=mapped_column(BigInteger,default=0)
    halted: Mapped[bool]=mapped_column(Boolean,default=False)
    authorization_id: Mapped[str]=mapped_column(String(200),default='')
    __table_args__=(UniqueConstraint('project_id','mode','currency'),CheckConstraint("mode IN ('mock','live')",name='ck_budget_mode'),CheckConstraint('limit_micros >= 0 AND reserved_micros >= 0 AND spent_micros >= 0',name='ck_budget_nonnegative'))

class ModelCall(Base):
    __tablename__='model_calls'
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
    project_id: Mapped[str]=mapped_column(ForeignKey('projects.id'),index=True)
    task_id: Mapped[str]=mapped_column(ForeignKey('tasks.id'),unique=True)
    provider_id: Mapped[str]=mapped_column(ForeignKey('text_providers.id'))
    budget_id: Mapped[str]=mapped_column(ForeignKey('model_budgets.id'))
    source_version_id: Mapped[str]=mapped_column(ForeignKey('story_versions.id'))
    accepted_version_id: Mapped[str | None]=mapped_column(ForeignKey('story_versions.id'),nullable=True)
    request_key: Mapped[str]=mapped_column(String(100))
    request_hash: Mapped[str]=mapped_column(String(64))
    request: Mapped[dict]=mapped_column(JSON)
    provider_snapshot: Mapped[dict]=mapped_column(JSON)
    prompt_version: Mapped[str]=mapped_column(String(50))
    prompt: Mapped[str]=mapped_column(Text)
    simulated: Mapped[bool]=mapped_column(Boolean)
    status: Mapped[str]=mapped_column(String(30),default='queued',index=True)
    budget_status: Mapped[str]=mapped_column(String(30),default='reserved')
    reserved_micros: Mapped[int]=mapped_column(BigInteger)
    calculated_cost_micros: Mapped[int | None]=mapped_column(BigInteger,nullable=True)
    actual_cost_micros: Mapped[int | None]=mapped_column(BigInteger,nullable=True)
    usage: Mapped[dict | None]=mapped_column(JSON,nullable=True)
    receipt: Mapped[dict | None]=mapped_column(JSON,nullable=True)
    draft: Mapped[dict | None]=mapped_column(JSON,nullable=True)
    draft_revision: Mapped[int]=mapped_column(Integer,default=0)
    review: Mapped[dict | None]=mapped_column(JSON,nullable=True)
    provider_call_id: Mapped[str | None]=mapped_column(String(200),nullable=True)
    error_code: Mapped[str | None]=mapped_column(String(60),nullable=True)
    sent_at: Mapped[datetime | None]=mapped_column(DateTime(timezone=True),nullable=True)
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(UniqueConstraint('project_id','request_key'),CheckConstraint('reserved_micros >= 0',name='ck_call_reserve_nonnegative'))

class ModelLedger(Base):
    __tablename__='model_ledger'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    budget_id: Mapped[str]=mapped_column(ForeignKey('model_budgets.id'),index=True)
    call_id: Mapped[str | None]=mapped_column(ForeignKey('model_calls.id'),nullable=True,index=True)
    kind: Mapped[str]=mapped_column(String(30))
    amount_micros: Mapped[int]=mapped_column(BigInteger)
    reference: Mapped[str]=mapped_column(String(200),unique=True)
    note: Mapped[str]=mapped_column(Text,default='')
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class ModelDraft(Base):
    __tablename__='model_drafts'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True)
    call_id: Mapped[str]=mapped_column(ForeignKey('model_calls.id'),index=True)
    number: Mapped[int]=mapped_column(Integer)
    payload: Mapped[dict]=mapped_column(JSON)
    origin: Mapped[str]=mapped_column(String(20))
    request_key: Mapped[str]=mapped_column(String(100))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
    __table_args__=(UniqueConstraint('call_id','number'),UniqueConstraint('call_id','request_key'))


class MediaAnalysis(Base):
    __tablename__ = 'media_analyses'
    task_id: Mapped[str] = mapped_column(ForeignKey('tasks.id'), primary_key=True)
    signature: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AnalysisRevision(Base):
    __tablename__ = 'analysis_revisions'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    asset_id: Mapped[str] = mapped_column(ForeignKey('assets.id'), index=True)
    number: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(100))
    input_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    __table_args__ = (UniqueConstraint('asset_id', 'number'), UniqueConstraint('asset_id', 'request_key'))

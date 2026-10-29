from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import String, Text, ForeignKey, DateTime, Integer, BigInteger, JSON, UniqueConstraint, CheckConstraint, Float, Boolean, text
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

class Task(Base):
    __tablename__ = 'tasks'
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey('projects.id'), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey('assets.id'))
    kind: Mapped[str] = mapped_column(String(40), default='probe')
    batch_id: Mapped[str | None] = mapped_column(ForeignKey('batches.id', ondelete='SET NULL'), nullable=True, index=True)
    story_version_id: Mapped[str | None] = mapped_column(ForeignKey('story_versions.id'),nullable=True,index=True)
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
    __table_args__=(UniqueConstraint('project_id','creation_key'),CheckConstraint("kind IN ('novel','script','character','scene','relationship','episode','storyboard','generation_plan')",name='ck_story_kind'),)

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

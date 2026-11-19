"""Persist manual distribution, channel rule versions and settlement records."""
from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = depends_on = None


def upgrade():
    op.create_table('channel_profiles',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('label',sa.String(180),nullable=False),
        sa.Column('platform',sa.String(40),nullable=False),sa.Column('region',sa.String(5),nullable=False),
        sa.Column('revision',sa.Integer,nullable=False),sa.Column('details',sa.JSON,nullable=False),
        sa.Column('request_key',sa.String(64),nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('project_id','request_key'),sa.UniqueConstraint('project_id','platform','revision'))
    op.create_index('ix_channel_profiles_project_id','channel_profiles',['project_id'])
    op.create_table('publications',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('channel_id',sa.String(36),sa.ForeignKey('channel_profiles.id'),nullable=False),
        sa.Column('delivery_task_id',sa.String(36),sa.ForeignKey('tasks.id'),nullable=False),
        sa.Column('title',sa.String(180),nullable=False),sa.Column('status',sa.String(30),nullable=False),
        sa.Column('planned_for',sa.DateTime(timezone=True)),
        sa.Column('request_key',sa.String(64),nullable=False),sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('project_id','request_key'))
    op.create_index('ix_publications_project_id','publications',['project_id'])
    op.create_table('publication_events',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('publication_id',sa.String(36),sa.ForeignKey('publications.id',ondelete='CASCADE'),nullable=False),
        sa.Column('from_status',sa.String(30),nullable=False),sa.Column('status',sa.String(30),nullable=False),
        sa.Column('evidence',sa.Text,nullable=False),sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.UniqueConstraint('publication_id','request_key'))
    op.create_index('ix_publication_events_publication_id','publication_events',['publication_id'])
    op.create_table('settlement_entries',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('channel_id',sa.String(36),sa.ForeignKey('channel_profiles.id'),nullable=False),
        sa.Column('account_scope',sa.String(64),nullable=False),
        sa.Column('external_id',sa.String(150),nullable=False),sa.Column('currency',sa.String(3),nullable=False),
        sa.Column('kind',sa.String(20),nullable=False),sa.Column('status',sa.String(20),nullable=False),
        sa.Column('amount_micros',sa.BigInteger),sa.Column('details',sa.JSON,nullable=False),
        sa.Column('source_hash',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('account_scope','external_id'))
    op.create_index('ix_settlement_entries_channel_id','settlement_entries',['channel_id'])


def downgrade():
    db=op.get_bind()
    if (db.execute(sa.text('SELECT 1 FROM channel_profiles LIMIT 1')).first()
        or db.execute(sa.text("SELECT 1 FROM tasks WHERE kind='promotion' LIMIT 1")).first()):
        raise RuntimeError('P13 channel or promotion history exists; restore in a separate database')
    for table in ('settlement_entries','publication_events','publications','channel_profiles'):
        op.drop_table(table)

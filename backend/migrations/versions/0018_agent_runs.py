"""Persist approved, fixed-input Agent workflows."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'agent_runs',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('production_spec_version_id',sa.String(36),sa.ForeignKey('production_specs.id'),nullable=False),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request',JSONB(),nullable=False),
        sa.Column('inputs',JSONB(),nullable=False),
        sa.Column('input_sha256',sa.String(64),nullable=False),
        sa.Column('task_ids',JSONB(),nullable=False),
        sa.Column('approval',JSONB(),nullable=True),
        sa.Column('review',JSONB(),nullable=True),
        sa.Column('cancelled_at',sa.DateTime(timezone=True),nullable=True),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('project_id','request_key'),
    )


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT EXISTS (SELECT 1 FROM agent_runs)')):
        raise RuntimeError('Agent runs exist. Restore the pre-upgrade snapshot in a separate database.')
    op.drop_table('agent_runs')

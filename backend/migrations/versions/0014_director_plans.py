"""Persist approved local director actions and their task links."""
from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'director_plans',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id'), nullable=False),
        sa.Column('request_key', sa.String(64), nullable=False),
        sa.Column('instruction', sa.Text(), nullable=False),
        sa.Column('action', sa.String(20), nullable=False),
        sa.Column('parameters', sa.JSON(), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('task_id', sa.String(36), sa.ForeignKey('tasks.id'), unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('approved_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('project_id', 'request_key'),
    )
    op.create_index('ix_director_plans_project_id', 'director_plans', ['project_id'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT EXISTS (SELECT 1 FROM director_plans)')):
        raise RuntimeError('Export director plans before removing the table')
    op.drop_index('ix_director_plans_project_id', table_name='director_plans')
    op.drop_table('director_plans')

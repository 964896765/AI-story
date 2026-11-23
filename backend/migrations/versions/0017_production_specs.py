"""Persist immutable project production specifications."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'production_specs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('project_id', sa.String(36), sa.ForeignKey('projects.id', ondelete='CASCADE'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('settings', JSONB(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('request_key', sa.String(100), nullable=False),
        sa.Column('restored_from_id', sa.String(36), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('project_id', 'number'),
        sa.UniqueConstraint('project_id', 'request_key'),
    )
    op.add_column('director_plans', sa.Column('production_spec_version_id', sa.String(36), nullable=True))
    op.create_foreign_key('fk_director_plans_production_spec','director_plans','production_specs',
                          ['production_spec_version_id'],['id'])


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT EXISTS (SELECT 1 FROM production_specs)')):
        raise RuntimeError('Production specifications exist. Restore a pre-upgrade backup in a separate database.')
    op.drop_constraint('fk_director_plans_production_spec','director_plans',type_='foreignkey')
    op.drop_column('director_plans','production_spec_version_id')
    op.drop_table('production_specs')

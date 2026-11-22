"""Persist reviewed director batch layouts and production run links."""
from alembic import op
import sqlalchemy as sa

revision = '0015'
down_revision = '0014'
branch_labels = depends_on = None


def upgrade():
    op.add_column('director_plans', sa.Column('run_id', sa.String(36)))
    op.add_column('director_plans', sa.Column('preview', sa.JSON()))
    op.create_foreign_key('fk_director_plans_run', 'director_plans', 'production_runs', ['run_id'], ['id'])
    op.create_unique_constraint('uq_director_plans_run', 'director_plans', ['run_id'])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM director_plans WHERE action = 'batch')")):
        raise RuntimeError('Export director batch plans before downgrading')
    op.drop_constraint('uq_director_plans_run', 'director_plans', type_='unique')
    op.drop_constraint('fk_director_plans_run', 'director_plans', type_='foreignkey')
    op.drop_column('director_plans', 'preview')
    op.drop_column('director_plans', 'run_id')

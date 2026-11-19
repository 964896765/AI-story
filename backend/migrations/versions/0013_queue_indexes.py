"""Index project histories and queued task readiness."""
from alembic import op
import sqlalchemy as sa

revision = '0013'
down_revision = '0012'
branch_labels = depends_on = None


def upgrade():
    op.create_index('ix_tasks_project_recent','tasks',['project_id',sa.text('created_at DESC'),'id'])
    op.create_index('ix_tasks_dispatch_ready','tasks',['status','next_run_at','created_at','id'])


def downgrade():
    op.drop_index('ix_tasks_dispatch_ready',table_name='tasks')
    op.drop_index('ix_tasks_project_recent',table_name='tasks')

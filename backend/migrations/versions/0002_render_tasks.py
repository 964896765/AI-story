"""Video processing lifecycle. No changes to existing assets or task results."""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

def upgrade():
    op.drop_constraint('tasks_status_check', 'tasks', type_='check')
    op.create_check_constraint('ck_task_status', 'tasks', "status IN ('queued','running','succeeded','failed','cancelled')")
    for column in [
        sa.Column('stage', sa.String(40), nullable=False, server_default='queued'),
        sa.Column('progress', sa.Float(), nullable=False, server_default='0'),
        sa.Column('cancel_requested', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('worker_token', sa.String(36)),
        sa.Column('started_at', sa.DateTime(timezone=True)),
        sa.Column('finished_at', sa.DateTime(timezone=True)),
        sa.Column('elapsed_seconds', sa.Float(), nullable=False, server_default='0'),
        sa.Column('input_snapshot', sa.JSON(), nullable=False, server_default='{}'),
    ]:
        op.add_column('tasks', column)
    op.create_check_constraint('ck_task_progress', 'tasks', 'progress >= 0 AND progress <= 100')
    op.execute("UPDATE tasks SET stage = status, progress = CASE WHEN status='succeeded' THEN 100 ELSE 0 END")

def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM tasks WHERE kind='render'")).scalar():
        raise RuntimeError('P2 render records exist; refusing unsafe P1 downgrade. Restore an upgrade-time backup into a separate database instead.')
    op.execute("UPDATE tasks SET status='failed', error='Cancelled in P2; downgraded to P1' WHERE status='cancelled'")
    op.drop_constraint('ck_task_progress', 'tasks', type_='check')
    for name in ['input_snapshot','elapsed_seconds','finished_at','started_at','worker_token','cancel_requested','progress','stage']:
        op.drop_column('tasks', name)
    op.drop_constraint('ck_task_status', 'tasks', type_='check')
    op.create_check_constraint('tasks_status_check', 'tasks', "status IN ('queued','running','succeeded','failed')")

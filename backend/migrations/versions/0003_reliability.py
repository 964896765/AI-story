"""P3 persistent batches, queue control, worker health and attempts."""
from alembic import op
import sqlalchemy as sa
revision="0003"
down_revision="0002"
branch_labels=None
depends_on=None

def upgrade():
    op.execute('\nCREATE TABLE batches (\n\tid VARCHAR(36) NOT NULL, \n\tproject_id VARCHAR(36) NOT NULL, \n\tidempotency_key VARCHAR(100) NOT NULL, \n\trequest JSON NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (project_id, idempotency_key), \n\tFOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE\n)\n\n')
    op.execute('CREATE INDEX ix_batches_project_id ON batches (project_id)')
    op.execute("\nCREATE TABLE queue_control (\n\tid VARCHAR(20) NOT NULL, \n\tpaused BOOLEAN DEFAULT 'false' NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE DEFAULT 'now()' NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n")
    op.execute('\nCREATE TABLE worker_nodes (\n\tid VARCHAR(36) NOT NULL, \n\tpid INTEGER NOT NULL, \n\thostname VARCHAR(255) NOT NULL, \n\tstate VARCHAR(20) NOT NULL, \n\ttask_id VARCHAR(36), \n\tlast_seen TIMESTAMP WITH TIME ZONE NOT NULL, \n\terror TEXT, \n\tPRIMARY KEY (id)\n)\n\n')
    op.execute('CREATE INDEX ix_worker_nodes_last_seen ON worker_nodes (last_seen)')
    op.execute("INSERT INTO queue_control (id,paused) VALUES ('local',false)")
    op.add_column('tasks',sa.Column('batch_id',sa.String(36),nullable=True))
    op.create_foreign_key('fk_task_batch','tasks','batches',['batch_id'],['id'],ondelete='SET NULL')
    op.create_index('ix_tasks_batch_id','tasks',['batch_id'])
    op.add_column('tasks',sa.Column('error_code',sa.String(40),nullable=True))
    op.add_column('tasks',sa.Column('next_run_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.text('now()')))
    op.add_column('tasks',sa.Column('max_attempts',sa.Integer(),nullable=False,server_default='3'))
    op.execute('\nCREATE TABLE task_attempts (\n\tid SERIAL NOT NULL, \n\ttask_id VARCHAR(36) NOT NULL, \n\tnumber INTEGER NOT NULL, \n\tworker_id VARCHAR(36) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tstage VARCHAR(40) NOT NULL, \n\tstarted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tfinished_at TIMESTAMP WITH TIME ZONE, \n\telapsed_seconds FLOAT NOT NULL, \n\tparameters JSON NOT NULL, \n\tinputs JSON NOT NULL, \n\toutput JSON NOT NULL, \n\tcheckpoints JSON NOT NULL, \n\terror TEXT, \n\terror_code VARCHAR(40), \n\tPRIMARY KEY (id), \n\tUNIQUE (task_id, number), \n\tFOREIGN KEY(task_id) REFERENCES tasks (id) ON DELETE CASCADE\n)\n\n')
    op.execute('CREATE INDEX ix_task_attempts_task_id ON task_attempts (task_id)')

def downgrade():
    if op.get_bind().execute(sa.text("SELECT count(*) FROM tasks WHERE status IN ('queued','running')")).scalar():
        raise RuntimeError('Active tasks exist; stop workers and settle queue before downgrade')
    if op.get_bind().execute(sa.text('SELECT count(*) FROM task_attempts')).scalar() or op.get_bind().execute(sa.text('SELECT count(*) FROM batches')).scalar():
        raise RuntimeError('P3 audit records exist; restore a separate upgrade-time backup instead of dropping history')
    op.drop_table('task_attempts')
    op.drop_index('ix_tasks_batch_id',table_name='tasks')
    op.drop_constraint('fk_task_batch','tasks',type_='foreignkey')
    for name in ['batch_id','error_code','next_run_at','max_attempts']:op.drop_column('tasks',name)
    for name in ['worker_nodes','queue_control','batches']:op.drop_table(name)

"""Initial PostgreSQL production foundation. Frozen DDL, not runtime metadata."""
from alembic import op
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.execute('CREATE TABLE projects (\n\tid VARCHAR(36) NOT NULL, \n\tname VARCHAR(200) NOT NULL, \n\tdescription TEXT NOT NULL, \n\tbudget_cents BIGINT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCHECK (budget_cents >= 0)\n)')
    op.execute('CREATE TABLE assets (\n\tid VARCHAR(36) NOT NULL, \n\tproject_id VARCHAR(36) NOT NULL, \n\tname VARCHAR(255) NOT NULL, \n\tstorage_key VARCHAR(300) NOT NULL, \n\tsha256 VARCHAR(64) NOT NULL, \n\tsize_bytes BIGINT NOT NULL, \n\t"authorization" TEXT NOT NULL, \n\tversion INTEGER NOT NULL, \n\tmedia_info JSON NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tUNIQUE (storage_key)\n)')
    op.execute('CREATE INDEX ix_assets_project_id ON assets (project_id)')
    op.execute('CREATE INDEX ix_assets_sha256 ON assets (sha256)')
    op.execute("CREATE TABLE tasks (\n\tid VARCHAR(36) NOT NULL, \n\tproject_id VARCHAR(36) NOT NULL, \n\tasset_id VARCHAR(36) NOT NULL, \n\tkind VARCHAR(40) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tidempotency_key VARCHAR(100) NOT NULL, \n\tparameters JSON NOT NULL, \n\toutput JSON NOT NULL, \n\tattempt INTEGER NOT NULL, \n\terror TEXT, \n\tlease_until TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tupdated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (project_id, idempotency_key), \n\tCHECK (status IN ('queued','running','succeeded','failed')), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(asset_id) REFERENCES assets (id)\n)")
    op.execute('CREATE INDEX ix_tasks_status ON tasks (status)')
    op.execute('CREATE INDEX ix_tasks_project_id ON tasks (project_id)')
    op.execute('CREATE TABLE cost_entries (\n\tid VARCHAR(36) NOT NULL, \n\tproject_id VARCHAR(36) NOT NULL, \n\ttask_id VARCHAR(36) NOT NULL, \n\tprovider VARCHAR(100) NOT NULL, \n\tamount_cents BIGINT NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\treference VARCHAR(200) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tCHECK (amount_cents >= 0), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tFOREIGN KEY(task_id) REFERENCES tasks (id), \n\tUNIQUE (reference)\n)')
    op.execute('CREATE INDEX ix_cost_entries_project_id ON cost_entries (project_id)')
    op.execute('CREATE TABLE task_events (\n\tid SERIAL NOT NULL, \n\ttask_id VARCHAR(36) NOT NULL, \n\tattempt INTEGER NOT NULL, \n\tmessage TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(task_id) REFERENCES tasks (id)\n)')
    op.execute('CREATE INDEX ix_task_events_task_id ON task_events (task_id)')

def downgrade():
    op.drop_table('task_events')
    op.drop_table('cost_entries')
    op.drop_table('tasks')
    op.drop_table('assets')
    op.drop_table('projects')

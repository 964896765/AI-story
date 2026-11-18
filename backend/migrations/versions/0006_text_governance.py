"""P5-A/B governed text calls, micro-unit budgets and human-reviewed drafts."""
from alembic import op
import sqlalchemy as sa
revision="0006"
down_revision="0005"
branch_labels=None
depends_on=None

def upgrade():
    op.alter_column("tasks","asset_id",existing_type=sa.String(36),nullable=True)
    op.execute('\nCREATE TABLE text_providers (\n\tid VARCHAR(36) NOT NULL, \n\tlabel VARCHAR(120) NOT NULL, \n\tkind VARCHAR(30) NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tsettings JSON NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n')
    op.execute("\nCREATE TABLE model_budgets (\n\tid VARCHAR(36) NOT NULL, \n\tproject_id VARCHAR(36) NOT NULL, \n\tmode VARCHAR(10) NOT NULL, \n\tcurrency VARCHAR(3) NOT NULL, \n\tlimit_micros BIGINT NOT NULL, \n\treserved_micros BIGINT NOT NULL, \n\tspent_micros BIGINT NOT NULL, \n\thalted BOOLEAN NOT NULL, \n\tauthorization_id VARCHAR(200) NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (project_id, mode, currency), \n\tCONSTRAINT ck_budget_mode CHECK (mode IN ('mock','live')), \n\tCONSTRAINT ck_budget_nonnegative CHECK (limit_micros >= 0 AND reserved_micros >= 0 AND spent_micros >= 0), \n\tFOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE\n)\n\n")
    op.execute('CREATE INDEX ix_model_budgets_project_id ON model_budgets (project_id)')
    op.execute('\nCREATE TABLE model_calls (\n\tid VARCHAR(36) NOT NULL, \n\tproject_id VARCHAR(36) NOT NULL, \n\ttask_id VARCHAR(36) NOT NULL, \n\tprovider_id VARCHAR(36) NOT NULL, \n\tbudget_id VARCHAR(36) NOT NULL, \n\tsource_version_id VARCHAR(36) NOT NULL, \n\taccepted_version_id VARCHAR(36), \n\trequest_key VARCHAR(100) NOT NULL, \n\trequest_hash VARCHAR(64) NOT NULL, \n\trequest JSON NOT NULL, \n\tprovider_snapshot JSON NOT NULL, \n\tprompt_version VARCHAR(50) NOT NULL, \n\tprompt TEXT NOT NULL, \n\tsimulated BOOLEAN NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tbudget_status VARCHAR(30) NOT NULL, \n\treserved_micros BIGINT NOT NULL, \n\tcalculated_cost_micros BIGINT, \n\tactual_cost_micros BIGINT, \n\tusage JSON, \n\treceipt JSON, \n\tdraft JSON, \n\tdraft_revision INTEGER NOT NULL, \n\treview JSON, \n\tprovider_call_id VARCHAR(200), \n\terror_code VARCHAR(60), \n\tsent_at TIMESTAMP WITH TIME ZONE, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (project_id, request_key), \n\tCONSTRAINT ck_call_reserve_nonnegative CHECK (reserved_micros >= 0), \n\tFOREIGN KEY(project_id) REFERENCES projects (id), \n\tUNIQUE (task_id), \n\tFOREIGN KEY(task_id) REFERENCES tasks (id), \n\tFOREIGN KEY(provider_id) REFERENCES text_providers (id), \n\tFOREIGN KEY(budget_id) REFERENCES model_budgets (id), \n\tFOREIGN KEY(source_version_id) REFERENCES story_versions (id), \n\tFOREIGN KEY(accepted_version_id) REFERENCES story_versions (id)\n)\n\n')
    op.execute('CREATE INDEX ix_model_calls_status ON model_calls (status)')
    op.execute('CREATE INDEX ix_model_calls_project_id ON model_calls (project_id)')
    op.execute('\nCREATE TABLE model_ledger (\n\tid SERIAL NOT NULL, \n\tbudget_id VARCHAR(36) NOT NULL, \n\tcall_id VARCHAR(36), \n\tkind VARCHAR(30) NOT NULL, \n\tamount_micros BIGINT NOT NULL, \n\treference VARCHAR(200) NOT NULL, \n\tnote TEXT NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(budget_id) REFERENCES model_budgets (id), \n\tFOREIGN KEY(call_id) REFERENCES model_calls (id), \n\tUNIQUE (reference)\n)\n\n')
    op.execute('CREATE INDEX ix_model_ledger_call_id ON model_ledger (call_id)')
    op.execute('CREATE INDEX ix_model_ledger_budget_id ON model_ledger (budget_id)')
    op.execute('\nCREATE TABLE model_drafts (\n\tid SERIAL NOT NULL, \n\tcall_id VARCHAR(36) NOT NULL, \n\tnumber INTEGER NOT NULL, \n\tpayload JSON NOT NULL, \n\torigin VARCHAR(20) NOT NULL, \n\trequest_key VARCHAR(100) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (call_id, number), \n\tUNIQUE (call_id, request_key), \n\tFOREIGN KEY(call_id) REFERENCES model_calls (id)\n)\n\n')
    op.execute('CREATE INDEX ix_model_drafts_call_id ON model_drafts (call_id)')

def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM model_calls')).scalar() or op.get_bind().execute(sa.text('SELECT count(*) FROM model_ledger')).scalar():
        raise RuntimeError('P5 financial audit records exist; restore a separate pre-upgrade backup')
    if op.get_bind().execute(sa.text("SELECT count(*) FROM tasks WHERE asset_id IS NULL")).scalar():
        raise RuntimeError('Text tasks exist; refusing incompatible downgrade')
    for name in ['model_drafts','model_ledger','model_calls','model_budgets','text_providers']:op.drop_table(name)
    op.alter_column('tasks','asset_id',existing_type=sa.String(36),nullable=False)

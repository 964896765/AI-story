"""Persist series production graphs and human technical-QC waivers."""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = depends_on = None


def upgrade():
    op.add_column('tasks',sa.Column('dependency_task_id',sa.String(36),sa.ForeignKey('tasks.id')))
    op.create_index('ix_tasks_dependency_task_id','tasks',['dependency_task_id'])
    op.create_table('production_runs',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('plan_version_id',sa.String(36),sa.ForeignKey('story_versions.id'),nullable=False),
        sa.Column('previous_run_id',sa.String(36),sa.ForeignKey('production_runs.id')),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('policy',sa.JSON,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('project_id','request_key'))
    op.create_index('ix_production_runs_project_id','production_runs',['project_id'])
    op.create_table('production_episodes',
        sa.Column('run_id',sa.String(36),sa.ForeignKey('production_runs.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('number',sa.Integer,primary_key=True),
        sa.Column('timeline_version_id',sa.String(36),sa.ForeignKey('story_versions.id'),nullable=False),
        sa.Column('render_task_id',sa.String(36),sa.ForeignKey('tasks.id'),nullable=False),
        sa.Column('qc_task_id',sa.String(36),sa.ForeignKey('tasks.id'),nullable=False),
        sa.Column('reused',sa.Boolean,nullable=False))
    for column in ('render_task_id','qc_task_id'):
        op.create_index('ix_production_episodes_'+column,'production_episodes',[column])
    op.create_table('quality_reviews',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('qc_task_id',sa.String(36),sa.ForeignKey('tasks.id'),nullable=False),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('reviewed_sha256',sa.String(64),nullable=False),
        sa.Column('note',sa.Text,nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('qc_task_id','request_key'))
    op.create_index('ix_quality_reviews_qc_task_id','quality_reviews',['qc_task_id'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT 1 FROM production_runs LIMIT 1')).first():
        raise RuntimeError('P11 production records exist; restore in a separate database')
    op.drop_table('quality_reviews')
    op.drop_table('production_episodes')
    op.drop_table('production_runs')
    op.drop_index('ix_tasks_dependency_task_id',table_name='tasks')
    op.drop_column('tasks','dependency_task_id')

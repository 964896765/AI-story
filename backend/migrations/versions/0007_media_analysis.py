"""Persist verified local multimedia outputs."""
from alembic import op
import sqlalchemy as sa

revision = '0007'
down_revision = '0006'
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        'media_analyses',
        sa.Column('task_id', sa.String(36), sa.ForeignKey('tasks.id'), primary_key=True),
        sa.Column('signature', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_media_analyses_signature', 'media_analyses', ['signature'])
    op.create_table(
        'analysis_revisions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('asset_id', sa.String(36), sa.ForeignKey('assets.id'), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('request_key', sa.String(100), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('asset_id', 'number'),
        sa.UniqueConstraint('asset_id', 'request_key'),
    )
    op.create_index('ix_analysis_revisions_asset_id', 'analysis_revisions', ['asset_id'])


def downgrade():
    if (op.get_bind().execute(sa.text("SELECT 1 FROM tasks WHERE kind = 'analyze' LIMIT 1")).first()
            or op.get_bind().execute(sa.text("SELECT 1 FROM analysis_revisions LIMIT 1")).first()):
        raise RuntimeError('P6 analysis tasks exist; restore in a separate database')
    op.drop_table('analysis_revisions')
    op.drop_table('media_analyses')

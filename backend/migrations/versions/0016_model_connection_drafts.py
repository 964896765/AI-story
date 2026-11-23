"""Persist offline model connection drafts without granting execution."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'model_connection_drafts',
        sa.Column('connector', sa.String(40), primary_key=True),
        sa.Column('settings', postgresql.JSONB(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    if op.get_bind().scalar(sa.text('SELECT EXISTS (SELECT 1 FROM model_connection_drafts)')):
        raise RuntimeError('Model connection drafts exist. Restore the pre-upgrade backup in a separate database.')
    op.drop_table('model_connection_drafts')

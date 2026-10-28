"""Use an evaluated timestamp default for queue state, including existing local DBs."""
from alembic import op
import sqlalchemy as sa

revision='0004'
down_revision='0003'
branch_labels=None
depends_on=None

def upgrade():
    op.alter_column('queue_control','updated_at',server_default=sa.text('now()'))

def downgrade():
    # Avoid reinstating a constant timestamp; ORM writers provide updated_at.
    op.alter_column('queue_control','updated_at',server_default=None)

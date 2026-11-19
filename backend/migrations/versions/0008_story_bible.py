"""Allow story bibles in the existing immutable creative version chain."""
from alembic import op
import sqlalchemy as sa

revision = '0008'
down_revision = '0007'
branch_labels = depends_on = None

OLD_KINDS = "'novel','script','character','scene','relationship','episode','storyboard','generation_plan'"


def set_constraint(kinds):
    op.drop_constraint('ck_story_kind', 'story_entities', type_='check')
    op.create_check_constraint('ck_story_kind', 'story_entities', f'kind IN ({kinds})')


def upgrade():
    set_constraint(OLD_KINDS + ",'story_bible'")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM story_entities WHERE kind='story_bible' LIMIT 1")).first():
        raise RuntimeError('P7 story bibles exist; restore in a separate database')
    set_constraint(OLD_KINDS)

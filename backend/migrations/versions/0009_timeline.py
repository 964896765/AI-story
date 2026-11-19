"""Enable immutable editing timelines using existing creative version records."""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = depends_on = None
OLD_KINDS = "'novel','script','character','scene','relationship','episode','storyboard','generation_plan','story_bible'"


def kinds_constraint(values):
    op.drop_constraint('ck_story_kind','story_entities',type_='check')
    op.create_check_constraint('ck_story_kind','story_entities',f'kind IN ({values})')


def upgrade():
    kinds_constraint(OLD_KINDS + ",'timeline'")


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM story_entities WHERE kind='timeline' LIMIT 1")).first():
        raise RuntimeError('P10 timeline versions exist; restore in a separate database')
    kinds_constraint(OLD_KINDS)

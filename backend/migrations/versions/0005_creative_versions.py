"""P4 immutable creative versions and pinned production references."""
from alembic import op
import sqlalchemy as sa
revision="0005"
down_revision="0004"
branch_labels=None
depends_on=None

def upgrade():
    op.execute("\nCREATE TABLE story_entities (\n\tid VARCHAR(36) NOT NULL, \n\tproject_id VARCHAR(36) NOT NULL, \n\tkind VARCHAR(30) NOT NULL, \n\tcurrent_version INTEGER NOT NULL, \n\tcreation_key VARCHAR(100) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (project_id, creation_key), \n\tCONSTRAINT ck_story_kind CHECK (kind IN ('novel','script','character','scene','relationship','episode','storyboard','generation_plan')), \n\tFOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE\n)\n\n")
    op.execute('CREATE INDEX ix_story_entities_project_id ON story_entities (project_id)')
    op.execute('\nCREATE TABLE story_versions (\n\tid VARCHAR(36) NOT NULL, \n\tentity_id VARCHAR(36) NOT NULL, \n\tnumber INTEGER NOT NULL, \n\ttitle VARCHAR(200) NOT NULL, \n\tcontent JSON NOT NULL, \n\tcontent_hash VARCHAR(64) NOT NULL, \n\tnote TEXT NOT NULL, \n\tprovenance JSON NOT NULL, \n\trequest_key VARCHAR(100) NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (entity_id, number), \n\tUNIQUE (entity_id, request_key), \n\tFOREIGN KEY(entity_id) REFERENCES story_entities (id) ON DELETE CASCADE\n)\n\n')
    op.execute('CREATE INDEX ix_story_versions_entity_id ON story_versions (entity_id)')
    op.execute('\nCREATE TABLE story_references (\n\tid SERIAL NOT NULL, \n\tfrom_version_id VARCHAR(36) NOT NULL, \n\ttarget_version_id VARCHAR(36), \n\tasset_id VARCHAR(36), \n\trole VARCHAR(40) NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT ck_story_reference_target CHECK ((target_version_id IS NOT NULL AND asset_id IS NULL) OR (target_version_id IS NULL AND asset_id IS NOT NULL)), \n\tFOREIGN KEY(from_version_id) REFERENCES story_versions (id) ON DELETE CASCADE, \n\tFOREIGN KEY(target_version_id) REFERENCES story_versions (id) ON DELETE CASCADE, \n\tFOREIGN KEY(asset_id) REFERENCES assets (id)\n)\n\n')
    op.execute('CREATE INDEX ix_story_references_from_version_id ON story_references (from_version_id)')
    op.execute('\nCREATE TABLE story_operations (\n\tid VARCHAR(36) NOT NULL, \n\tproject_id VARCHAR(36) NOT NULL, \n\trequest_key VARCHAR(100) NOT NULL, \n\trequest JSON NOT NULL, \n\tresult_version_ids JSON NOT NULL, \n\tcreated_at TIMESTAMP WITH TIME ZONE NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (project_id, request_key), \n\tFOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE CASCADE\n)\n\n')
    op.execute('CREATE INDEX ix_story_operations_project_id ON story_operations (project_id)')
    op.add_column('tasks',sa.Column('story_version_id',sa.String(36),nullable=True))
    op.create_foreign_key('fk_task_story_version','tasks','story_versions',['story_version_id'],['id'])
    op.create_index('ix_tasks_story_version_id','tasks',['story_version_id'])

def downgrade():
    if op.get_bind().execute(sa.text('SELECT count(*) FROM story_entities')).scalar():
        raise RuntimeError('P4 creative records exist; restore a separate pre-upgrade backup to preserve version history')
    op.drop_index('ix_tasks_story_version_id',table_name='tasks')
    op.drop_constraint('fk_task_story_version','tasks',type_='foreignkey')
    op.drop_column('tasks','story_version_id')
    for name in ['story_references','story_operations','story_versions','story_entities']:op.drop_table(name)

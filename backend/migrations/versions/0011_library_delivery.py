"""Versioned rights and logical library registration for guarded delivery."""
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision = '0011'
down_revision = '0010'
branch_labels = depends_on = None


def upgrade():
    op.create_table('library_works',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('project_id',sa.String(36),sa.ForeignKey('projects.id'),nullable=False),
        sa.Column('title',sa.String(200),nullable=False),
        sa.Column('origin',sa.Text,nullable=False),
        sa.Column('tags',postgresql.JSONB,nullable=False),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('archived_at',sa.DateTime(timezone=True)),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('project_id','request_key'))
    op.create_index('ix_library_works_project_id','library_works',['project_id'])
    op.create_index('ix_library_works_tags','library_works',['tags'],postgresql_using='gin')
    op.create_table('library_episodes',
        sa.Column('work_id',sa.String(36),sa.ForeignKey('library_works.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('number',sa.Integer,primary_key=True),
        sa.Column('title',sa.String(200),nullable=False),
        sa.Column('asset_id',sa.String(36),sa.ForeignKey('assets.id'),nullable=False))
    op.create_index('ix_library_episodes_asset_id','library_episodes',['asset_id'])
    op.create_table('asset_rights',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('asset_id',sa.String(36),sa.ForeignKey('assets.id'),nullable=False),
        sa.Column('revision',sa.Integer,nullable=False),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('source_type',sa.String(20),nullable=False),
        sa.Column('holder',sa.String(300),nullable=False),
        sa.Column('scope',sa.JSON,nullable=False),
        sa.Column('evidence',sa.Text,nullable=False),
        sa.Column('starts_at',sa.DateTime(timezone=True)),
        sa.Column('expires_at',sa.DateTime(timezone=True)),
        sa.Column('request_key',sa.String(64),nullable=False),
        sa.Column('request_hash',sa.String(64),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('asset_id','revision'),sa.UniqueConstraint('asset_id','request_key'))
    op.create_index('ix_asset_rights_asset_id','asset_rights',['asset_id'])


def downgrade():
    connection=op.get_bind()
    for table in ('library_works','asset_rights'):
        if connection.execute(sa.text(f'SELECT 1 FROM {table} LIMIT 1')).first():
            raise RuntimeError('P12 library or rights records exist; restore in a separate database')
    if connection.execute(sa.text("SELECT 1 FROM tasks WHERE kind='delivery' LIMIT 1")).first():
        raise RuntimeError('P12 delivery tasks exist; restore in a separate database')
    for table in ('asset_rights','library_episodes','library_works'):
        op.drop_table(table)

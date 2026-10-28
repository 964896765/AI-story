from alembic import context
from app.db import engine, Base
from app import models
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

def compare_defaults(migration_context, inspected_column, metadata_column, inspected_default, metadata_default, rendered_metadata_default):
    # PostgreSQL JSON has no equality operator; compare trusted schema defaults as JSONB.
    if isinstance(metadata_column.type,sa.JSON):
        if inspected_default is None or rendered_metadata_default is None:
            return inspected_default is not None or rendered_metadata_default is not None
        expected=sa.literal(metadata_default.arg) if isinstance(metadata_default.arg,str) else sa.literal_column(rendered_metadata_default)
        expression=sa.cast(sa.literal_column(inspected_default),JSONB)==sa.cast(expected,JSONB)
        return not migration_context.connection.scalar(sa.select(expression))
    return None

if context.is_offline_mode():
    context.configure(url=str(engine.url), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_server_default=compare_defaults)
        with context.begin_transaction():
            context.run_migrations()

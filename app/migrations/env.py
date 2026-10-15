from alembic import context

from app.config import Settings
from app.database import Database
from app.models import Base, UTCDateTime

config = context.config


def render_item(kind, item, autogen_context):
    if kind == "type" and isinstance(item, UTCDateTime):
        return "sa.DateTime()"
    return False


def run(connection):
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,
        compare_type=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=Settings.from_env().database_url,
        target_metadata=Base.metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    run(config.attributes["connection"])
else:
    database = Database(Settings.from_env().database_url)
    with database.engine.begin() as connection:
        run(connection)
    database.close()

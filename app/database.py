from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import ROOT
from app.models import Base


def migration_config() -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "app" / "migrations"))
    return config


class Database:
    def __init__(self, url: str):
        self.url = url
        self.path = make_url(url).database
        memory = self.path in (None, "", ":memory:")
        self.engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 5},
            **({"poolclass": StaticPool} if memory else {}),
        )

        @event.listens_for(self.engine, "connect")
        def configure_sqlite(connection, _):
            # Gestion explicite des transactions, y compris les DDL des migrations.
            connection.isolation_level = None
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

        @event.listens_for(self.engine, "begin")
        def begin(connection):
            connection.exec_driver_sql("BEGIN")

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def initialize(self):
        if self.path not in (None, "", ":memory:"):
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        config = migration_config()
        with self.engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")

    def check_schema(self):
        with self.engine.connect() as connection:
            revision = MigrationContext.configure(connection).get_current_revision()
            tables = set(inspect(connection).get_table_names())
        expected = ScriptDirectory.from_config(migration_config()).get_current_head()
        if revision != expected or expected is None:
            raise RuntimeError(
                "Base absente ou schéma incompatible. Exécuter : python -m app.cli init-db"
            )
        if not set(Base.metadata.tables).issubset(tables):
            raise RuntimeError(
                "Schéma incomplet : restaurer une sauvegarde valide. "
                "init-db ne répare pas une base endommagée."
            )

    @contextmanager
    def transaction(self):
        """Commit atomique ; toute exception annule l’ensemble des écritures."""
        with self.sessions.begin() as session:
            yield session

    def close(self):
        self.engine.dispose()

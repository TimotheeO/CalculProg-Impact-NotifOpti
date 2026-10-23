from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Database
from app.seeds import seed_demo
from app.web import create_app


@pytest.fixture
def web_settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'impactflow.sqlite3'}", environment="test"
    )


@pytest.fixture
def database(web_settings):
    database = Database(web_settings.database_url)
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def seeded_db(database):
    with database.transaction() as session:
        seed_demo(session)
    return database


@pytest.fixture
def web_client(seeded_db, web_settings):
    with TestClient(create_app(web_settings)) as client:
        yield client


@pytest.fixture
def web_clock():
    """Horloge UTC contrôlée pour les scénarios de notification, sans attente réelle."""
    current = [datetime(2026, 10, 22, 9, tzinfo=timezone.utc)]

    def read():
        return current[0]

    def advance(seconds):
        current[0] += timedelta(seconds=seconds)

    read.advance = advance
    return read

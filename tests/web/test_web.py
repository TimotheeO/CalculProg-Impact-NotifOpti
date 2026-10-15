import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.models import Event, Workshop
from app.seeds import SECOND_EVENT_ID
from app.web import create_app


def test_health_checks_database_without_leaking_configuration(web_client):
    response = web_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert "sqlite" not in response.text


def test_catalog_is_rendered_from_database_and_hides_private_data(web_client):
    response = web_client.get("/")
    assert response.status_code == 200
    assert "La Fabrique du vendredi" in response.text
    for private in (
        "Les Rencontres créatives",
        "Alice Martin",
        "example.test",
        "seed-notification",
    ):
        assert private not in response.text


def test_public_detail_lists_only_its_active_workshops(web_client, seeded_db):
    response = web_client.get("/events/fabrique-du-vendredi")
    assert response.status_code == 200
    assert "Regards sur la ville" in response.text
    assert "30/10/2026 à 14 h 00" in response.text  # Paris repasse à UTC+1.
    assert "Cuisine de saison" not in response.text
    with seeded_db.transaction() as session:
        session.get(Workshop, "fabrique-photo").status = "cancelled"
    assert (
        "Regards sur la ville"
        not in web_client.get("/events/fabrique-du-vendredi").text
    )


@pytest.mark.parametrize("status", ["draft", "cancelled", "archived"])
def test_nonpublic_event_state_is_not_disclosed(web_client, seeded_db, status):
    with seeded_db.transaction() as session:
        session.get(Event, SECOND_EVENT_ID).status = status
    assert "La Fabrique du vendredi" not in web_client.get("/").text
    assert web_client.get("/events/fabrique-du-vendredi").status_code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/events/rencontres-creatives",
        "/events/missing",
        "/admin",
        "/docs",
        "/openapi.json",
    ],
)
def test_absent_or_private_route_returns_a_safe_error(web_client, path):
    response = web_client.get(path)
    assert response.status_code == 404
    assert "Cette page est introuvable" in response.text
    assert "Traceback" not in response.text
    assert "example.test" not in response.text


def test_templates_escape_database_content(web_client, seeded_db):
    with seeded_db.transaction() as session:
        session.get(Event, SECOND_EVENT_ID).name = '<script>alert("xss")</script>'
    response = web_client.get("/")
    assert "<script>alert" not in response.text
    assert "&lt;script&gt;" in response.text
    assert "Content-Security-Policy" in response.headers
    assert "'unsafe-inline'" not in response.headers["Content-Security-Policy"]


def test_security_headers_and_local_assets(web_client):
    response = web_client.get("/")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    for path, mime in [
        ("/static/app.css", "text/css"),
        ("/static/theme.js", "javascript"),
    ]:
        asset = web_client.get(path)
        assert asset.status_code == 200
        assert mime in asset.headers["content-type"]


def test_empty_database_has_a_useful_empty_catalog(database, web_settings):
    with TestClient(create_app(web_settings)) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "Aucun événement ouvert" in response.text


def test_uninitialized_schema_prevents_startup(web_settings):
    with (
        pytest.raises(RuntimeError, match="init-db"),
        TestClient(create_app(web_settings)),
    ):
        pass


def test_incompatible_schema_prevents_startup(database, web_settings):
    from sqlalchemy import text

    with database.engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num='future'"))
    with (
        pytest.raises(RuntimeError, match="schéma incompatible"),
        TestClient(create_app(web_settings)),
    ):
        pass


def test_missing_table_prevents_startup_without_recreating_it(database, web_settings):
    from sqlalchemy import text

    with database.engine.begin() as connection:
        connection.execute(text("DROP TABLE contacts"))
    with (
        pytest.raises(RuntimeError, match="Schéma incomplet"),
        TestClient(create_app(web_settings)),
    ):
        pass


def test_unexpected_error_is_presented_without_internal_details(
    seeded_db, web_settings
):
    application = create_app(web_settings)

    @application.get("/failure-for-test")
    def fail():
        raise RuntimeError("private@example.test and internal details")

    with TestClient(application, raise_server_exceptions=False) as client:
        response = client.get("/failure-for-test")
    assert response.status_code == 500
    assert "Une erreur est survenue" in response.text
    assert "private@example.test" not in response.text
    assert "RuntimeError" not in response.text


@pytest.mark.parametrize("path", ["/health", "/"])
def test_database_failure_returns_503_without_sql_or_personal_data(
    web_client, monkeypatch, path
):
    def unavailable(*args, **kwargs):
        raise OperationalError(
            "SELECT private FROM users",
            {"email": "private@example.test"},
            Exception("secret"),
        )

    monkeypatch.setattr(web_client.app.state.database.engine, "connect", unavailable)
    response = web_client.get(path)
    assert response.status_code == 503
    assert "SELECT" not in response.text and "secret" not in response.text
    assert "private@example.test" not in response.text


def test_no_unauthenticated_mutation_endpoint_is_available(web_client):
    response = web_client.post(
        "/events/fabrique-du-vendredi", json={"name": "Unauthorized"}
    )
    assert response.status_code == 405
    assert "La Fabrique du vendredi" in web_client.get("/").text


@pytest.mark.parametrize(
    "url",
    ["postgresql://localhost/db", "sqlite:///relative.sqlite3", "sqlite:///:memory:"],
)
def test_unsupported_or_nonpersistent_configuration_is_rejected(url):
    with pytest.raises(ValueError):
        Settings(database_url=url)

from dataclasses import replace
from datetime import datetime, timezone

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.services import bootstrap_admin, create_invitation
from app.mailer import BrevoMailer, MailMessage, MemoryMailer, deliver_invitation
from app.models import MailDelivery, OrganizerInvitation
from app.web import create_app

NOW = datetime(2026, 10, 16, 10, tzinfo=timezone.utc)
MESSAGE = MailMessage(
    "delivery-test",
    "person@gmail.com",
    "Invitation",
    "<p>Test</p>",
    "Test",
    "https://impactflow.example/activation-organisateur#invitation=secret-test",
)


def brevo(web_settings, handler):
    settings = replace(
        web_settings,
        mailer_backend="brevo",
        mail_from_email="sender@example.org",
        brevo_api_key="test-key-not-real",
    )
    return BrevoMailer(settings, transport=httpx.MockTransport(handler))


def test_brevo_sends_expected_payload_without_secret_in_repr(web_settings):
    requests = []

    def handle(request):
        import json

        requests.append(request)
        assert request.url == "https://api.brevo.com/v3/smtp/email"
        assert request.headers["api-key"] == "test-key-not-real"
        body = json.loads(request.content)
        assert body["to"] == [{"email": MESSAGE.recipient}]
        assert body["sender"]["email"] == "sender@example.org"
        assert body["htmlContent"] == MESSAGE.html
        return httpx.Response(201, json={"messageId": "provider-test-id"})

    mailer = brevo(web_settings, handle)
    result = mailer.send(MESSAGE)
    assert result.status == "accepted" and result.provider_id == "provider-test-id"
    assert len(requests) == 1
    assert "test-key-not-real" not in repr(mailer.settings)
    assert "secret-test" not in repr(MESSAGE)


@pytest.mark.parametrize(
    "status,body,expected",
    [
        (400, {}, "failed"),
        (401, {}, "failed"),
        (429, {}, "failed"),
        (500, {}, "uncertain"),
        (503, {}, "uncertain"),
        (201, {}, "uncertain"),
        (201, [], "uncertain"),
        (302, {}, "failed"),
    ],
)
def test_provider_error_results_are_explicit_and_never_retried(
    web_settings, status, body, expected
):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(status, json=body)

    result = brevo(web_settings, handle).send(MESSAGE)
    assert result.status == expected and result.error_code
    assert len(requests) == 1


def test_network_timeout_is_uncertain_and_not_retried(web_settings):
    calls = []

    def handle(request):
        calls.append(request)
        raise httpx.ReadTimeout("private provider details", request=request)

    result = brevo(web_settings, handle).send(MESSAGE)
    assert result.status == "uncertain" and len(calls) == 1
    assert "private" not in repr(result)


@pytest.mark.parametrize(
    "email",
    [
        "demo@example.test",
        "test@example.org",
        "a@localhost",
        "b@sub.invalid",
        "c@sub.example",
        "d@sub.example.com",
        "e@sub.example.net",
        "f@sub.example.org",
        "g@sub.localhost",
    ],
)
def test_demo_recipients_never_reach_external_provider(web_settings, email):
    def forbidden(_):
        pytest.fail(
            "Aucun appel réseau ne doit être effectué pour les adresses fictives"
        )

    assert (
        brevo(web_settings, forbidden)
        .send(replace(MESSAGE, recipient=email))
        .error_code
        == "test_recipient_blocked"
    )


def invitation(database, settings):
    admin = bootstrap_admin(
        database,
        settings,
        "admin@example.test",
        "Admin",
        "Une phrase fictive pour les tests",
        NOW,
    )
    with database.transaction(immediate=True) as session:
        record, delivery, token = create_invitation(
            session, settings, admin.id, "test@example.test", NOW
        )
        return record.id, delivery.id, token


def test_delivery_is_persisted_once_without_storing_raw_invitation(
    database, web_settings
):
    invitation_id, delivery_id, token = invitation(database, web_settings)
    memory = MemoryMailer()
    assert (
        deliver_invitation(database, web_settings, memory, invitation_id, token, NOW)
        == "simulated"
    )
    assert (
        deliver_invitation(database, web_settings, memory, invitation_id, token, NOW)
        == "simulated"
    )
    assert len(memory.messages) == 1
    assert "#invitation=" + token in memory.messages[0].invitation_url
    assert "<a" in memory.messages[0].html
    with database.sessions() as session:
        delivery = session.get(MailDelivery, delivery_id)
        assert delivery.status == "simulated" and delivery.attempted_at == NOW
        assert session.get(OrganizerInvitation, invitation_id).status == "pending"
        for row in session.execute(select(OrganizerInvitation.__table__)).all():
            assert token not in str(row)


def test_unexpected_mailer_failure_preserves_invitation_and_is_not_retried(
    database, web_settings
):
    invitation_id, delivery_id, token = invitation(database, web_settings)

    class BrokenMailer:
        calls = 0

        def send(self, _):
            self.calls += 1
            raise RuntimeError("secret transport payload")

    mailer = BrokenMailer()
    assert (
        deliver_invitation(database, web_settings, mailer, invitation_id, token, NOW)
        == "uncertain"
    )
    assert (
        deliver_invitation(database, web_settings, mailer, invitation_id, token, NOW)
        == "uncertain"
    )
    assert mailer.calls == 1
    with database.sessions() as session:
        assert session.get(OrganizerInvitation, invitation_id).status == "pending"
        assert session.get(MailDelivery, delivery_id).error_code == "mailer_interrupted"


def test_started_delivery_is_not_replayed_after_restart(database, web_settings):
    invitation_id, delivery_id, token = invitation(database, web_settings)
    with database.transaction() as session:
        session.get(MailDelivery, delivery_id).status = "sending"
    restarted = MemoryMailer()
    assert (
        deliver_invitation(database, web_settings, restarted, invitation_id, token, NOW)
        == "sending"
    )
    assert restarted.messages == ()


@pytest.mark.parametrize(
    "values",
    [
        {"environment": "production"},
        {"environment": "production", "base_url": "https://impactflow.example"},
        {"mailer_backend": "brevo"},
        {"base_url": "https://impactflow.example/path"},
        {"base_url": "http://u:p@localhost"},
        {"base_url": "http://localhost:wrong"},
        {"session_ttl_seconds": 1},
        {"invitation_ttl_hours": 0},
        {"mail_from_email": "bad"},
    ],
)
def test_invalid_security_and_mailer_configuration_is_rejected(web_settings, values):
    with pytest.raises(ValueError):
        replace(web_settings, **values)


def test_https_uses_secure_host_only_cookie(database, web_settings):
    settings = replace(web_settings, base_url="https://testserver")
    with TestClient(create_app(settings), base_url=settings.base_url) as client:
        response = client.get("/connexion")
    cookie = response.headers["set-cookie"]
    assert "__Host-impactflow_session=" in cookie
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Domain=" not in cookie and "Path=/" in cookie
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "same-origin"


def test_brevo_settings_are_replaceable_without_memory_in_production(web_settings):
    settings = replace(
        web_settings,
        environment="production",
        base_url="https://impactflow.example",
        mailer_backend="brevo",
        mail_from_email="sender@example.org",
        brevo_api_key="fake",
    )
    assert settings.cookie_secure
    assert "fake" not in repr(settings)

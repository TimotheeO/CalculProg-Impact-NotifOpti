"""Une tentative, résultat explicite ; aucun mécanisme de réessai automatique."""

import smtplib
import threading
from collections import deque
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid

import httpx2 as httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select

from app.config import ROOT
from app.models import MailDelivery, OrganizerInvitation

MAIL_TEMPLATES = Environment(
    loader=FileSystemLoader(ROOT / "app" / "templates" / "emails"),
    autoescape=select_autoescape(),
)


@dataclass(frozen=True)
class MailMessage:
    delivery_id: str
    recipient: str
    subject: str
    html: str = field(repr=False)
    text: str = field(repr=False)
    invitation_url: str = field(repr=False)


@dataclass(frozen=True)
class MailResult:
    status: str
    provider_id: str | None = None
    error_code: str | None = None


class MemoryMailer:
    def __init__(self):
        self._messages = deque(maxlen=100)
        self._lock = threading.Lock()

    @property
    def messages(self):
        with self._lock:
            return tuple(self._messages)

    def send(self, message):
        with self._lock:
            self._messages.append(message)
        return MailResult("simulated")


class BrevoMailer:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.transport = transport

    def send(self, message):
        domain = message.recipient.rsplit("@", 1)[-1].casefold()
        reserved = ("localhost", "example.com", "example.net", "example.org")
        if any(
            domain == suffix or domain.endswith("." + suffix) for suffix in reserved
        ) or domain.endswith((".test", ".invalid", ".example")):
            return MailResult("failed", error_code="test_recipient_blocked")
        payload = {
            "sender": {
                "name": self.settings.mail_from_name,
                "email": self.settings.mail_from_email,
            },
            "to": [{"email": message.recipient}],
            "subject": message.subject,
            "htmlContent": message.html,
            "textContent": message.text,
        }
        try:
            with httpx.Client(
                timeout=10,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
            ) as client:
                response = client.post(
                    "https://api.brevo.com/v3/smtp/email",
                    json=payload,
                    headers={
                        "api-key": self.settings.brevo_api_key,
                        "accept": "application/json",
                    },
                )
            if 200 <= response.status_code < 300:
                data = response.json()
                provider_id = data.get("messageId") if isinstance(data, dict) else None
                if isinstance(provider_id, str) and 0 < len(provider_id) <= 240:
                    return MailResult("accepted", provider_id=provider_id)
                return MailResult("uncertain", error_code="invalid_provider_receipt")
            if response.status_code >= 500:
                return MailResult("uncertain", error_code="provider_server_error")
            return MailResult("failed", error_code="provider_rejected")
        except (httpx.HTTPError, ValueError):
            # Une coupure ne prouve pas que le fournisseur n’a pas reçu l’appel.
            return MailResult("uncertain", error_code="provider_response_unknown")


class MailpitMailer:
    """SMTP local uniquement : capture de test, jamais un relais externe."""

    def __init__(self, settings):
        self.settings = settings

    def send(self, message):
        mail = EmailMessage()
        sender = self.settings.mail_from_email or "impactflow@example.test"
        mail["From"] = f"{self.settings.mail_from_name} <{sender}>"
        mail["To"], mail["Subject"] = message.recipient, message.subject
        mail["Message-ID"] = make_msgid(domain="impactflow.local")
        mail.set_content(message.text)
        mail.add_alternative(message.html, subtype="html")
        try:
            with smtplib.SMTP(
                self.settings.smtp_host, self.settings.smtp_port, timeout=10
            ) as smtp:
                refused = smtp.send_message(mail)
            return (
                MailResult("failed", error_code="smtp_recipient_rejected")
                if refused
                else MailResult("accepted", provider_id=str(mail["Message-ID"]))
            )
        except (
            smtplib.SMTPRecipientsRefused,
            smtplib.SMTPSenderRefused,
            smtplib.SMTPDataError,
        ):
            return MailResult("failed", error_code="smtp_rejected")
        except ConnectionRefusedError:
            return MailResult("failed", error_code="mailpit_unavailable")
        except (smtplib.SMTPException, OSError):
            return MailResult("uncertain", error_code="smtp_response_unknown")


def make_mailer(settings):
    if settings.mailer_backend == "mailpit":
        return MailpitMailer(settings)
    return (
        BrevoMailer(settings) if settings.mailer_backend == "brevo" else MemoryMailer()
    )


def compose_message(
    settings,
    delivery_id,
    recipient,
    kind,
    *,
    event_name="",
    url=None,
    content="",
    reason="",
    expires="",
):
    url = url or f"{settings.base_url}/espace"
    subjects = {
        "organizer_invitation": "Votre invitation organisateur",
        "event_invitation": "Votre invitation à un événement",
        "request_verification": "Confirmez votre demande de participation",
        "request_response": "Réponse à votre demande",
        "notification": "Votre événement a changé",
        "cancellation": "Annulation : information importante",
        "password_reset": "Réinitialisez votre mot de passe",
    }
    title = subjects[kind]
    template = kind if kind not in {"notification", "cancellation"} else "change"
    context = {
        "title": title,
        "event_name": event_name,
        "url": url,
        "content": content,
        "reason": reason,
        "expires": expires,
    }
    return MailMessage(
        delivery_id,
        recipient,
        f"{title} — {event_name or 'ImpactFlow'}"[:240],
        MAIL_TEMPLATES.get_template(f"{template}.html").render(**context),
        MAIL_TEMPLATES.get_template(f"{template}.txt").render(**context),
        url,
    )


def deliver_invitation(database, settings, mailer, invitation_id, raw_token, now):
    with database.transaction(immediate=True) as session:
        invitation = session.get(OrganizerInvitation, invitation_id)
        delivery = session.scalars(
            select(MailDelivery).where(MailDelivery.invitation_id == invitation_id)
        ).one()
        if delivery.status != "pending":
            return delivery.status
        if invitation.status != "pending" or invitation.expires_at <= now:
            delivery.status, delivery.error_code = "failed", "invitation_inactive"
            return delivery.status
        delivery.status, delivery.attempted_at = "sending", now
        url = f"{settings.base_url.rstrip('/')}/activation-organisateur#invitation={raw_token}"
        message = MailMessage(
            delivery_id=delivery.id,
            recipient=invitation.email,
            subject="Votre invitation organisateur — ImpactFlow",
            html=MAIL_TEMPLATES.get_template("organizer_invitation.html").render(
                url=url, expires_at=invitation.expires_at
            ),
            text=f"Vous êtes invité(e) à organiser des événements sur ImpactFlow.\nOuvrez votre invitation : {url}\nElle expire le {invitation.expires_at.isoformat()}. Ouvrir le lien ne crée pas votre compte.",
            invitation_url=url,
        )
        delivery_id = delivery.id
    try:
        result = mailer.send(message)
    except Exception:  # noqa: BLE001 — frontière avec un adaptateur externe, résultat incertain
        # Un adaptateur défaillant ne doit ni masquer l’invitation ni provoquer un nouvel essai.
        result = MailResult("uncertain", error_code="mailer_interrupted")
    with database.transaction(immediate=True) as session:
        delivery = session.get(MailDelivery, delivery_id)
        delivery.status, delivery.provider_id, delivery.error_code = (
            result.status,
            result.provider_id,
            result.error_code,
        )
    return result.status

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from email_validator import EmailNotValidError, validate_email
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_url: str = f"sqlite:///{ROOT / 'var' / 'impactflow.sqlite3'}"
    environment: str = "development"
    base_url: str = "http://127.0.0.1:8000"
    session_ttl_seconds: int = 8 * 60 * 60
    invitation_ttl_hours: int = 48
    mailer_backend: str = "memory"
    mail_from_email: str = ""
    mail_from_name: str = "ImpactFlow"
    brevo_api_key: str = field(default="", repr=False)
    batch_window_seconds: float = 60
    send_max_per_period: int = 2
    send_period_seconds: float = 1
    send_daily_limit: int = 300
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1025
    mailpit_ui_url: str = "http://127.0.0.1:8025"
    worker_enabled: bool | None = None

    @property
    def cookie_secure(self):
        return (
            urlsplit(self.base_url).scheme == "https"
            or self.environment == "production"
        )

    @property
    def cookie_name(self):
        return (
            "__Host-impactflow_session" if self.cookie_secure else "impactflow_session"
        )

    def __post_init__(self):
        url = make_url(self.database_url)
        if url.drivername != "sqlite":
            raise ValueError(
                "C1-02 utilise SQLite : DATABASE_URL doit commencer par sqlite:///"
            )
        if (
            url.database not in (None, "", ":memory:")
            and not Path(url.database).is_absolute()
        ):
            raise ValueError(
                "DATABASE_URL doit utiliser un chemin absolu pour éviter deux bases différentes"
            )
        if url.query or url.host or url.username or url.password:
            raise ValueError(
                "DATABASE_URL contient des options SQLite non prises en charge"
            )
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("APP_ENV doit valoir development, test ou production")
        if url.database in (None, "", ":memory:") and self.environment != "test":
            raise ValueError("Une base sur disque est obligatoire hors des tests")
        origin = urlsplit(self.base_url)
        _ = origin.port  # Rejette aussi un port invalide.
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username
            or origin.password
            or origin.query
            or origin.fragment
            or origin.path not in {"", "/"}
        ):
            raise ValueError(
                "APP_BASE_URL doit être une origine HTTP(S), sans chemin, identifiants ou paramètres"
            )
        if self.environment == "production" and origin.scheme != "https":
            raise ValueError("HTTPS est obligatoire en production")
        if not 300 <= self.session_ttl_seconds <= 86400:
            raise ValueError("SESSION_TTL_SECONDS doit être compris entre 300 et 86400")
        if not 1 <= self.invitation_ttl_hours <= 168:
            raise ValueError("INVITATION_TTL_HOURS doit être compris entre 1 et 168")
        if self.mailer_backend not in {"memory", "brevo", "mailpit"}:
            raise ValueError("MAILER_BACKEND doit valoir memory, mailpit ou brevo")
        if self.environment == "production" and self.mailer_backend != "brevo":
            raise ValueError(
                "Les transports mémoire et Mailpit sont réservés au développement et aux tests"
            )
        if self.mailer_backend == "brevo" and (
            not self.brevo_api_key or not self.mail_from_email
        ):
            raise ValueError(
                "Configurer BREVO_API_KEY et MAIL_FROM_EMAIL pour le Mailer Brevo"
            )
        if self.mail_from_email:
            try:
                validate_email(
                    self.mail_from_email,
                    check_deliverability=False,
                    test_environment=self.mailer_backend == "mailpit",
                )
            except EmailNotValidError as error:
                raise ValueError("MAIL_FROM_EMAIL invalide") from error
        if len(self.mail_from_name) > 120 or any(
            c in self.mail_from_name for c in "\r\n"
        ):
            raise ValueError("MAIL_FROM_NAME invalide")
        if not 0 <= self.batch_window_seconds <= 3600:
            raise ValueError("BATCH_WINDOW_SECONDS doit être compris entre 0 et 3600")
        if (
            not 1 <= self.send_max_per_period <= 100
            or not 0.1 <= self.send_period_seconds <= 3600
            or not 1 <= self.send_daily_limit <= 10000
        ):
            raise ValueError("Limites d’envoi invalides")
        if (
            self.smtp_host not in {"127.0.0.1", "localhost", "::1"}
            or not 1 <= self.smtp_port <= 65535
        ):
            raise ValueError(
                "Mailpit doit être un serveur SMTP local, avec un port valide"
            )
        mailpit_origin = urlsplit(self.mailpit_ui_url)
        if (
            mailpit_origin.scheme != "http"
            or mailpit_origin.hostname not in {"127.0.0.1", "localhost", "::1"}
            or mailpit_origin.username
            or mailpit_origin.password
            or mailpit_origin.path not in {"", "/"}
            or mailpit_origin.query
            or mailpit_origin.fragment
        ):
            raise ValueError("MAILPIT_UI_URL doit être une origine HTTP locale")
        _ = mailpit_origin.port

    @classmethod
    def from_env(cls):
        load_dotenv(ROOT / ".env", override=False)
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            environment=os.getenv("APP_ENV", "development"),
            base_url=os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            session_ttl_seconds=int(os.getenv("SESSION_TTL_SECONDS", "28800")),
            invitation_ttl_hours=int(os.getenv("INVITATION_TTL_HOURS", "48")),
            mailer_backend=os.getenv("MAILER_BACKEND", "memory"),
            mail_from_email=os.getenv("MAIL_FROM_EMAIL", ""),
            mail_from_name=os.getenv("MAIL_FROM_NAME", "ImpactFlow"),
            brevo_api_key=os.getenv("BREVO_API_KEY", ""),
            batch_window_seconds=float(os.getenv("BATCH_WINDOW_SECONDS", "60")),
            send_max_per_period=int(os.getenv("SEND_MAX_PER_PERIOD", "2")),
            send_period_seconds=float(os.getenv("SEND_PERIOD_SECONDS", "1")),
            send_daily_limit=int(os.getenv("SEND_DAILY_LIMIT", "300")),
            smtp_host=os.getenv("SMTP_HOST", "127.0.0.1"),
            smtp_port=int(os.getenv("SMTP_PORT", "1025")),
            mailpit_ui_url=os.getenv("MAILPIT_UI_URL", "http://127.0.0.1:8025"),
            worker_enabled=cls.read_worker_setting(os.getenv("APP_WORKER_ENABLED")),
        )

    @staticmethod
    def read_worker_setting(value):
        if value is None:
            return None
        if value.lower() not in {"true", "false", "1", "0"}:
            raise ValueError("APP_WORKER_ENABLED doit valoir true ou false")
        return value.lower() in {"true", "1"}

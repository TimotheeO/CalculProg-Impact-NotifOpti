import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from email_validator import EmailNotValidError, validate_email

from app.services import DomainError

PASSWORDS = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
DUMMY_HASH = PASSWORDS.hash(secrets.token_urlsafe(32))


class AuthError(DomainError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def ensure_participation_allowed(user):
    if user is not None and user.role == "super_admin":
        raise AuthError(
            "Le compte super-admin est réservé à la gestion. Utilisez un compte personnel distinct pour participer.",
            403,
        )


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_email(value: str, *, development=False) -> str:
    try:
        return validate_email(
            value.strip(), check_deliverability=False, test_environment=development
        ).normalized.casefold()
    except EmailNotValidError as error:
        raise AuthError("Saisissez une adresse e-mail valide.", 422) from error


def validate_password(password: str):
    if not 15 <= len(password) <= 128 or password.isspace():
        raise AuthError("Choisissez une phrase de passe de 15 à 128 caractères.", 422)


def password_matches(stored: str | None, password: str) -> bool:
    candidate = password if len(password) <= 128 else ""
    try:
        valid = PASSWORDS.verify(stored or DUMMY_HASH, candidate)
        return bool(stored) and valid
    except (VerificationError, InvalidHashError):
        return False


def check_csrf(auth_session, value: str, request_origin: str | None, base_url: str):
    if (
        auth_session is None
        or not value
        or not secrets.compare_digest(auth_session.csrf_token.encode(), value.encode())
        or (
            request_origin is not None
            and request_origin.rstrip("/") != base_url.rstrip("/")
        )
    ):
        raise AuthError(
            "Le formulaire a expiré ou n’est pas valide. Rechargez la page avant de réessayer.",
            403,
        )

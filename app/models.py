from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, validates
from sqlalchemy.types import TypeDecorator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """SQLite stocke des dates naïves ; leur contrat applicatif reste UTC explicite."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Une date doit contenir son fuseau horaire")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value is not None else None


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s_%(column_1_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(column_1_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class CreatedAt:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class EmailIdentity:
    @validates("email")
    def normalize_email(self, key, value):
        value = value.strip().casefold()
        if not value or "@" not in value or len(value) > 254:
            raise ValueError("Adresse e-mail invalide")
        return value


class User(CreatedAt, EmailIdentity, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('super_admin', 'organizer', 'participant')", name="role"
        ),
        CheckConstraint("length(trim(name)) > 0", name="name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    # NULL = compte non activé, jamais un mot de passe en clair ou un login utilisable.
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20), default="participant")
    is_active: Mapped[bool] = mapped_column(
        Boolean(name="is_active", create_constraint=True), default=True
    )


class Contact(CreatedAt, EmailIdentity, Base):
    __tablename__ = "contacts"
    __table_args__ = (CheckConstraint("length(trim(name)) > 0", name="name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), unique=True)


class Event(CreatedAt, Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'published', 'cancelled', 'archived')", name="status"
        ),
        CheckConstraint(
            "participation_mode IN ('invitation', 'open')", name="participation_mode"
        ),
        CheckConstraint("ends_at > starts_at", name="schedule"),
        CheckConstraint("length(trim(name)) > 0", name="name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(String(240))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20), default="draft")
    participation_mode: Mapped[str] = mapped_column(String(20), default="invitation")


class EventOrganizer(CreatedAt, Base):
    __tablename__ = "event_organizers"

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)


class Workshop(CreatedAt, Base):
    __tablename__ = "workshops"
    __table_args__ = (
        UniqueConstraint("event_id", "id"),
        CheckConstraint("status IN ('active', 'cancelled')", name="status"),
        CheckConstraint("capacity IS NULL OR capacity > 0", name="capacity"),
        CheckConstraint("ends_at > starts_at", name="schedule"),
        CheckConstraint("length(trim(name)) > 0", name="name"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime())
    location: Mapped[str] = mapped_column(String(240))
    capacity: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active")


class Dependency(Base):
    __tablename__ = "dependencies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "base_workshop_id"], ["workshops.event_id", "workshops.id"]
        ),
        ForeignKeyConstraint(
            ["event_id", "dependent_workshop_id"],
            ["workshops.event_id", "workshops.id"],
        ),
        CheckConstraint("base_workshop_id != dependent_workshop_id", name="not_self"),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    base_workshop_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dependent_workshop_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class Participation(CreatedAt, Base):
    __tablename__ = "participations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('confirmed', 'withdrawn', 'removed', 'pending_confirmation')",
            name="status",
        ),
    )

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="confirmed")


class Enrollment(CreatedAt, Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "user_id"],
            ["participations.event_id", "participations.user_id"],
        ),
        ForeignKeyConstraint(
            ["event_id", "workshop_id"], ["workshops.event_id", "workshops.id"]
        ),
        CheckConstraint(
            "status IN ('active', 'cancelled', 'removed', 'pending_confirmation')",
            name="status",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workshop_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="active")


class Invitation(CreatedAt, EmailIdentity, Base):
    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("event_id", "id"),
        UniqueConstraint("event_id", "email"),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'revoked', 'expired')",
            name="status",
        ),
        CheckConstraint("expires_at > created_at", name="expiry"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    email: Mapped[str] = mapped_column(String(254))
    inviter_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    purpose: Mapped[str] = mapped_column(
        String(20), default="invitation", server_default="invitation"
    )
    invitee_name: Mapped[str | None] = mapped_column(String(120))


class InvitationWorkshop(Base):
    __tablename__ = "invitation_workshops"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "invitation_id"], ["invitations.event_id", "invitations.id"]
        ),
        ForeignKeyConstraint(
            ["event_id", "workshop_id"], ["workshops.event_id", "workshops.id"]
        ),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    invitation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workshop_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class InvitationResponse(CreatedAt, Base):
    __tablename__ = "invitation_responses"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "invitation_id"], ["invitations.event_id", "invitations.id"]
        ),
        CheckConstraint("response IN ('accepted', 'declined')", name="response"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    invitation_id: Mapped[str] = mapped_column(String(64))
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    response: Mapped[str] = mapped_column(String(20))


class ParticipationRequest(CreatedAt, Base):
    __tablename__ = "participation_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'withdrawn')", name="status"
        ),
    )

    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")


class OrganizerInvitation(CreatedAt, EmailIdentity, Base):
    __tablename__ = "organizer_invitations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired')", name="status"
        ),
        CheckConstraint("expires_at > created_at", name="expiry"),
        Index(
            "uq_organizer_pending_email",
            "email",
            unique=True,
            sqlite_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    inviter_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    accepted_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class AuthSession(CreatedAt, Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (CheckConstraint("expires_at > created_at", name="expiry"),)

    token_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    pending_invitation_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizer_invitations.id")
    )
    pending_event_invitation_id: Mapped[str | None] = mapped_column(
        ForeignKey("invitations.id")
    )
    pending_password_reset_id: Mapped[str | None] = mapped_column(
        ForeignKey("password_resets.id")
    )


class PasswordReset(CreatedAt, Base):
    __tablename__ = "password_resets"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AuthRateLimit(Base):
    __tablename__ = "auth_rate_limits"
    __table_args__ = (CheckConstraint("attempts > 0", name="attempts"),)

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    attempts: Mapped[int] = mapped_column(Integer)


class AuthAudit(CreatedAt, Base):
    __tablename__ = "auth_audit"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    target_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    invitation_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizer_invitations.id")
    )
    action: Mapped[str] = mapped_column(String(40))


class MailDelivery(CreatedAt, Base):
    __tablename__ = "mail_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sending', 'simulated', 'accepted', 'failed', 'uncertain')",
            name="status",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    invitation_id: Mapped[str | None] = mapped_column(
        ForeignKey("organizer_invitations.id"), unique=True
    )
    event_id: Mapped[str | None] = mapped_column(ForeignKey("events.id"), index=True)
    event_invitation_id: Mapped[str | None] = mapped_column(
        ForeignKey("invitations.id")
    )
    notification_id: Mapped[str | None] = mapped_column(
        ForeignKey("notifications.id"), unique=True
    )
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(
        String(32),
        default="organizer_invitation",
        server_default="organizer_invitation",
    )
    recipient: Mapped[str | None] = mapped_column(String(254))
    subject: Mapped[str | None] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    backend: Mapped[str] = mapped_column(String(20))
    attempted_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    provider_id: Mapped[str | None] = mapped_column(String(240))
    error_code: Mapped[str | None] = mapped_column(String(80))
    password_reset_id: Mapped[str | None] = mapped_column(
        ForeignKey("password_resets.id")
    )
    context: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class MailAttempt(Base):
    __tablename__ = "mail_attempts"
    __table_args__ = (UniqueConstraint("delivery_id", "number"),)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    delivery_id: Mapped[str] = mapped_column(
        ForeignKey("mail_deliveries.id"), index=True
    )
    number: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(20))
    provider_id: Mapped[str | None] = mapped_column(String(240))
    error_code: Mapped[str | None] = mapped_column(String(80))
    content_revision: Mapped[int | None] = mapped_column(Integer)


class EventOperation(CreatedAt, Base):
    __tablename__ = "event_operations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40))
    request_digest: Mapped[str] = mapped_column(String(64))


class EventAction(CreatedAt, Base):
    __tablename__ = "event_actions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    kind: Mapped[str] = mapped_column(String(40))
    target_id: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class Change(CreatedAt, Base):
    __tablename__ = "changes"
    __table_args__ = (
        UniqueConstraint("event_id", "id"),
        ForeignKeyConstraint(
            ["event_id", "workshop_id"], ["workshops.event_id", "workshops.id"]
        ),
        CheckConstraint("length(trim(field)) > 0", name="field"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), index=True)
    workshop_id: Mapped[str | None] = mapped_column(String(64))
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    field: Mapped[str] = mapped_column(String(80))
    old_value: Mapped[object | None] = mapped_column(JSON)
    new_value: Mapped[object | None] = mapped_column(JSON)
    operation_id: Mapped[str | None] = mapped_column(String(64), index=True)
    notification_scope: Mapped[str] = mapped_column(
        String(16), default="none", server_default="none"
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class Notification(CreatedAt, Base):
    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("event_id", "id"),
        ForeignKeyConstraint(
            ["event_id", "user_id"],
            ["participations.event_id", "participations.user_id"],
        ),
        CheckConstraint(
            "status IN ('pending', 'ready', 'sending', 'sent', 'failed', 'uncertain', 'skipped')",
            name="status",
        ),
        CheckConstraint("urgency BETWEEN 0 AND 2", name="urgency"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    urgency: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    opened_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), index=True)
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    naive_requests: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    replaced_fields: Mapped[list] = mapped_column(
        JSON, default=list, server_default="[]"
    )


class NotificationChange(Base):
    __tablename__ = "notification_changes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_id", "notification_id"],
            ["notifications.event_id", "notifications.id"],
        ),
        ForeignKeyConstraint(
            ["event_id", "change_id"], ["changes.event_id", "changes.id"]
        ),
    )

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    notification_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    change_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    active: Mapped[bool] = mapped_column(
        Boolean(), default=True, server_default=text("1")
    )

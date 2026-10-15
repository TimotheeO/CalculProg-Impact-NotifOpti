from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
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
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
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
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    inviter_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


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

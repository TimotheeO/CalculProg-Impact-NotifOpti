"""Un ordonnanceur par base, file heapq et limiteur glissant historiques."""

import fcntl
import logging
import threading
from collections import OrderedDict
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select

from app.mailer import MailResult, MemoryMailer, compose_message
from app.models import (
    Event,
    Invitation,
    MailDelivery,
    Notification,
    OrganizerInvitation,
    Participation,
    User,
)
from app.notification_groups import recalculate_pending
from src.notifications import Notification as QueuedNotification
from src.notifications import NotificationQueue, Urgency
from src.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class Scheduler:
    def __init__(self, database, settings, mailer, clock):
        self.database, self.settings, self.mailer, self.clock = (
            database,
            settings,
            mailer,
            clock,
        )
        self._lock = threading.RLock()
        self._queue_lock = threading.Lock()
        self._payloads = OrderedDict()
        self._stop = threading.Event()
        self._thread = None
        self._file = None
        self.last_error = None
        self._limiter = None

    def _rate_limiter(self):
        if self._limiter is None:
            marker = [self.clock().timestamp()]
            limiter = RateLimiter(
                self.settings.send_max_per_period,
                self.settings.send_period_seconds,
                clock=lambda: marker[0],
            )
            with self.database.sessions() as session:
                attempts = list(
                    session.scalars(
                        select(MailDelivery.attempted_at)
                        .where(
                            MailDelivery.attempted_at
                            > self.clock()
                            - timedelta(seconds=self.settings.send_period_seconds)
                        )
                        .order_by(MailDelivery.attempted_at.desc())
                        .limit(self.settings.send_max_per_period)
                    )
                )
            for timestamp in reversed(attempts):
                marker[0] = timestamp.timestamp()
                limiter.try_acquire()
            self._limiter, self._marker = limiter, marker
        self._marker[0] = self.clock().timestamp()
        return self._limiter

    def submit(self, delivery_id, message):
        with self._queue_lock:
            if len(self._payloads) >= 1000 and delivery_id not in self._payloads:
                with self.database.transaction(immediate=True) as session:
                    row = session.get(MailDelivery, delivery_id)
                    row.status, row.error_code = "failed", "local_queue_full"
                return
            self._payloads[delivery_id] = message
        if isinstance(self.mailer, MemoryMailer):
            self.tick()

    def submit_organizer(self, invitation_id, token):
        with self.database.transaction(immediate=True) as session:
            invitation = session.get(OrganizerInvitation, invitation_id)
            delivery = session.scalars(
                select(MailDelivery).where(MailDelivery.invitation_id == invitation_id)
            ).one()
            delivery.recipient = invitation.email
            url = f"{self.settings.base_url}/activation-organisateur#invitation={token}"
            message = compose_message(
                self.settings,
                delivery.id,
                invitation.email,
                "organizer_invitation",
                url=url,
                expires=invitation.expires_at.isoformat(),
            )
            delivery.subject = message.subject
            delivery_id = delivery.id
        self.submit(delivery_id, message)

    def _message_for_notification(self, session, delivery):
        notification = session.get(Notification, delivery.notification_id)
        user = session.get(User, notification.user_id)
        event = session.get(Event, notification.event_id)
        return compose_message(
            self.settings,
            delivery.id,
            user.email,
            "request_response"
            if delivery.kind == "request_response"
            else "cancellation"
            if notification.urgency == 0
            else "notification",
            event_name=event.name,
            content=notification.message,
            reason=notification.reason,
        )

    def _prepare_groups(self):
        now = self.clock()
        with self.database.transaction(immediate=True) as session:
            recalculate_pending(session, now, self.settings.batch_window_seconds)
            queue = NotificationQueue()
            for row in session.scalars(
                select(Notification)
                .where(Notification.status == "ready")
                .order_by(Notification.due_at, Notification.created_at, Notification.id)
            ):
                queue.push(
                    QueuedNotification(row.id, "", row.message, Urgency(row.urgency))
                )
            while not queue.is_empty():
                notification = session.get(
                    Notification, queue.pop_next().participant_id
                )
                delivery = session.scalar(
                    select(MailDelivery).where(
                        MailDelivery.notification_id == notification.id
                    )
                )
                if delivery is None:
                    user = session.get(User, notification.user_id)
                    delivery = MailDelivery(
                        id=str(uuid4()),
                        event_id=notification.event_id,
                        user_id=user.id,
                        notification_id=notification.id,
                        kind="notification",
                        recipient=user.email,
                        backend=self.settings.mailer_backend,
                        status="pending",
                        created_at=now,
                    )
                    session.add(delivery)
                    session.flush()
                if delivery.status == "pending":
                    message = self._message_for_notification(session, delivery)
                    delivery.subject = message.subject
                    self._payloads[delivery.id] = message

    def _still_relevant(self, session, delivery):
        now = self.clock()
        if delivery.user_id:
            recipient = session.get(User, delivery.user_id)
            if recipient is None or not recipient.is_active:
                return False
        if delivery.invitation_id:
            invitation = session.get(OrganizerInvitation, delivery.invitation_id)
            return invitation.status == "pending" and invitation.expires_at > now
        if delivery.event_invitation_id:
            invitation = session.get(Invitation, delivery.event_invitation_id)
            event = session.get(Event, invitation.event_id)
            return (
                invitation.status == "pending"
                and invitation.expires_at > now
                and event.status == "published"
            )
        if delivery.notification_id:
            notification = session.get(Notification, delivery.notification_id)
            user = session.get(User, notification.user_id)
            if (
                not user
                or not user.is_active
                or notification.status != "ready"
                or not notification.message
            ):
                return False
            if delivery.kind != "request_response":
                participation = session.get(
                    Participation, (notification.event_id, notification.user_id)
                )
                return participation is not None and participation.status == "confirmed"
        return True

    def _priority(self, delivery_id):
        with self.database.sessions() as session:
            delivery = session.get(MailDelivery, delivery_id)
            notification = (
                session.get(Notification, delivery.notification_id)
                if delivery and delivery.notification_id
                else None
            )
            return notification.urgency if notification else 1

    def tick(self):
        with self._lock:
            self._prepare_groups()
            with self._queue_lock:
                pending_ids = list(self._payloads)
            for delivery_id in sorted(pending_ids, key=self._priority):
                if self._stop.is_set():
                    break
                with self.database.transaction(immediate=True) as session:
                    recalculate_pending(
                        session, self.clock(), self.settings.batch_window_seconds
                    )
                    delivery = session.get(MailDelivery, delivery_id)
                    if not delivery or delivery.status != "pending":
                        self._payloads.pop(delivery_id, None)
                        continue
                    if not self._still_relevant(session, delivery):
                        delivery.status, delivery.error_code = (
                            "failed",
                            "no_longer_relevant",
                        )
                        if delivery.notification_id:
                            session.get(
                                Notification, delivery.notification_id
                            ).status = "skipped"
                        self._payloads.pop(delivery_id, None)
                        continue
                    midnight = self.clock().replace(
                        hour=0, minute=0, second=0, microsecond=0
                    )
                    daily = session.scalar(
                        select(func.count())
                        .select_from(MailDelivery)
                        .where(MailDelivery.attempted_at >= midnight)
                    )
                    if (
                        daily >= self.settings.send_daily_limit
                        or not self._rate_limiter().try_acquire()
                    ):
                        break
                    message = (
                        self._message_for_notification(session, delivery)
                        if delivery.notification_id
                        else self._payloads[delivery_id]
                    )
                    delivery.status, delivery.attempted_at = "sending", self.clock()
                    if delivery.notification_id:
                        session.get(
                            Notification, delivery.notification_id
                        ).status = "sending"
                self._payloads.pop(delivery_id, None)
                try:
                    result = self.mailer.send(message)
                except Exception:  # noqa: BLE001 — frontière de transport, jamais de réessai
                    result = MailResult("uncertain", error_code="mailer_interrupted")
                with self.database.transaction(immediate=True) as session:
                    delivery = session.get(MailDelivery, delivery_id)
                    delivery.status, delivery.provider_id, delivery.error_code = (
                        result.status,
                        result.provider_id,
                        result.error_code,
                    )
                    if delivery.notification_id:
                        session.get(Notification, delivery.notification_id).status = (
                            "sent"
                            if result.status in {"accepted", "simulated"}
                            else result.status
                        )
            self.last_error = None

    def start(self):
        enabled = (
            self.settings.worker_enabled
            if self.settings.worker_enabled is not None
            else self.settings.environment != "test"
        )
        if not enabled or self._thread:
            return
        # Le verrou vit aussi longtemps que le worker ; close() ferme ce descripteur.
        self._file = open(Path(self.database.path + ".scheduler.lock"), "a")  # noqa: SIM115
        try:
            fcntl.flock(self._file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self._file.close()
            self._file = None
            raise RuntimeError(
                "Un ordonnanceur utilise déjà cette base. Démarrez un seul processus Uvicorn."
            ) from error
        with self.database.transaction(immediate=True) as session:
            for delivery in session.scalars(
                select(MailDelivery).where(
                    MailDelivery.status.in_(("pending", "sending"))
                )
            ):
                if delivery.status == "sending":
                    delivery.status, delivery.error_code = (
                        "uncertain",
                        "interrupted_during_attempt",
                    )
                    if delivery.notification_id:
                        session.get(
                            Notification, delivery.notification_id
                        ).status = "uncertain"
                elif delivery.notification_id is None:
                    delivery.status, delivery.error_code = (
                        "failed",
                        "interrupted_before_attempt",
                    )
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="impactflow-scheduler", daemon=True
        )
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as error:  # noqa: BLE001 — garder le worker vivant, sans afficher de données personnelles
                self.last_error = type(error).__name__
                logger.error("Scheduler unavailable: %s", self.last_error)
            self._stop.wait(0.25)

    def close(self):
        if self._thread:
            self._stop.set()
            self._thread.join(timeout=12)
            if self._thread.is_alive():
                raise RuntimeError(
                    "L’ordonnanceur ne s’est pas arrêté ; conservez le processus avant de relancer."
                )
            self._thread = None
        if self._file:
            fcntl.flock(self._file, fcntl.LOCK_UN)
            self._file.close()
            self._file = None

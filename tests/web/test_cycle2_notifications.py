"""Urgence, reprise, relance manuelle et retour volontaire après annulation."""

from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.deliveries import retry_delivery
from app.events.services import (
    EventError,
    cancel_event,
    change_event_state,
    revision,
    workshops_for,
)
from app.mailer import MailResult, MemoryMailer
from app.models import (
    Enrollment,
    Event,
    Invitation,
    MailAttempt,
    MailDelivery,
    Notification,
    Participation,
    User,
    Workshop,
)
from app.participation.lifecycle import confirm_participation, withdraw
from app.participation.services import (
    create_invitations,
    places_for,
    replace_enrollments,
    validate_enrollments,
)
from app.seeds import EVENT_ID, OWNER_ID
from app.worker import Scheduler
from app.workshops.services import update_workshop, workshop_revision
from app.workshops.types import snapshot
from tests.web.test_cycle1 import change, worker


def test_cancellation_goes_now_and_unrelated_workshop_keeps_its_deadline(
    seeded_db, web_settings, web_clock
):
    with seeded_db.transaction() as session:
        session.add(
            Enrollment(
                event_id=EVENT_ID,
                user_id="demo-alice",
                workshop_id="w4",
                status="active",
            )
        )
    change(seeded_db, web_clock, location="Information caduque")
    change(seeded_db, web_clock, "w4", location="Information indépendante")
    web_clock.advance(5)
    change(seeded_db, web_clock, status="cancelled")
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 4
    alice = next(
        m for m in scheduler.mailer.messages if m.recipient == "demo-alice@example.test"
    )
    assert (
        "Annulation" in alice.subject
        and "Information caduque" not in alice.text
        and "Information indépendante" not in alice.text
    )
    with seeded_db.sessions() as session:
        pending = list(
            session.scalars(
                select(Notification).where(Notification.status == "pending")
            )
        )
        assert {n.user_id for n in pending} >= {"demo-alice", "demo-nora"}
    web_clock.advance(55)
    scheduler.tick()
    independent = [
        m for m in scheduler.mailer.messages if "Information indépendante" in m.text
    ]
    assert len(independent) == 2
    assert all("Information caduque" not in m.text for m in scheduler.mailer.messages)


@pytest.mark.parametrize("with_dependents", [False, True])
def test_reactivation_is_opt_in_and_old_places_require_new_confirmation(
    seeded_db, web_settings, web_clock, with_dependents
):
    change(seeded_db, web_clock, status="cancelled")
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    with seeded_db.transaction(immediate=True) as session:
        event = session.get(Event, EVENT_ID)
        workshop = session.get(Workshop, "w1")
        update_workshop(
            session,
            EVENT_ID,
            "w1",
            OWNER_ID,
            replace(snapshot(workshop), status="active"),
            workshop_revision(session, event),
            web_clock(),
            operation_id=str(uuid4()),
            reactivate_dependents=with_dependents,
        )
    with seeded_db.sessions() as session:
        assert session.get(Workshop, "w1").status == "active"
        assert session.get(Workshop, "w2").status == (
            "active" if with_dependents else "cancelled"
        )
        assert session.get(Workshop, "w3").status == (
            "active" if with_dependents else "cancelled"
        )
        assert (
            session.get(Enrollment, (EVENT_ID, "demo-alice", "w1")).status
            == "pending_confirmation"
        )
        assert (
            places_for(session, EVENT_ID)["w1"] == session.get(Workshop, "w1").capacity
        )
    with seeded_db.transaction() as session:
        selected = validate_enrollments(
            session, session.get(Event, EVENT_ID), "demo-alice", ["w1"]
        )
        replace_enrollments(
            session, session.get(Event, EVENT_ID), "demo-alice", selected, web_clock()
        )
    with seeded_db.sessions() as session:
        assert (
            session.get(Enrollment, (EVENT_ID, "demo-alice", "w1")).status == "active"
        )


def test_withdrawal_frees_places_and_recalculates_pending_recipients(
    seeded_db, web_settings, web_clock
):
    change(seeded_db, web_clock, location="Salle finale")
    with seeded_db.transaction(immediate=True) as session:
        withdraw(
            session,
            EVENT_ID,
            "demo-alice",
            "demo-alice",
            web_clock(),
            operation_id=str(uuid4()),
        )
    web_clock.advance(60)
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    assert {m.recipient for m in scheduler.mailer.messages} == {
        "demo-sofia@example.test"
    }
    with seeded_db.sessions() as session:
        assert (
            session.get(Participation, (EVENT_ID, "demo-alice")).status == "withdrawn"
        )
        assert (
            session.get(Enrollment, (EVENT_ID, "demo-alice", "w1")).status
            == "cancelled"
        )


def test_organizer_can_remove_one_workshop_without_removing_other_enrollments(
    seeded_db, web_clock
):
    with seeded_db.transaction() as session:
        withdraw(
            session,
            EVENT_ID,
            "demo-alice",
            OWNER_ID,
            web_clock(),
            organizer=True,
            workshop_id="w1",
        )
    with seeded_db.sessions() as session:
        assert (
            session.get(Enrollment, (EVENT_ID, "demo-alice", "w1")).status == "removed"
        )
        assert (
            session.get(Enrollment, (EVENT_ID, "demo-alice", "w2")).status == "active"
        )
        assert (
            session.get(Participation, (EVENT_ID, "demo-alice")).status == "confirmed"
        )
    with pytest.raises(EventError), seeded_db.transaction() as session:
        withdraw(
            session, EVENT_ID, "demo-alice", "demo-lea", web_clock(), organizer=False
        )


def test_event_cancel_reactivate_and_confirm_does_not_reserve_old_places(
    seeded_db, web_settings, web_clock
):
    with seeded_db.transaction() as session:
        event = session.get(Event, EVENT_ID)
        cancel_event(
            session,
            EVENT_ID,
            OWNER_ID,
            revision(event, workshops_for(session, EVENT_ID)),
            web_clock(),
        )
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    assert len(scheduler.mailer.messages) == 8
    assert any(
        m.recipient == "demo-alex@example.test" for m in scheduler.mailer.messages
    )
    with seeded_db.transaction() as session:
        event = session.get(Event, EVENT_ID)
        change_event_state(
            session,
            EVENT_ID,
            OWNER_ID,
            "reactiver",
            revision(event, workshops_for(session, EVENT_ID)),
            web_clock(),
            operation_id=str(uuid4()),
        )
    with seeded_db.sessions() as session:
        assert (
            session.get(Participation, (EVENT_ID, "demo-alice")).status
            == "pending_confirmation"
        )
        assert (
            session.get(Enrollment, (EVENT_ID, "demo-alice", "w1")).status
            == "pending_confirmation"
        )
        assert all(
            i.status != "pending"
            for i in session.scalars(
                select(Invitation).where(Invitation.event_id == EVENT_ID)
            )
        )
    with seeded_db.transaction() as session:
        confirm_participation(session, EVENT_ID, "demo-alice", ["w1"], web_clock(), 60)
    with seeded_db.sessions() as session:
        assert (
            session.get(Participation, (EVENT_ID, "demo-alice")).status == "confirmed"
        )
        assert (
            session.get(Enrollment, (EVENT_ID, "demo-alice", "w1")).status == "active"
        )
        assert (
            session.get(Enrollment, (EVENT_ID, "demo-alice", "w2")).status
            == "cancelled"
        )


class ControlledMailer(MemoryMailer):
    def __init__(self, first="failed"):
        super().__init__()
        self.calls = 0
        self.first = first

    def send(self, message):
        self.calls += 1
        super().send(message)
        return MailResult(
            self.first if self.calls == 1 else "simulated",
            error_code="controlled_failure" if self.calls == 1 else None,
        )


def test_failed_mail_never_retries_automatically_but_manual_retry_is_audited(
    seeded_db, web_settings, web_clock
):
    change(seeded_db, web_clock, "w4", location="Nouvelle salle")
    web_clock.advance(60)
    mailer = ControlledMailer()
    scheduler = worker(seeded_db, web_settings, web_clock, mailer=mailer)
    scheduler.tick()
    assert mailer.calls == 1
    web_clock.advance(1000)
    scheduler.tick()
    resumed = Scheduler(seeded_db, web_settings, mailer, web_clock)
    resumed.tick()
    assert mailer.calls == 1
    with seeded_db.sessions() as session:
        delivery = session.scalar(
            select(MailDelivery).where(MailDelivery.notification_id.is_not(None))
        )
        assert session.get(Notification, delivery.notification_id).message
        delivery_id = delivery.id
    operation_id = str(uuid4())
    for _ in range(2):
        with seeded_db.transaction() as session:
            retry_delivery(
                session, EVENT_ID, delivery_id, OWNER_ID, operation_id, web_clock()
            )
    resumed.tick()
    assert mailer.calls == 2
    with seeded_db.sessions() as session:
        attempts = list(
            session.scalars(select(MailAttempt).order_by(MailAttempt.number))
        )
        assert [a.status for a in attempts] == ["failed", "simulated"]
        assert [a.actor_id for a in attempts] == [None, OWNER_ID]
        assert [a.number for a in attempts] == [1, 2]
    with pytest.raises(EventError), seeded_db.transaction() as session:
        retry_delivery(
            session, EVENT_ID, delivery_id, OWNER_ID, str(uuid4()), web_clock()
        )


def test_uncertain_mail_requires_explicit_provider_check_before_retry(
    seeded_db, web_settings, web_clock
):
    change(seeded_db, web_clock, "w4", location="Nouvelle salle")
    web_clock.advance(60)
    mailer = ControlledMailer("uncertain")
    scheduler = worker(seeded_db, web_settings, web_clock, mailer=mailer)
    scheduler.tick()
    with seeded_db.sessions() as session:
        delivery_id = session.scalar(
            select(MailDelivery.id).where(MailDelivery.kind == "notification")
        )
    with (
        pytest.raises(EventError, match="Vérifiez"),
        seeded_db.transaction() as session,
    ):
        retry_delivery(
            session, EVENT_ID, delivery_id, OWNER_ID, str(uuid4()), web_clock()
        )
    with seeded_db.transaction() as session:
        retry_delivery(
            session,
            EVENT_ID,
            delivery_id,
            OWNER_ID,
            str(uuid4()),
            web_clock(),
            reviewed=True,
            note="Transport vérifié : aucune acceptation dans les journaux.",
        )
    scheduler.tick()
    assert mailer.calls == 2


def test_never_attempted_invitation_is_rebuilt_after_memory_loss(
    seeded_db, web_settings, web_clock
):
    with seeded_db.transaction() as session:
        from app.models import Contact

        contact = Contact(id="fresh-contact", name="Invité", email="fresh@example.test")
        session.add(contact)
        session.flush()
        deliveries, _ = create_invitations(
            session, web_settings, EVENT_ID, OWNER_ID, [contact.id], [], web_clock()
        )
        old_url = deliveries[0][1].invitation_url
    mailer = MemoryMailer()
    scheduler = Scheduler(seeded_db, web_settings, mailer, web_clock)
    scheduler.tick()
    assert len(mailer.messages) == 1
    assert mailer.messages[0].invitation_url != old_url
    with seeded_db.sessions() as session:
        assert session.scalar(select(func.count()).select_from(MailAttempt)) == 1


def test_restart_preserves_remaining_window_and_completed_delivery(
    seeded_db, web_settings, web_clock
):
    change(seeded_db, web_clock, "w4", location="Salle persistante")
    first = worker(seeded_db, web_settings, web_clock)
    first.tick()
    web_clock.advance(40)
    resumed = worker(seeded_db, web_settings, web_clock)
    resumed.tick()
    assert not resumed.mailer.messages
    web_clock.advance(20)
    resumed.tick()
    assert len(resumed.mailer.messages) == 1
    third = worker(seeded_db, web_settings, web_clock)
    third.tick()
    assert not third.mailer.messages


def test_interrupted_attempt_becomes_uncertain_and_never_restarts(
    seeded_db, web_settings, web_clock
):
    change(seeded_db, web_clock, "w4", location="Salle avant interruption")
    web_clock.advance(60)
    scheduler = worker(seeded_db, web_settings, web_clock, mailer=ControlledMailer())
    scheduler.tick()
    with seeded_db.transaction() as session:
        delivery = session.scalar(
            select(MailDelivery).where(
                MailDelivery.user_id == "demo-nora", MailDelivery.kind == "notification"
            )
        )
        delivery.status = "sending"
        session.get(Notification, delivery.notification_id).status = "sending"
        attempt = session.scalar(
            select(MailAttempt).where(MailAttempt.delivery_id == delivery.id)
        )
        attempt.status, attempt.finished_at = "sending", None
        delivery_id = delivery.id
    mailer = MemoryMailer()
    restarted = Scheduler(
        seeded_db, replace(web_settings, worker_enabled=True), mailer, web_clock
    )
    try:
        restarted.start()
    finally:
        restarted.close()
    restarted.tick()
    assert not mailer.messages
    with seeded_db.sessions() as session:
        assert session.get(MailDelivery, delivery_id).status == "uncertain"
        assert (
            session.scalar(
                select(MailAttempt).where(MailAttempt.delivery_id == delivery_id)
            ).status
            == "uncertain"
        )


def test_schedule_conflict_is_notified_without_removing_existing_enrollment(
    seeded_db, web_settings, web_clock
):
    from app.events.services import PARIS

    with seeded_db.sessions() as session:
        day = (
            session.get(Event, EVENT_ID)
            .starts_at.astimezone(PARIS)
            .strftime("%Y-%m-%d")
        )
    change(seeded_db, web_clock, "w6", starts_at=day + "T16:30", ends_at=day + "T17:30")
    with seeded_db.transaction() as session:
        session.add(
            Enrollment(
                event_id=EVENT_ID,
                user_id="demo-alice",
                workshop_id="w6",
                status="active",
            )
        )
    change(seeded_db, web_clock, ends_at=day + "T16:00")
    web_clock.advance(60)
    scheduler = worker(seeded_db, web_settings, web_clock, send_max_per_period=100)
    scheduler.tick()
    alice = next(
        m for m in scheduler.mailer.messages if m.recipient == "demo-alice@example.test"
    )
    assert (
        "Conflit horaire" in alice.text and "inscriptions sont conservées" in alice.text
    )
    with seeded_db.sessions() as session:
        assert (
            session.get(Enrollment, (EVENT_ID, "demo-alice", "w2")).status == "active"
        )
        assert (
            session.get(Enrollment, (EVENT_ID, "demo-alice", "w6")).status == "active"
        )


def test_two_concurrent_retry_commands_reserve_only_one_new_attempt(
    seeded_db, web_settings, web_clock
):
    from concurrent.futures import ThreadPoolExecutor

    change(seeded_db, web_clock, "w4", location="Lieu de concurrence")
    web_clock.advance(60)
    scheduler = worker(seeded_db, web_settings, web_clock, mailer=ControlledMailer())
    scheduler.tick()
    with seeded_db.sessions() as session:
        delivery_id = session.scalar(
            select(MailDelivery.id).where(
                MailDelivery.user_id == "demo-nora", MailDelivery.kind == "notification"
            )
        )

    def submit_retry():
        try:
            with seeded_db.transaction(immediate=True) as session:
                retry_delivery(
                    session, EVENT_ID, delivery_id, OWNER_ID, str(uuid4()), web_clock()
                )
            return "reserved"
        except EventError:
            return "refused"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: submit_retry(), range(2)))
    assert sorted(results) == ["refused", "reserved"]
    scheduler.tick()
    with seeded_db.sessions() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(MailAttempt)
                .where(MailAttempt.delivery_id == delivery_id)
            )
            == 2
        )


def test_pending_public_verification_does_not_mail_account_disabled_before_send(
    seeded_db, web_settings, web_clock
):
    from app.participation.services import public_request
    from app.seeds import SECOND_EVENT_ID

    with seeded_db.transaction() as session:
        deliveries = public_request(
            session,
            web_settings,
            session.get(Event, SECOND_EVENT_ID),
            None,
            "demo-nora@example.test",
            "Nora",
            web_clock(),
        )
    with seeded_db.transaction() as session:
        session.get(User, "demo-nora").is_active = False
    mailer = MemoryMailer()
    scheduler = Scheduler(seeded_db, web_settings, mailer, web_clock)
    scheduler.submit(*deliveries[0])
    assert not mailer.messages
    with seeded_db.sessions() as session:
        delivery = session.get(MailDelivery, deliveries[0][0])
        assert (
            delivery.attempted_at is None
            and delivery.error_code == "no_longer_relevant"
        )
    with seeded_db.transaction() as session:
        assert (
            public_request(
                session,
                web_settings,
                session.get(Event, SECOND_EVENT_ID),
                None,
                "demo-nora@example.test",
                "Nora",
                web_clock(),
            )
            == []
        )

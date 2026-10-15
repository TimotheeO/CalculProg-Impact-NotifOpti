"""Fixtures déterministes et fictives. Pas de mot de passe, jeton utilisable ou envoi."""

import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.models import (
    Change,
    Contact,
    Dependency,
    Enrollment,
    Event,
    EventOrganizer,
    Invitation,
    InvitationResponse,
    InvitationWorkshop,
    Notification,
    NotificationChange,
    Participation,
    ParticipationRequest,
    User,
    Workshop,
)
from app.services import DomainError

SEED_DATE = datetime(2026, 10, 15, 10, tzinfo=timezone.utc)
EVENT_ID = "demo-rencontres"
SECOND_EVENT_ID = "demo-fabrique"
OWNER_ID = "demo-thomas"
PEOPLE = (
    ("alice", "Alice Martin", ["w1", "w2"]),
    ("sofia", "Sofia Bernard", ["w1"]),
    ("mehdi", "Mehdi Benali", ["w2"]),
    ("lina", "Lina Moreau", ["w3"]),
    ("nora", "Nora Petit", ["w4"]),
    ("hugo", "Hugo Laurent", ["w5"]),
    ("emma", "Emma Robert", ["w6"]),
    ("alex", "Alex Dubois", []),
    ("bruno", "Bruno Lefèvre", []),
    ("chloe", "Chloé Garcia", []),
)
WORKSHOPS = (
    ("w1", "Cuisine de saison", 12, 13, "La Cuisine", 12),
    ("w2", "Dégustation partagée", 13, 14, "La Grande Table", 18),
    ("w3", "Accords & échanges", 14, 15, "Le Salon", 18),
    ("w4", "Initiation à la poterie", 12, 13.5, "L’Atelier", 10),
    ("w5", "Vernissage des créations", 14, 15, "La Galerie", 20),
    ("w6", "Balade photographique", 12, 13, "Le Port", 12),
)
# Le diamant w1 → w2 → w3 et w1 → w3 vérifie les chemins multiples.
DEPENDENCIES = (("w1", "w2"), ("w2", "w3"), ("w1", "w3"), ("w4", "w5"))


def seed_demo(session) -> bool:
    """Une seule transaction, base vide obligatoire ; relance sans écrasement."""
    if session.get(Event, EVENT_ID) is not None:
        return False
    if session.scalar(select(func.count()).select_from(User)):
        raise DomainError(
            "Le jeu de démonstration nécessite une base vide ; aucune donnée n’a été modifiée"
        )

    accounts = [
        (OWNER_ID, "Thomas Mercier", "organizer"),
        ("demo-lea", "Léa Roux", "organizer"),
    ]
    accounts.extend((f"demo-{key}", name, "participant") for key, name, _ in PEOPLE)
    session.add_all(
        User(
            id=key,
            name=name,
            email=f"{key}@example.test",
            role=role,
            created_at=SEED_DATE,
        )
        for key, name, role in accounts
    )
    session.flush()
    session.add_all(
        Contact(
            id=f"contact-{key}",
            user_id=key,
            name=name,
            email=f"{key}@example.test",
            created_at=SEED_DATE,
        )
        for key, name, _ in accounts
    )
    session.add_all(
        [
            Event(
                id=EVENT_ID,
                slug="rencontres-creatives",
                owner_id=OWNER_ID,
                name="Les Rencontres créatives",
                description="Une après-midi pour cuisiner, façonner et échanger.",
                location="Les Ateliers du Port, Nice",
                starts_at=datetime(2026, 10, 22, 12, tzinfo=timezone.utc),
                ends_at=datetime(2026, 10, 22, 16, tzinfo=timezone.utc),
                status="published",
                participation_mode="invitation",
                created_at=SEED_DATE,
            ),
            Event(
                id=SECOND_EVENT_ID,
                slug="fabrique-du-vendredi",
                owner_id="demo-lea",
                name="La Fabrique du vendredi",
                description="Photographie et création collective au cœur de Nice.",
                location="La Fabrique, Nice",
                starts_at=datetime(2026, 10, 30, 13, tzinfo=timezone.utc),
                ends_at=datetime(2026, 10, 30, 17, tzinfo=timezone.utc),
                status="published",
                participation_mode="open",
                created_at=SEED_DATE,
            ),
        ]
    )
    session.flush()
    session.add(
        EventOrganizer(event_id=EVENT_ID, user_id="demo-lea", created_at=SEED_DATE)
    )
    day = datetime(2026, 10, 22, tzinfo=timezone.utc)
    session.add_all(
        Workshop(
            id=key,
            event_id=EVENT_ID,
            name=name,
            starts_at=day + timedelta(hours=start),
            ends_at=day + timedelta(hours=end),
            location=location,
            capacity=capacity,
            created_at=SEED_DATE,
        )
        for key, name, start, end, location, capacity in WORKSHOPS
    )
    session.add(
        Workshop(
            id="fabrique-photo",
            event_id=SECOND_EVENT_ID,
            name="Regards sur la ville",
            starts_at=datetime(2026, 10, 30, 13, tzinfo=timezone.utc),
            ends_at=datetime(2026, 10, 30, 15, tzinfo=timezone.utc),
            location="La Fabrique",
            capacity=None,
            created_at=SEED_DATE,
        )
    )
    session.add_all(
        Participation(event_id=EVENT_ID, user_id=f"demo-{key}", created_at=SEED_DATE)
        for key, _, _ in PEOPLE
        if key not in {"bruno", "chloe"}
    )
    session.add(
        Participation(
            event_id=SECOND_EVENT_ID,
            user_id="demo-alex",
            created_at=SEED_DATE + timedelta(seconds=31),
        )
    )
    session.flush()
    session.add_all(
        Dependency(
            event_id=EVENT_ID, base_workshop_id=base, dependent_workshop_id=dependent
        )
        for base, dependent in DEPENDENCIES
    )
    session.add_all(
        Enrollment(
            event_id=EVENT_ID,
            user_id=f"demo-{key}",
            workshop_id=workshop,
            created_at=SEED_DATE,
        )
        for key, _, ids in PEOPLE
        for workshop in ids
    )
    session.add(
        Enrollment(
            event_id=SECOND_EVENT_ID,
            user_id="demo-alex",
            workshop_id="fabrique-photo",
            created_at=SEED_DATE + timedelta(seconds=31),
        )
    )
    session.add(
        ParticipationRequest(
            event_id=SECOND_EVENT_ID, user_id="demo-chloe", created_at=SEED_DATE
        )
    )
    for key, name, _ in PEOPLE:
        status = (
            "declined"
            if key == "bruno"
            else "pending"
            if key == "chloe"
            else "accepted"
        )
        session.add(
            Invitation(
                id=f"invitation-{key}",
                event_id=EVENT_ID,
                email=f"demo-{key}@example.test",
                inviter_id=OWNER_ID,
                user_id=f"demo-{key}",
                status=status,
                created_at=SEED_DATE,
                # Empreinte seule, sans lien envoyé ni jeton utilisable fourni.
                token_digest=hashlib.sha256(
                    f"fixture-unusable-{key}".encode()
                ).hexdigest(),
                expires_at=datetime(2026, 10, 21, 12, tzinfo=timezone.utc),
            )
        )
    session.flush()
    session.add_all(
        InvitationResponse(
            id=f"response-{key}",
            event_id=EVENT_ID,
            invitation_id=f"invitation-{key}",
            actor_id=f"demo-{key}",
            response="declined" if key == "bruno" else "accepted",
            created_at=SEED_DATE,
        )
        for key, _, _ in PEOPLE
        if key != "chloe"
    )
    session.add(
        InvitationWorkshop(
            event_id=EVENT_ID, invitation_id="invitation-chloe", workshop_id="w1"
        )
    )

    # Historique fictif : deux corrections puis annulation, sans envoyer quoi que ce soit.
    session.add_all(
        [
            Change(
                id="seed-change-1",
                event_id=EVENT_ID,
                workshop_id="w4",
                actor_id=OWNER_ID,
                field="location",
                old_value="Salle A",
                new_value="Salle B",
                created_at=SEED_DATE,
            ),
            Change(
                id="seed-change-2",
                event_id=EVENT_ID,
                workshop_id="w4",
                actor_id=OWNER_ID,
                field="location",
                old_value="Salle B",
                new_value="L’Atelier",
                created_at=SEED_DATE + timedelta(seconds=20),
            ),
            Change(
                id="seed-cancellation",
                event_id=SECOND_EVENT_ID,
                workshop_id=None,
                actor_id="demo-lea",
                field="status",
                old_value="published",
                new_value="cancelled",
                created_at=SEED_DATE,
            ),
            Change(
                id="seed-reactivation",
                event_id=SECOND_EVENT_ID,
                workshop_id=None,
                actor_id="demo-lea",
                field="status",
                old_value="cancelled",
                new_value="published",
                created_at=SEED_DATE + timedelta(seconds=30),
            ),
        ]
    )
    session.add(
        Notification(
            id="seed-notification",
            event_id=EVENT_ID,
            user_id="demo-nora",
            message="Exemple fictif : Poterie se tient dans L’Atelier. Aucun e-mail envoyé.",
            urgency=2,
            status="skipped",
            created_at=SEED_DATE + timedelta(seconds=60),
        )
    )
    session.flush()
    session.add_all(
        NotificationChange(
            event_id=EVENT_ID, notification_id="seed-notification", change_id=key
        )
        for key in ("seed-change-1", "seed-change-2")
    )
    session.flush()
    return True

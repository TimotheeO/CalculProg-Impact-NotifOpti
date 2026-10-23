"""Préparation locale de données fictives, sans écrasement ni envoi d’e-mail."""

import argparse
import html
import json
import secrets
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from app.auth.security import PASSWORDS, digest
from app.auth.services import audit
from app.config import ROOT
from app.database import Database
from app.events.services import PARIS
from app.models import (
    Change,
    Contact,
    Event,
    Invitation,
    InvitationWorkshop,
    Notification,
    NotificationChange,
    OrganizerInvitation,
    User,
    Workshop,
    utc_now,
)
from app.operations import log_action
from app.seeds import EVENT_ID, OWNER_ID, SECOND_EVENT_ID, seed_demo

DEMO_PASSWORD = "Demo-ImpactFlow-2026!"  # Comptes fictifs locaux uniquement.
ADMIN_ID = "demo-admin"
MARKER = "impactflow-demo-prete-v1"
DEFAULT_DIRECTORY = ROOT / "var" / "demo-prete"
BASE_URL = "http://127.0.0.1:8000"


def _local_day(value, date):
    return datetime.combine(date, value.astimezone(PARIS).time(), PARIS).astimezone(
        timezone.utc
    )


def populate(session, now):
    """Adaptation du seed historique dans une nouvelle base exclusivement fictive."""
    seed_demo(session)
    # Départ sans envoi ni journal de changement inventé : la démo produira les vrais.
    for model in (NotificationChange, Notification, Change):
        session.execute(delete(model))
    today = now.astimezone(PARIS).date()
    day = today + timedelta(days=(3 - today.weekday()) % 7 or 7)
    for event_id, date in ((EVENT_ID, day), (SECOND_EVENT_ID, day + timedelta(days=1))):
        event = session.get(Event, event_id)
        # Ne pas déclencher d’autoflush entre les deux extrémités du déplacement.
        event.starts_at, event.ends_at = (
            _local_day(event.starts_at, date),
            _local_day(event.ends_at, date),
        )
        for workshop in session.scalars(
            select(Workshop).where(Workshop.event_id == event_id)
        ):
            workshop.starts_at, workshop.ends_at = (
                _local_day(workshop.starts_at, date),
                _local_day(workshop.ends_at, date),
            )
    session.add(
        User(
            id=ADMIN_ID,
            email="admin.demo@example.test",
            name="Admin démonstration",
            role="super_admin",
            created_at=now,
        )
    )
    session.flush()
    session.add(
        Contact(
            id="contact-demo-admin",
            user_id=ADMIN_ID,
            name="Admin démonstration",
            email="admin.demo@example.test",
            created_at=now,
        )
    )
    accounts = list(session.scalars(select(User).order_by(User.role, User.name)))
    for user in accounts:
        user.password_hash = PASSWORDS.hash(DEMO_PASSWORD)
    audit(session, "bootstrap_admin", now, actor_id=ADMIN_ID, target_user_id=ADMIN_ID)
    draft_day = day + timedelta(days=7)
    session.add(
        Event(
            id="demo-brouillon",
            slug="festival-savoir-faire-brouillon",
            owner_id=OWNER_ID,
            name="Festival des savoir-faire",
            description="Brouillon prêt pour montrer la création d’ateliers et la publication.",
            location="Maison des associations, Nice",
            starts_at=datetime.combine(draft_day, time(14), PARIS).astimezone(
                timezone.utc
            ),
            ends_at=datetime.combine(draft_day, time(18), PARIS).astimezone(
                timezone.utc
            ),
            status="draft",
            participation_mode="open",
            created_at=now,
        )
    )
    expires = now + timedelta(hours=48)
    links = []
    chloe = session.get(Invitation, "invitation-chloe")
    chloe.invitee_name = "Chloé Garcia"
    token = secrets.token_urlsafe(32)
    chloe.token_digest = digest(token)
    chloe.expires_at = expires
    links.append(
        {
            "name": "Chloé Garcia — compte existant",
            "email": chloe.email,
            "url": f"{BASE_URL}/invitations#invitation={token}",
        }
    )
    for key, name in (
        ("camille", "Camille Durand"),
        ("julie", "Julie Simon"),
        ("noe", "Noé Laurent"),
    ):
        email = f"{key}@example.test"
        session.add(
            Contact(id=f"contact-demo-{key}", name=name, email=email, created_at=now)
        )
        if key == "noe":
            continue  # Contact disponible pour un vrai envoi Mailpit depuis le site.
        token = secrets.token_urlsafe(32)
        invitation = Invitation(
            id=f"invitation-demo-{key}",
            event_id=EVENT_ID,
            email=email,
            inviter_id=OWNER_ID,
            invitee_name=name,
            token_digest=digest(token),
            purpose="invitation",
            status="pending",
            created_at=now,
            expires_at=expires,
        )
        session.add(invitation)
        session.flush()
        session.add(
            InvitationWorkshop(
                event_id=EVENT_ID, invitation_id=invitation.id, workshop_id="w1"
            )
        )
        links.append(
            {
                "name": name + " — création ou refus sans compte",
                "email": email,
                "url": f"{BASE_URL}/invitations#invitation={token}",
            }
        )
    token = secrets.token_urlsafe(32)
    session.add(
        OrganizerInvitation(
            id="demo-organizer-invitation",
            email="organisateur.invite@example.test",
            inviter_id=ADMIN_ID,
            token_digest=digest(token),
            status="pending",
            created_at=now,
            expires_at=expires,
        )
    )
    links.append(
        {
            "name": "Nouvel organisateur",
            "email": "organisateur.invite@example.test",
            "url": f"{BASE_URL}/activation-organisateur#invitation={token}",
        }
    )
    log_action(
        session,
        EVENT_ID,
        OWNER_ID,
        "demo_prepared",
        now,
        detail={
            "description": "Données fictives préparées pour la démonstration. Aucun e-mail envoyé."
        },
    )
    session.flush()
    return {
        "marker": MARKER,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "event_date": day.isoformat(),
        "accounts": [
            {"name": u.name, "email": u.email, "role": u.role} for u in accounts
        ],
        "invitations": links,
    }


def _write_access(directory, report):
    rows = "\n".join(
        f"| {u['name']} | {u['email']} | {u['role']} |" for u in report["accounts"]
    )
    (directory / "ACCES_DEMO.md").write_text(
        f"""# Accès à la base de démonstration locale

Application : {BASE_URL} · mot de passe commun : `{DEMO_PASSWORD}`.
Comptes fictifs réservés à cette base locale, jamais à utiliser en production.
Préparée le {report["created_at"]}. Rencontres prévues le {report["event_date"]}.

| Nom | E-mail | Rôle |
|---|---|---|
{rows}

Ouvrir `invitations.html` dans un autre profil ou une fenêtre privée pour les
liens préparés, valables jusqu’au {report["expires_at"]}.
Ces liens n’ont pas été envoyés : aucun e-mail préchargé n’est présenté comme reçu.
Les vrais essais depuis l’application utilisent Mailpit.

Voir docs/DEMO.md pour les manipulations et résultats attendus.
""",
        encoding="utf-8",
    )
    items = "\n".join(
        f"<li><strong>{html.escape(link['name'])}</strong> · {html.escape(link['email'])}<br>"
        f'<a href="{html.escape(link["url"], quote=True)}">Ouvrir cette invitation</a></li>'
        for link in report["invitations"]
    )
    (directory / "invitations.html").write_text(
        f"""<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Invitations préparées — ImpactFlow</title><h1>Invitations de démonstration</h1>
<p>Ouvrir dans une fenêtre privée ou un profil distinct. Application sur {BASE_URL}.</p>
<p>Liens fictifs préparés, sans envoi d’e-mail. Usage unique, expiration : {html.escape(report["expires_at"])}.</p>
<ul>{items}</ul><p>Camille et Julie n’ont pas encore de compte ; Chloé possède un compte mais aucune participation aux Rencontres.</p>
<p>Pour montrer un vrai envoi SMTP : inviter Noé depuis le carnet, puis ouvrir Mailpit.</p></html>""",
        encoding="utf-8",
    )
    (directory / "preparation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for file in directory.iterdir():
        if file.is_file():
            file.chmod(0o600)


def prepare(directory=DEFAULT_DIRECTORY, *, now=None):
    directory = Path(directory).resolve()
    if directory.exists():
        marker = directory / "preparation.json"
        if not marker.is_file() or not (directory / "impactflow.sqlite3").is_file():
            raise ValueError(
                "Le dossier existe sans base de démonstration reconnue. Choisissez un nouveau dossier ; aucune donnée écrasée."
            )
        report = json.loads(marker.read_text(encoding="utf-8"))
        if report.get("marker") != MARKER:
            raise ValueError(
                "Ce dossier ne correspond pas à la démonstration attendue. Aucune donnée modifiée."
            )
        return directory, False
    directory.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix=".impactflow-demo-", dir=directory.parent
    ) as staging:
        temporary = Path(staging) / "prepared"
        temporary.mkdir(mode=0o700)
        database = Database(f"sqlite:///{temporary / 'impactflow.sqlite3'}")
        try:
            database.initialize()
            with database.transaction(immediate=True) as session:
                report = populate(session, now or utc_now())
            database.check_schema()
        finally:
            database.close()
        _write_access(temporary, report)
        # Publication seulement quand base ET accès sont prêts. Pas de remplacement.
        temporary.rename(directory)
    return directory, True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Préparer une base locale prête à présenter, sans écraser les bases existantes."
    )
    parser.add_argument(
        "--directory",
        type=Path,
        default=DEFAULT_DIRECTORY,
        help="Nouveau dossier de sortie ; défaut : var/demo-prete",
    )
    args = parser.parse_args(argv)
    try:
        directory, created = prepare(args.directory)
    except (OSError, ValueError, RuntimeError, SQLAlchemyError):
        print(
            "Préparation impossible : vérifier le dossier et les migrations, ou choisir un nouveau dossier. Aucune base existante n’a été remplacée.",
            file=sys.stderr,
        )
        return 2
    print(
        "Base de démonstration préparée."
        if created
        else "Base déjà préparée : données et modifications conservées."
    )
    print(f"Base : {directory / 'impactflow.sqlite3'}")
    print(f"Comptes : {directory / 'ACCES_DEMO.md'}")
    print(f"Liens personnels : {directory / 'invitations.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

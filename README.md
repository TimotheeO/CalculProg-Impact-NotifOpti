# ImpactFlow — propagation d’impact et notifications optimisées

Projet individuel EPITECH Simulated : organiser des événements à plusieurs
ateliers, calculer les conséquences d’un changement et prévenir uniquement les
personnes concernées, avec regroupement, priorité et limite de débit.

**Documentation : ce README pour installer/comprendre/tester le projet et
[DEMO.md](docs/DEMO.md) pour préparer et refaire la démonstration.** Ces deux
documents sont mis à jour au fil du développement, sans autres guides séparés.

## Installation

Python **3.12**, environnement vérifié sous Linux, depuis la racine du dépôt :

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

Les versions directes/transitives sont fixées dans requirements.txt et constraints.txt.

## Démarrer avec une base remplie

Deux terminaux, depuis le dépôt :

```bash
# Terminal 1 : SMTP de test local
./scripts/mailpit.sh
```

```bash
# Terminal 2 : nouveau dossier pour retrouver les données initiales
DEMO_DIRECTORY=var/demo-seance-01 ./scripts/run_prepared_demo.sh
```

Application : <http://127.0.0.1:8000> ; Mailpit : <http://127.0.0.1:8025>.
Le script conserve une base existante ; changer de dossier crée une nouvelle copie.
Les comptes fictifs et le scénario sont dans [DEMO.md](docs/DEMO.md).
Arrêter l’ancien serveur avant de relancer sur le même port.

## Démarrer sur une base vide

```bash
cp .env.example .env
venv/bin/python -m app.cli init-db
venv/bin/python -m app.cli create-super-admin --email admin@example.test --name "Admin local"
venv/bin/python -m uvicorn app.web:create_app --factory --host 127.0.0.1 --port 8000
```

Le mot de passe admin est saisi localement, deux fois, sans affichage ; aucune
valeur par défaut en base vide. Le serveur exige les migrations appliquées.
`seed-demo` charge des fixtures sans mots de passe utilisables ; `app.demo`
prépare au contraire une base de présentation avec comptes actifs.

## Fonctionnement

- Trois espaces protégés : super-admin, organisateur et participant. Un événement
  a un responsable principal et peut avoir des coorganisateurs autorisés.
- Carnet commun aux organisateurs, sans accès aux événements privés d’autrui.
  Catalogue pour les événements ouverts ; invitations personnelles également possibles.
- L’invité peut créer son compte puis choisir ses ateliers. Consulter le lien
  ne confirme rien. Une demande publique exige vérification de l’adresse et approbation.
- Capacité vérifiée transactionnellement ; chevauchements d’inscriptions refusés,
  y compris entre événements ; créneaux adjacents autorisés.
- **A → B signifie que B attend la fin de A.** Une salle/description reste locale.
  Un retard décale B uniquement si sa marge est insuffisante, en conservant sa durée.
  Exemple : A finit 30 min plus tard ; B adjacent décale de 30 min, B avec 15 min
  de marge de 15 min, B avec une heure de marge reste inchangé et ne crée pas de message.
- Annuler un atelier annule réellement ses dépendants, sans effacer inscriptions
  ou historique. Avancer un atelier ne réavance pas automatiquement les suivants.
- L’aperçu présente le plan avant confirmation atomique ; un dépassement de
  l’événement refuse toute l’opération. Programme ou liens modifiés entre-temps :
  formulaire refusé, nouvel aperçu requis.
- Un changement global vise tous les confirmés actifs, même sans atelier.
  Reporter la date déplace tout le programme ; les messages gardent les dates finales.
- Fenêtre fixe de 60 s par personne/événement, non repoussée : valeurs finales
  regroupées, retour à la valeur initiale sans message pour ce champ, historique conservé.
- Priorité annulation puis horaire puis information mineure ; limiteur commun
  aux e-mails. Une tentative, états succès/échec/incertain distincts, pas de réessai automatique.
- Journal, économies sur groupes fermés, boîte participant et lu/non lu persistants.
  Calendrier français, cadran 24 h, affichage Paris, stockage UTC, thèmes bordeaux clair/nuit.

## Architecture et choix

| Partie | Responsabilité |
|---|---|
| app/auth | Sessions, rôles, CSRF et invitations organisateur |
| app/events, app/workshops | Événements, programme, dépendances et plan de cascade |
| app/participation | Carnet, invitations, demandes et inscriptions |
| app/impact.py, app/notification_groups.py | Ciblage réel, contenu final et fenêtres |
| app/worker.py, app/mailer.py, app/journal.py | Ordonnancement, transports et suivi |
| app/models.py, app/migrations | Modèles SQL et migrations Alembic 0001 à 0003 |
| app/templates, app/static | Jinja2, styles et JavaScript partagé |
| src/, cli.py | Moteur initial indépendant et simulation CLI |
| tests/, scripts/ | Vérifications et lancement reproductible |

| Choix | Raison et alternative |
|---|---|
| FastAPI/Jinja2 | Stack du plan, formulaires rendus côté serveur ; Django aurait apporté un admin intégré, une SPA ajouterait un frontend séparé |
| SQLite/SQLAlchemy/Alembic | Transactions locales sans serveur séparé, schéma évolutif ; PostgreSQL à réexaminer pour plusieurs instances |
| BFS puis ordre topologique | BFS trouve les candidats ; le tri traite tous les parents avant leur enfant. DFS trouve aussi l’accessibilité |
| Fenêtre fixe | Les changements continus ne repoussent pas l’envoi, contrairement au debouncing |
| heapq et fenêtre glissante | Priorité et plafond sur chaque période ; un token bucket peut autoriser des rafales |
| Worker local | Un processus pour le périmètre local ; Celery/Redis ajouteraient coordination et exploitation |
| Cache limité au recalcul | Réutilise les cibles dans une transaction, puis les relit avant la tentative suivante ; un cache global risquerait des cibles périmées |

Les alternatives sont comparées qualitativement ; pas de benchmark de charge revendiqué.
Argon2id, cookies HttpOnly/SameSite, empreintes des jetons en base, droits relus
sous transaction, clés étrangères et rollback protègent les mutations.
Les maquettes statiques initiales restent dans docs/maquettes ; leurs anciennes
règles ne représentent pas l’application actuelle.

## Configuration et e-mails

`.env` reste local ; les variables exportées prévalent. Principaux réglages :

| Variable | Défaut / rôle |
|---|---|
| DATABASE_URL | SQLite absolu vers var/impactflow.sqlite3 ; mémoire réservée aux tests |
| APP_ENV / APP_BASE_URL | development / http://127.0.0.1:8000 ; HTTPS exigé en production |
| MAILER_BACKEND | memory, mailpit ou brevo |
| SMTP_HOST / SMTP_PORT / MAILPIT_UI_URL | 127.0.0.1 / 1025 / http://127.0.0.1:8025 |
| BATCH_WINDOW_SECONDS | 60 ; non repoussée par les changements suivants |
| SEND_MAX_PER_PERIOD / SEND_PERIOD_SECONDS | 2 / 1 ; scripts de démo : 1 / 1 |
| SEND_DAILY_LIMIT | 300 tentatives/jour UTC |
| APP_WORKER_ENABLED | Actif hors test par défaut |
| SESSION_TTL_SECONDS / INVITATION_TTL_HOURS | 28800 / 48 |

**Un seul processus Uvicorn**, protégé par un verrou Linux par base.
`init-db` applique les migrations sans réinitialisation ; sauvegarder une base
utilisée avant migration. Ne pas contourner un schéma incompatible en recréant les tables.

memory simule les envois. Mailpit capture un véritable échange SMTP local, sans
compte ni relais externe ; aucune réception Gmail/Outlook n’est démontrée.
Si Mailpit est absent, son script affiche les commandes d’installation ; il peut
aussi recevoir MAILPIT_BINARY. Installation locale avec GitHub CLI connecté :

```bash
mkdir -p var/tools/mailpit-v1.31.6
gh release download v1.31.6 --repo axllent/mailpit --pattern mailpit-linux-amd64.tar.gz --dir var/tools/mailpit-v1.31.6
tar -xzf var/tools/mailpit-v1.31.6/mailpit-linux-amd64.tar.gz -C var/tools/mailpit-v1.31.6 mailpit
```

Brevo est préparé mais aucun compte/expéditeur n’est validé. Pour l’activer plus tard,
vérifier une offre gratuite et un expéditeur, configurer MAIL_FROM_EMAIL,
MAIL_FROM_NAME et BREVO_API_KEY uniquement en .env. Les domaines fictifs sont bloqués
avant appel externe. Un accusé fournisseur ne prouve pas la réception.

## Vérifier

```bash
venv/bin/python -m pytest -q -W error
venv/bin/ruff check .
venv/bin/python -m pip check
bash -n scripts/mailpit.sh scripts/run_demo.sh scripts/run_prepared_demo.sh
```

Dernière suite fonctionnelle complète locale, **23 octobre 2026 : 409 tests réussis**,
dont les 92 historiques. Tests sur bases temporaires : droits/CSRF, migrations,
invitations, concurrence, marges/cascades, fusion, quotas, transport et erreurs.
Ruff, dépendances et 37 templates Jinja vérifiés. Les contrôles Node du script
d’invitation utilisent DOM/transport simulés ; les rapports datés restent dans docs/preuves.
La nouvelle CI distante doit être vérifiée après push.

La revue a corrigé les dates après report global, les doublons à l’échéance,
la relecture des sessions admin et les envois aux comptes désactivés. Sur un
recalcul isolé identique de quatre groupes/cinq champs : **113 → 56 instructions SQL** ;
c’est une mesure de requêtes, pas de temps ni de tenue en charge.
Pour vérifier à la main, suivre [DEMO.md](docs/DEMO.md), y compris ses cas d’erreur.

## CLI du moteur

```bash
venv/bin/python cli.py --list
venv/bin/python cli.py
venv/bin/python cli.py --change 0 w1 horaire 15h --change 5 w1 horaire 16h
```

`--change HEURE ATELIER CHAMP VALEUR` est répétable ; temps en secondes simulées.
Options : window 30 s, limit 2, period 1 s, data data/sample_event.json, rows 15
par défaut. Le graphe CLI est générique ; le site ajoute les règles métier de marges.

## État et suite du projet

Version locale **0.1.0**, cycle 1 relié : accès, événements/ateliers, invitations,
aperçu, worker SMTP local, journal et boîte participant. Travail individuel les
jeudis/vendredis ; environ quatre jours déclarés pour le cycle 1, non chronométrés.
Soutenances confirmées les 23 octobre et 6 novembre 2026 ; dépôt Hub effectué.

Restent au cycle 2 : compte participant/récupération du mot de passe, retraits
et reconfirmations complets, annulations avant échéance, reprise/relances abouties,
graphe/tableau de bord, recherche/CSV/archivage et recette finale. Hébergement
strictement gratuit si compatible ; livraison actuellement locale.

Les bases, secrets, liens générés, binaires et caches restent dans les fichiers
ignorés. VERSION prépare une livraison ; aucun tag, release ou résultat de CI
distante n’en est déduit. L’étudiant effectue lui-même le push.
Pour les prochaines tâches : expliquer les choix/alternatives, indiquer les tests
manuels et mettre à jour uniquement ce README et docs/DEMO.md.

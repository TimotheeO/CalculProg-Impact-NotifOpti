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
- Le super-admin utilise un compte de gestion uniquement : aucune demande,
  invitation participante ou inscription à un atelier. Pour participer, il lui
  faut un compte personnel distinct ; aucun compte supplémentaire n’est créé automatiquement.
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
- Annulations prêtes au prochain passage du worker, sans attendre la fenêtre ;
  informations d’autres ateliers conservées jusqu’à leur échéance.
- Mot de passe oublié : réponse neutre, lien de 30 minutes à usage unique,
  invalidation des anciennes demandes et sessions après changement.
- Espace personnel : invitations en attente, planning chronologique, places
  restantes, désinscription et retrait par l’organisateur. Réactiver un atelier
  propose explicitement la réactivation des dépendants ; aucune place ancienne
  n’est réservée avant une nouvelle confirmation.
- Outbox durable : groupes et premiers envois non commencés repris après arrêt.
  Une tentative interrompue reste incertaine. Relance manuelle après échec,
  vérification du transport obligatoire pour un résultat incertain ; auteur et
  historique des tentatives conservés.
- Graphe SVG interactif, compteurs depuis la base, filtres et exports CSV
  UTF-8 avec neutralisation des formules, archivage en lecture seule.
- Journal, économies sur groupes fermés, boîte participant et lu/non lu persistants.
  Calendrier français, cadran 24 h, affichage Paris, stockage UTC, thèmes bordeaux clair/nuit.

## Architecture et choix

| Partie | Responsabilité |
|---|---|
| app/auth | Sessions, rôles, CSRF, invitations organisateur et récupération du compte |
| app/events, app/workshops | Événements, programme, dépendances et plan de cascade |
| app/participation | Carnet, invitations, demandes et inscriptions |
| app/impact.py, app/notification_groups.py | Ciblage réel, contenu final et fenêtres |
| app/worker.py, app/mailer.py, app/deliveries.py, app/journal.py | Outbox, tentatives, transports, relances et suivi |
| app/dashboard.py, app/events/management.py | Graphe, compteurs, filtres, CSV et états de clôture |
| app/backup.py, app/release.py | Sauvegarde/restauration et livraison locale sans publication |
| app/models.py, app/migrations | Modèles SQL et migrations Alembic 0001 à 0004 |
| app/templates, app/static | Jinja2, styles et JavaScript partagé |
| src/, cli.py | Moteur initial indépendant et simulation CLI |
| tests/, scripts/ | Vérifications et lancement reproductible |

| Choix | Raison et alternative |
|---|---|
| Compte super-admin réservé à la gestion | Sépare l’administration des inscriptions personnelles ; un compte cumulant tous les droits mélangerait ces usages. Les organisateurs peuvent toujours participer |
| FastAPI/Jinja2 | Stack du plan, formulaires rendus côté serveur ; Django aurait apporté un admin intégré, une SPA ajouterait un frontend séparé |
| SQLite/SQLAlchemy/Alembic | Transactions locales sans serveur séparé, schéma évolutif ; PostgreSQL à réexaminer pour plusieurs instances |
| BFS puis ordre topologique | BFS trouve les candidats ; le tri traite tous les parents avant leur enfant. DFS trouve aussi l’accessibilité |
| Fenêtre fixe | Les changements continus ne repoussent pas l’envoi, contrairement au debouncing |
| heapq et fenêtre glissante | Priorité et plafond sur chaque période ; un token bucket peut autoriser des rafales |
| Worker local | Un processus pour le périmètre local ; Celery/Redis ajouteraient coordination et exploitation |
| SVG natif | Interactions au clavier et sur mobile sans bibliothèque graphique lourde ; l’édition reste dans les formulaires |
| Jetons de lien hachés | Après perte mémoire, renouvellement du jeton d’un envoi non commencé ; un corps durable contenant le secret en clair aurait accru son exposition |
| Historique des tentatives | Chaque relance garde son auteur et son résultat ; remplacer l’erreur précédente aurait perdu la traçabilité |
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
venv/bin/python -m coverage run --source=app,src -m pytest -q -W error
venv/bin/python -m coverage report --fail-under=85
venv/bin/ruff check .
venv/bin/python -m pip check
bash -n scripts/mailpit.sh scripts/run_demo.sh scripts/run_prepared_demo.sh
```

Validation du cycle 2 : **30 octobre 2026 : 463 tests réussis, 90 % des lignes Python couvertes**. Les 92 tests historiques du moteur
restent inclus et distincts des tests web. Vérifications sur bases temporaires :
droits/CSRF, migrations d’une base peuplée, récupération, invitations, capacité,
conflits, retraits/reconfirmation, annulations, reprise, relances et archivage.
Le test de débit traite 105 messages simulés avec redémarrage au milieu, sans
appel SMTP externe. Ruff et dépendances vérifiés ; la CI distante attend le push.
La [preuve structurée](docs/preuves/cycle-2/validation.json) rassemble les contrôles
navigateur, SMTP, vidéo et livraison. La couverture porte sur les lignes Python de `app` et `src`, pas sur une mesure
exhaustive de l’ergonomie, du JavaScript ou des cas possibles.

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

Version locale **1.0.0**, cycles 1 et 2 intégrés : comptes, événements/ateliers,
invitations, inscriptions, aperçu, annulations prioritaires, reprise durable,
relances manuelles, graphe, exports et archives. Travail individuel les
jeudis/vendredis ; environ quatre jours déclarés pour le cycle 1, non chronométrés.
Soutenances confirmées les 23 octobre et 6 novembre 2026 ; dépôt Hub effectué.

Le périmètre des neuf tâches C2-01 à C2-09 est suivi ci-dessous.
Cycle 2 : **environ 3,5 jours-homme déclarés** par l’étudiant, travail hors campus
compris, contre **4 jours-homme estimés**. Ce temps n’est pas chronométré et
reste à ajuster si du travail complémentaire est réalisé. La répétition humaine
reste à faire ; aucune estimation n’est présentée comme une mesure.
Livraison locale ; ni hébergement ni réception dans une boîte externe validés.

Les bases, secrets, liens générés, binaires et caches restent dans les fichiers
ignorés. VERSION prépare une livraison ; aucun tag, release ou résultat de CI
distante n’en est déduit. L’étudiant effectue lui-même le push.
Pour les prochaines tâches : expliquer les choix/alternatives, indiquer les tests
manuels et mettre à jour uniquement ce README et docs/DEMO.md.

## Cycle 2 — périmètre et validation

| Tâche GitHub | Livraison locale |
|---|---|
| [C2-01 · compte participant](https://github.com/TimotheeO/CalculProg-Impact-NotifOpti/issues/19) | Invitations dans l’espace, planning, récupération et sessions invalidées |
| [C2-02 · inscriptions](https://github.com/TimotheeO/CalculProg-Impact-NotifOpti/issues/20) | Places restantes, retrait, capacité/conflits, reconfirmation et recalcul des cibles |
| [C2-03 · annulations](https://github.com/TimotheeO/CalculProg-Impact-NotifOpti/issues/21) | Groupe urgent distinct ; contenus caducs retirés, autres ateliers à leur échéance |
| [C2-04 · reprise](https://github.com/TimotheeO/CalculProg-Impact-NotifOpti/issues/22) | Échéances conservées, travail non commencé retrouvé, tentative interrompue incertaine |
| [C2-05 · relances](https://github.com/TimotheeO/CalculProg-Impact-NotifOpti/issues/23) | Relance autorisée et tracée, double clic idempotent, débit commun |
| [C2-06 · interface](https://github.com/TimotheeO/CalculProg-Impact-NotifOpti/issues/24) | Rôles distincts, thèmes mémorisés, SVG interactif, aperçu réel et compteurs |
| [C2-07 · clôture](https://github.com/TimotheeO/CalculProg-Impact-NotifOpti/issues/25) | Filtres, CSV protégé, annulation collective, réactivation et archive |
| [C2-08 · hébergement](https://github.com/TimotheeO/CalculProg-Impact-NotifOpti/issues/26) | Étude ci-dessous ; voie locale retenue, aucune mise en ligne revendiquée |
| [C2-09 · recette finale](https://github.com/TimotheeO/CalculProg-Impact-NotifOpti/issues/27) | Tests, guide unique, support et archive locale ; bilan de 3,5 j-h déclarés ; répétition humaine, push/CI et publication finale à valider |

La fenêtre normale reste fixe : une modification continue ne repousse pas sa
fin. Une annulation utilise un groupe urgent séparé. Les anciennes informations
du même atelier sont écartées, mais celles d’un autre atelier attendent leur
échéance initiale. Un e-mail déjà transmis ne peut pas être rappelé.

Une notification finalisée reste visible dans le site si l’e-mail échoue.
`mail_attempts` conserve heure, auteur de relance, numéro, résultat, erreur et
référence transport. Après un arrêt pendant une tentative : état incertain,
sans nouvel envoi automatique. Une non-réception ne prouve pas la non-acceptation :
vérifier le journal du transport avant d’autoriser une relance incertaine.

Brevo reçoit une clé d’idempotence stable par envoi/révision. Sa documentation
annonce une [durée de 15 minutes](https://developers.brevo.com/changelog/2021/11/10) ;
cette protection ne constitue pas une garantie illimitée. SMTP Mailpit n’offre
pas cette garantie ; l’application réserve chaque tentative sous transaction.
Les secrets de liens restent hachés. Un lien non envoyé peut être renouvelé
lors de la reconstruction d’un envoi, sans prolonger son expiration.

## Sauvegarder et restaurer

La copie utilise l’API de sauvegarde SQLite, cohérente même en mode WAL,
contrôle l’intégrité et refuse tout écrasement. Exemples depuis le dépôt :

```bash
venv/bin/python -m app.backup sauvegarder var/demo-cycle2-01/impactflow.sqlite3 var/sauvegardes/defense-01.sqlite3
venv/bin/python -m app.backup restaurer var/sauvegardes/defense-01.sqlite3 var/restauration-01/impactflow.sqlite3
# Après arrêt de l’ancien serveur, avec Mailpit démarré :
DATABASE_URL="sqlite:///$PWD/var/restauration-01/impactflow.sqlite3" ./scripts/run_demo.sh
```

Choisir de nouveaux noms à chaque copie. Le dernier serveur doit utiliser
explicitement le fichier restauré. `init-db` applique les migrations sans
réinitialiser les comptes ni les événements. Les données de récupération et les nouvelles tentatives d’envoi empêchent un
retour de migration. Pour revenir à une ancienne version, restaurer une sauvegarde
compatible. Les fichiers de sauvegarde contiennent des données
personnelles et ne doivent pas entrer dans Git ou dans la livraison publique.

## Hébergement gratuit — décision du 29 octobre 2026

Aucun compte hébergeur ni Brevo n’a été créé par l’étudiant. Aucune offre n’a
été validée de bout en bout avec stockage durable, worker et e-mail externe.
La livraison retenue est donc locale, sans achat ni abonnement. Cette décision
ne signifie pas qu’aucune offre compatible ne peut exister.

| Offre examinée | Limites pertinentes et décision |
|---|---|
| [Render gratuit](https://render.com/docs/free) | Disque éphémère et pas de disque persistant gratuit ; SQLite serait perdu au redémarrage. Sommeil après 15 minutes ; PostgreSQL gratuit expire après 30 jours. Non retenu pour cette architecture SQLite |
| [PythonAnywhere gratuit](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/) | 512 Mio, une application et expiration mensuelle. ASGI reste une piste à valider ; [API Brevo autorisée](https://eu.pythonanywhere.com/whitelist/) mais proxy, worker, déploiement et réception non testés. Aucun compte disponible, piste non validée |
| [Fly.io](https://fly.io/docs/about/pricing/) | Machines et volumes facturés à l’usage ; pas de validation d’une exploitation durable strictement gratuite. Non retenu |

Pour réexaminer un hébergement : compte gratuit, HTTPS, stockage persistant,
API d’envoi accessible, un seul worker, liens sur la bonne origine, sauvegarde
et preuve après redémarrage. Ne jamais engager de plan payant automatiquement.

## Préparer la livraison et la soutenance

```bash
venv/bin/python -m app.release --directory var/livraison-1.0.0-01 --video docs/preuves/demo-secours.webm
```

Le dossier neuf reçoit l’archive ZIP, `soutenance.html` et un manifeste avec
empreintes SHA-256, version, commit de base et indication des modifications
locales. Le ZIP contient les sources nécessaires et les deux guides, sans base,
`.env`, environnement virtuel ou secrets générés. La vidéo est facultative pour
la commande ; celle de la recette continue conserve la fenêtre réelle de 60 secondes
et le débit de 1 tentative/s. C’est une capture locale de comptes fictifs, pas une
preuve de répétition humaine ou de réception Gmail. Le support HTML peut être
ouvert dans le navigateur ou imprimé. Aucun tag, push ou release GitHub n’est
créé par cette commande. L’étudiant conserve la publication après revue.

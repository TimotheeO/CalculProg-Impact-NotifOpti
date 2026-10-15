# ImpactFlow — fondation web C1-02

Pour vérifier l’étape avec des résultats attendus à chaque action, suivre
[la recette manuelle C1-02](RECETTE_MANUELLE.md#c1-02--application-base-persistante-et-graphe).
Pour comprendre les raisons et alternatives, consulter le
[journal des choix techniques](DECISIONS_TECHNIQUES.md). Ce guide détaille
l’architecture et les commandes ; la recette sert au contrôle par l’étudiant.

## Démarrer

Depuis la racine du dépôt, avec Python 3.12 :

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
python -m app.cli init-db
python -m app.cli seed-demo
python -m uvicorn app.main:app --reload
```

Ouvrir <http://127.0.0.1:8000>. Le catalogue affiche les événements **publiés et
ouverts** depuis la base. L’événement privé des Rencontres créatives n’y apparaît
pas. Le détail public ne contient ni contacts, ni participants, ni historique.
Il n’y a pas encore de connexion ou d’interface de modification ; ces parcours
seront livrés dans les tâches suivantes. Les maquettes C1-01 restent indépendantes.

L’initialisation applique les migrations existantes sans supprimer de données.
Le serveur exige un schéma à jour au démarrage et ne lance aucune migration
implicitement. `seed-demo` est facultatif : une base vide affiche un catalogue
vide compréhensible. Le seed n’ouvre aucun accès utilisable, n’envoie rien et
n’ajoute aucun mot de passe de démonstration.

## Configuration

Le fichier `.env.example` peut être copié en `.env`. Il ne contient aucun secret.
L’environnement existant prévaut sur `.env`. La configuration est chargée depuis
la racine du dépôt, indépendamment du répertoire courant.

| Variable | Défaut | Contrat |
|---|---|---|
| `DATABASE_URL` | Chemin absolu vers `var/impactflow.sqlite3` dans le dépôt | SQLite sur disque, chemin absolu obligatoire ; URL sans options |
| `APP_ENV` | `development` | `development`, `test` ou `production` ; ne constitue pas une autorisation de déploiement |

Exemple de chemin alternatif : `sqlite:////tmp/impactflow-demo.sqlite3`.
La base en mémoire est réservée aux tests. Les fichiers `.env`, le dossier
`var/` et les bases SQLite sont ignorés par Git. Le passage à un autre moteur SQL
n’est pas annoncé comme pris en charge par cette étape.

## Commandes locales

```bash
python -m app.cli init-db
python -m app.cli seed-demo
python -m app.cli inspect
python -m app.cli inspect --event demo-fabrique --workshop fabrique-photo
python -m app.cli set-workshop-location --event demo-rencontres --workshop w1 --actor demo-thomas --location "Salle Bordeaux"
```

L’option globale `--database-url URL` se place **avant** le nom de la commande :

```bash
python -m app.cli --database-url sqlite:////tmp/impactflow-demo.sqlite3 init-db
```

`set-workshop-location` est une commande locale de vérification de persistance,
accessible à une personne ayant accès au poste et à la base. L’argument acteur
n’est pas une authentification : il vérifie les droits métier du compte indiqué,
sans remplacer les sessions sécurisées de C1-03. Aucun endpoint HTTP équivalent
n’est exposé. La commande conserve ancienne/nouvelle valeur, auteur et date ;
elle ne déclenche pas encore de notification. Une valeur identique ne crée rien.

Erreurs attendues : code de sortie **2**, message sur stderr sans traceback ou
détail SQL. Aucun accès refusé ou état invalide n’est enregistré partiellement.

## Vérifier la persistance entre processus

1. Initialiser et charger le seed.
2. Lancer `inspect` : deux événements, huit participants confirmés dans les
   Rencontres, Cuisine dans « La Cuisine », quatre personnes impactées.
3. Modifier le lieu de Cuisine avec la commande ci-dessus.
4. Fermer l’application, puis relancer le serveur et `inspect` dans de nouveaux
   processus. Retrouver « Salle Bordeaux » et le changement avec auteur, date,
   ancienne et nouvelle valeur.
5. Relancer `init-db` et `seed-demo` : les données modifiées sont conservées.

Ce parcours est également exécuté par un test qui lance réellement plusieurs
processus Python. La reprise d’une fenêtre de fusion ou d’une tentative d’envoi
est réservée au cycle 2 ; la fondation persiste les données métier et l’historique.

## Modèle SQL et invariants

| Tables | Responsabilité |
|---|---|
| `users`, `contacts` | Comptes et carnet commun ; e-mails normalisés ; pas de mot de passe en clair |
| `events`, `event_organizers` | Responsable principal, coorganisateurs et états de chaque événement |
| `workshops`, `dependencies` | Programme, horaires UTC, capacités et liens orientés |
| `invitations`, `invitation_workshops`, `invitation_responses` | Invitations, suggestions d’ateliers et réponses datées |
| `organizer_invitations` | Schéma des invitations organisateur ; empreinte du jeton seulement |
| `participation_requests` | Demandes ouvertes, distinctes des participations actives |
| `participations`, `enrollments` | Participations confirmées et inscriptions actives ou retirées |
| `changes` | Historique par auteur/entité/champ, ancienne et nouvelle valeur JSON |
| `notifications`, `notification_changes` | Contenus, états, lu/non lu et lien vers les changements |

- Les clés étrangères SQLite sont activées sur chaque connexion.
- Les clés composites empêchent de relier deux événements par une inscription,
  dépendance, proposition d’atelier, cible de changement ou lien notification/changement.
- Les clés uniques interdisent les doubles inscriptions et les invitations
  dupliquées pour une même adresse dans un événement.
- Les contraintes SQL refusent les états inconnus, les capacités non positives,
  les dates de fin antérieures ou égales au début, et les dépendances vers soi-même.
- Les dates applicatives doivent contenir un fuseau, sont stockées en UTC et
  restituées avec ce fuseau. L’affichage utilise `Europe/Paris`, y compris au
  changement d’heure. SQLite conserve techniquement des dates sans fuseau :
  le type applicatif `UTCDateTime` impose leur interprétation UTC.
- `Database.transaction()` regroupe l’état courant et son historique dans un
  commit unique ; une exception annule toutes les écritures de la transaction.
- Les suppressions référencées sont refusées par défaut ; aucune cascade
  destructive silencieuse n’a été ajoutée.

Les contraintes SQL ne remplacent pas les services métier. Les contrôles de
capacité/concurrence et de chevauchement sont C2-02, le refus des cycles dans
les formulaires est C1-05 et les réponses aux invitations sont C1-06. Ces règles
ne sont pas prétendues disponibles sous prétexte que leur schéma existe.

## Reconstruction du graphe

`app.services.load_graph(session, event_id)` retourne le `EventGraph` historique :

1. Ajouter les comptes actifs ayant une participation confirmée dans cet événement,
   y compris ceux sans atelier, utiles pour le ciblage global ultérieur.
2. Ajouter les ateliers actifs de cet événement.
3. Ajouter seulement les inscriptions actives reliant ces comptes et ateliers.
4. Ajouter les dépendances dont les deux ateliers figurent dans ce graphe.

Le résultat est transmis au BFS existant ; aucun second algorithme de propagation
n’a été ajouté. Un événement inconnu est une erreur métier. Une dépendance
cyclique injectée en base reste tolérée par le moteur pour tester sa robustesse ;
les formulaires futurs devront interdire sa création.

## Fixtures déterministes

Le seed représente un état **après acceptation d’Alice**, contrairement à la
maquette qui démarre avant sa réponse. Il contient :

- Deux événements, deux organisateurs et Alex participant aux deux.
- Six ateliers dans les Rencontres et un atelier dans la Fabrique.
- Cuisine → Dégustation → Accords, plus Cuisine → Accords pour tester les chemins
  multiples ; Poterie → Vernissage constitue une branche épargnée, Photo est indépendante.
- Alice inscrite à Cuisine et Dégustation, dédupliquée dans l’impact.
- Bruno refusé et Chloé en attente, sans participation active dans les Rencontres.
- Une demande de Chloé en attente dans la Fabrique, sans inscription active.
- Un historique fictif de corrections rapprochées, annulation puis réactivation ;
  la participation finale d’Alex à la Fabrique est datée après cette réactivation.
- Une notification d’exemple marquée `skipped`, reliée aux corrections, **aucun envoi réel**.

Identités `demo-*`, adresses `example.test`, aucun mot de passe, aucun lien
d’invitation utilisable. Le seed est transactionnel et ne s’exécute que sur une
base vide. Une relance détecte la démonstration et n’écrase rien.

## Migrations, contrôles et erreurs

La révision `0001` crée le schéma explicitement. Elle n’appelle pas
`Base.metadata.create_all()` : son contenu reste indépendant des modèles futurs.
`init-db` applique Alembic. Au démarrage, la version et la présence des tables
sont vérifiées. Une base partiellement endommagée n’est pas recréée silencieusement.

```bash
python -m pytest -q -o addopts= -W error
ruff check .
python -m pip check
```

La CI conserve les tests du moteur et découvre les tests de `tests/web/` ; les
avertissements sont traités comme des erreurs. Les tests utilisent des bases
temporaires isolées, sans modifier `var/impactflow.sqlite3`.

Résultat local du 15 octobre 2026 : **178 tests réussis**, dont les 92 historiques
et 86 nouveaux, Ruff sans erreur, `pip check` sans conflit. Le vrai serveur a
également été vérifié dans Chrome : **11 contrôles réussis**, aucune exception
JavaScript, sur ordinateur (1440 px) et téléphone (390 px), avec les deux thèmes.
Ce résultat local ne constitue pas encore un résultat de CI distante : celle-ci
s’exécutera après le push.

Les versions directes sont fixées dans `requirements.txt` ; `constraints.txt`
fixe les dépendances transitives résolues dans l’environnement Linux/Python 3.12
vérifié. Une mise à jour doit modifier ces versions ensemble et relancer les
contrôles ; les versions ne sont pas annoncées comme testées sur tout autre OS.

| Situation | Comportement vérifié |
|---|---|
| Base non initialisée, mauvaise révision ou table manquante | Démarrage refusé, message d’action explicite |
| Base temporairement indisponible | HTTP 503, sans requête SQL ou données personnelles dans la réponse |
| Page absente, événement privé ou non publié | HTTP 404 avec retour au catalogue |
| Erreur interne inattendue | HTTP 500 avec message neutre, sans détail technique exposé |
| Valeur invalide, cible inconnue, acteur non autorisé, événement fermé | Erreur métier, état et historique inchangés |
| Exception après une écriture | Rollback de l’état et de l’historique |
| Contenu HTML dans un nom | Échappé par Jinja2 ; politique CSP sans script en ligne |

La route `/health` vérifie une connexion et une requête SQL. Elle ne constitue
pas une preuve de disponibilité d’un fournisseur d’e-mails ni un audit complet
de toutes les données. Les pages d’erreur ne prétendent pas réparer une base.

Pour créer une prochaine migration après modification des modèles :
`alembic revision --autogenerate -m "description"`, puis relire le script généré
avant de l’appliquer avec `python -m app.cli init-db`. Sauvegarder la base avant
une migration de données utilisée réellement.

## Limites de cette livraison

Fondation locale, pas de déploiement. Authentification, invitations envoyées,
formulaires admin, confirmations transactionnelles d’inscription, worker réel,
fusion persistante et fournisseur d’e-mails ne sont pas encore implémentés.
La reprise fine des envois et les relances manuelles appartiennent au cycle 2.

Références techniques utilisées : [cycle de vie FastAPI](https://fastapi.tiangolo.com/advanced/events/),
[contraintes SQLAlchemy](https://docs.sqlalchemy.org/en/20/core/constraints.html),
[migrations SQLite Alembic](https://alembic.sqlalchemy.org/en/latest/batch.html) et
[client de test Starlette](https://starlette.dev/testclient/).

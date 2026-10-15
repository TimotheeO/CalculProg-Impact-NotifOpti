# ImpactFlow — choix techniques et alternatives

Mis à jour le 15 octobre 2026. Ce journal prépare l’explication au jury et
permet de réexaminer les choix. Les comparaisons sont qualitatives, fondées
sur le besoin du projet et les références officielles citées. Les frameworks
alternatifs n’ont pas été implémentés ou comparés par benchmark dans ce dépôt.

Pour chaque nouvelle tâche, ajouter ou actualiser les décisions significatives.
Une décision approuvée dans le plan n’est pas présentée comme un choix nouveau.
Les preuves manuelles sont décrites dans [RECETTE_MANUELLE.md](RECETTE_MANUELLE.md).

## D01 — FastAPI pour la couche web

**État :** prévu dans le plan validé, appliqué en C1-02. Le moteur reste Python.

| Possibilité | Intérêt dans ce projet | Compromis |
|---|---|---|
| FastAPI, retenu | Routes Python séparées du moteur et tests HTTP ; permet ensuite des endpoints JSON pour le graphe | Authentification, admin et règles d’accès restent à construire et tester |
| Django | ORM, authentification et administration intégrés, intéressants pour ce périmètre riche en comptes et formulaires | Adopter ses conventions et intégrer le moteur à cette structure ; alternative sérieuse si le cadre initial était ouvert |
| Flask | Couche web légère, compatible avec des templates et le moteur Python | Composer aussi les briques de validation, persistance et authentification nécessaires |

**Justification :** conserver la stack déjà validée et un moteur indépendant
de la couche HTTP. Le choix ne démontre pas que FastAPI est plus rapide à
développer ou à exécuter que Django pour ce produit.

**À l’oral :** « Le plan avait retenu FastAPI. Je l’ai utilisé comme couche web
autour du moteur Python existant. Django aurait apporté un admin et une
authentification intégrés ; avec FastAPI, je dois vérifier ces briques moi-même. »

**Preuve :** `app/web.py`, tests HTTP dans `tests/web/test_web.py`. Réexaminer
si les besoins ou le périmètre imposent un autre cadre ; une migration aurait
un coût qui n’a pas été estimé ici.

Références : [comparaisons FastAPI](https://fastapi.tiangolo.com/alternatives/),
[administration Django](https://docs.djangoproject.com/en/5.2/ref/contrib/admin/).

## D02 — HTML rendu par Jinja2, JavaScript ciblé

**État :** Jinja2 prévu dans le plan ; organisation actuelle appliquée en C1-02.

| Possibilité | Intérêt | Compromis |
|---|---|---|
| Jinja2 côté serveur, retenu | Pages, données et futures sessions dans une seule application ; pas de build frontend pour les écrans actuels | Les interactions riches nécessiteront du JavaScript complémentaire |
| Frontend React/Vue séparé en SPA | Gestion adaptée à une interface très interactive avec état client important | Projet frontend, contrat API et synchronisation des états à maintenir en plus |
| HTML entièrement statique | Suffisant pour les maquettes C1-01 et facile à ouvrir | Ne fournit ni données persistantes ni contrôle d’accès serveur |

**À l’oral :** « Les écrans actuels sont surtout des listes et des formulaires.
Le serveur produit le HTML et j’ajoute du JavaScript pour les interactions
utiles. La maquette statique sert à valider les parcours ; le site lit la base. »

**Preuve :** `app/templates/`, `app/static/theme.js`, test d’échappement HTML.
Réexaminer le besoin d’une couche frontend plus importante si le graphe ou
les interactions dépassent ce que cette organisation maintient simplement.

Référence : [templates FastAPI/Jinja2](https://fastapi.tiangolo.com/advanced/templates/).

## D03 — SQLite sur disque pour la livraison locale

**État :** fixé par le plan pour le local, appliqué en C1-02.

| Possibilité | Intérêt | Compromis |
|---|---|---|
| SQLite sur disque, retenu | Persistance, transactions et contraintes SQL sans serveur de base séparé | Les écritures concurrentes sont sérialisées ; le disque doit rester durable |
| PostgreSQL | Serveur de base adapté à plusieurs clients et à davantage d’écritures concurrentes | Service, configuration, sauvegarde et compatibilité d’hébergement à prévoir |
| Fichier JSON | Lisible, déjà utile pour le jeu de données de la CLI | Cohérence relationnelle, transactions et concurrence à gérer autrement |
| Base en mémoire | Rapide à créer et isoler dans les tests | Perdue à l’arrêt, incompatible avec la livraison persistante |

**À l’oral :** « SQLite couvre la démonstration locale avec transactions et
contraintes, sans service supplémentaire. Je ne le présente pas comme une
solution à beaucoup d’écritures simultanées ; je testerai explicitement la
dernière place en concurrence. »

**Preuve :** `app/database.py`, test entre processus dans
`tests/web/test_web_cli.py`. La capacité transactionnelle concurrente est prévue
en C2-02 et n’est pas livrée par la seule création du schéma. PostgreSQL serait
à réévaluer pour un déploiement ou une charge différente ; ce changement n’est
pas garanti sans adaptation et tests.

Référence : [cas d’usage et limites SQLite](https://www.sqlite.org/whentouse.html).

## D04 — SQLAlchemy et sessions synchrones

**État :** décision d’implémentation C1-02 ; une base SQL était déjà prévue.

| Possibilité | Intérêt | Compromis |
|---|---|---|
| SQLAlchemy synchrone, retenu | Modèles partagés, requêtes explicites, transactions délimitées et intégration Alembic | Dépendance et concepts ORM à expliquer ; SQL et contraintes restent à comprendre |
| SQL écrit avec `sqlite3` | Bibliothèque standard, maîtrise directe des requêtes | Mapping, répétition des accès et évolution du schéma à organiser soi-même |
| SQLAlchemy asynchrone | API compatible avec une chaîne d’entrées/sorties asynchrones | Pilote et gestion async supplémentaires ; ne supprime pas la limite d’écriture SQLite |

**Justification :** les accès à la base sont synchrones, et les routes qui les
utilisent sont des fonctions `def`, exécutées par FastAPI dans sa réserve de
threads. Une session n’est pas partagée entre requêtes. Ajouter `async` à une
fonction ne rendrait pas ses appels bloquants asynchrones.

**À l’oral :** « J’ai gardé une chaîne d’accès SQL synchrone cohérente. L’ORM
m’aide à structurer les données et les transactions ; il ne remplace pas la
connaissance du SQL et ne prouve pas une meilleure performance. »

**Preuve :** `app/models.py`, `app/database.py`, routes dans `app/web.py`.
Réexaminer lors d’un changement de pilote, de charge ou de services externes.

Références : [sessions SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/session_basics.html),
[fonctions synchrones dans FastAPI](https://fastapi.tiangolo.com/async/).

## D05 — Migrations Alembic explicites

**État :** schéma versionné exigé au plan ; Alembic retenu en C1-02.

**Comparaison :** Alembic conserve une suite de transformations versionnées.
`create_all()` convient pour créer des tables absentes, mais ne remplace pas
la migration de tables existantes. Des scripts SQL manuels seraient possibles,
avec une discipline de version, d’ordre et de suivi à construire.

**Compromis :** un script généré doit être relu et testé. Les migrations ne
dispensent pas de sauvegarde. Le serveur vérifie le schéma au démarrage ; la
commande `init-db` applique les migrations explicitement. Une migration au
démarrage automatique aurait un lancement plus court pour l’utilisateur mais
introduirait une modification implicite de la base au lancement du serveur.

**À l’oral :** « Je dois pouvoir faire évoluer une base déjà remplie. Une
migration décrit cette évolution ; recréer les tables ne répond pas au besoin
de conserver les données. »

**Preuve :** révision `0001`, tests de réinitialisation sans écrasement, de
version incompatible et de table manquante. Réexaminer la procédure de migration
avant un hébergement ou un changement de moteur SQL.

Référence : [fonctionnement d’Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html).

## D06 — Contraintes relationnelles et transaction état/historique

**État :** isolation et persistance exigées ; mécanisme retenu en C1-02.

**Comparaison :** des vérifications uniquement dans les formulaires ne couvrent
pas les scripts, services ou accès concurrents. Une clé étrangère simple vérifie
qu’un atelier existe ; une clé composite `(event_id, workshop_id)` vérifie
également qu’il appartient au bon événement. Les services donnent des messages
métier et la base constitue une protection supplémentaire.

**Choix :** clés composites, unicité des inscriptions, contraintes d’état et
transaction commune pour la modification et son historique. Deux commits
séparés pourraient conserver un nouvel état sans son historique si le second
échoue. Le contrat actuel annule les deux écritures en cas d’exception.

**À l’oral :** « Un identifiant d’atelier valide ne suffit pas : il doit appartenir
au même événement. Et une modification n’est complète que si son historique
est enregistré avec elle, dans la même transaction. »

**Preuve :** tests de liens inter-événements et de rollback dans
`tests/web/test_database.py` et `tests/web/test_services.py`.
Ces contraintes n’implémentent pas encore les capacités ou tous les contrôles
de concurrence. L’historique est durable, pas un journal cryptographiquement
infalsifiable ; ces garanties sont distinctes.

Référence : [clés composites SQLAlchemy](https://docs.sqlalchemy.org/en/20/core/constraints.html).

## D07 — Dates UTC avec fuseau explicite

**État :** choix d’implémentation C1-02, cohérent avec la reprise durable prévue.

**Comparaison :** stocker « 14h » perd la date et le fuseau ; stocker une heure
locale sans fuseau crée des ambiguïtés au changement d’heure. Des instants UTC
avec conversion à l’affichage conservent une base de comparaison commune.

**Choix :** dates applicatives avec fuseau, normalisation en UTC, affichage
`Europe/Paris`. SQLite ne conserve pas nativement le fuseau dans ce schéma :
`UTCDateTime` impose le contrat au niveau de l’application.

**À l’oral :** « Je stocke l’instant en UTC et j’affiche l’heure locale. Une même
heure écrite sans sa date ni son fuseau ne suffit pas à vérifier un conflit. »

**Preuve :** rejet d’une date naïve, réouverture en UTC, affichage du 30 octobre
2026 en heure de Paris dans les tests. Une politique d’édition d’événements
dans plusieurs fuseaux serait à définir si ce besoin apparaît.

Référence : [dates avec et sans fuseau en Python](https://docs.python.org/3.12/library/datetime.html).

## D08 — Erreurs explicites et écrans publics limités au périmètre livré

**État :** choix d’implémentation C1-02 ; sécurité des futurs comptes exigée au plan.

**Comparaison :** afficher l’exception brute aide ponctuellement au diagnostic
mais peut divulguer requêtes ou données. Renvoyer toujours 200 masque l’échec
aux clients et outils de surveillance. Les réponses actuelles utilisent 404
pour une page absente/non publique, 503 pour une indisponibilité SQL et 500 pour
une erreur inattendue, avec message neutre côté utilisateur.

**Choix :** pas de route admin de modification sans l’authentification future.
La commande locale de vérification reste accessible depuis le poste ; son
paramètre `--actor` vérifie des droits métier et ne constitue pas une connexion.
Le contrôle `/health` prouve un accès SQL, pas le fonctionnement du futur Mailer.

**À l’oral :** « Le serveur distingue les échecs et ne montre pas les détails
internes au visiteur. Je précise aussi les limites : la CLI locale n’est pas
un espace administrateur authentifié. »

**Preuve :** tests HTTP d’erreur et de non-divulgation. La journalisation pourra
être enrichie pour l’exploitation ; elle se limite actuellement au type d’erreur
sans paramètres SQL.

## D09 — Tests isolés, scénarios déterministes et versions fixées

**État :** décision d’implémentation C1-02 ; préserver la CLI et les tests est imposé.

**Comparaison :** des mocks seuls peuvent manquer une contrainte SQL ou une
perte au redémarrage ; tout tester en navigateur rend les échecs moins ciblés.
Les tests actuels combinent moteur, vraies bases SQLite temporaires, client HTTP,
processus distincts et vérification visuelle sur le vrai serveur. Les mocks
servent notamment à provoquer une panne SQL de façon contrôlée.

**Choix :** fixtures fixes et bases isolées ; versions directes et transitives
fixées pour retrouver l’environnement vérifié. Des versions flottantes éviteraient
des mises à jour manuelles, avec un risque de changement implicite entre deux
installations. Des versions fixées exigent toujours des mises à jour suivies et testées.

**À l’oral :** « Chaque niveau de test apporte une preuve différente. Une base
temporaire vérifie les contraintes réelles ; un nouveau processus vérifie que
les données ne vivaient pas seulement en mémoire. »

**Preuve actuelle :** 178 tests réussis, dont 92 historiques et 86 nouveaux,
et 11 contrôles du vrai serveur dans Chrome. Cela ne garantit pas zéro bug,
ne mesure pas une charge réelle et ne remplace pas la recette de l’étudiant.

## D10 — Réutiliser le moteur de graphe

**État :** moteur hérité, préservation prévue ; adaptation SQL livrée en C1-02.

**Comparaison :** BFS et DFS peuvent tous deux calculer l’ensemble atteignable.
Le BFS existant utilise une file `deque` et un ensemble de nœuds visités : un
atelier n’est parcouru qu’une fois, même avec cycle ou chemins multiples. Un
DFS itératif serait aussi valable ; la récursion demanderait de gérer la
profondeur maximale. Une bibliothèque de graphes apporterait d’autres opérations,
sans être nécessaire à ce seul parcours.

**Choix :** reconstruire un `EventGraph` à partir des liens actifs puis appeler
le BFS existant, au lieu de réécrire la propagation dans le frontend ou en SQL.
Le parcours est linéaire dans les ateliers, liens et inscriptions parcourus ;
il n’a pas été comparé en performance à une implémentation DFS.

**À l’oral :** « Le SQL sélectionne les données actives du bon événement, puis
le moteur calcule la propagation. Je teste séparément ces deux responsabilités. »

**Preuve :** `src/impact.py`, tests du moteur, jeux multi-événements et diamant
dans `tests/web/test_graph_loader.py`. Réexaminer si les volumes mesurés ou les
besoins de graphe rendent cette reconstruction coûteuse.

## D11 — Priorité, débit et regroupement : choix du moteur hérité

Ces mécanismes existent dans la simulation. Leur intégration au worker web
et la reprise durable ne sont pas livrées en C1-02.

| Besoin | Choix existant | Alternative et compromis |
|---|---|---|
| Ordre d’urgence | Tas `heapq`, insertion/retrait en O(log n), compteur pour les égalités | Une FIFO respecte seulement l’arrivée ; trier une liste entière à chaque retrait refait un travail inutile pour une file alimentée progressivement |
| Quota strict sur une période glissante | Horodatages conservés dans une `deque` | Un token bucket exprime une recharge et peut autoriser des rafales selon sa capacité ; il ne correspond pas nécessairement au même contrat strict |
| Regrouper les corrections rapprochées | Fenêtre fixe depuis le premier changement, dernière valeur conservée | Un debounce relancé à chaque changement peut repousser l’échéance tant que les modifications continuent |

**À l’oral :** « La priorité choisit parmi les messages disponibles ; elle ne
rend pas automatiquement une annulation disponible. Le worker devra donc la
sortir de la fenêtre de regroupement tout en conservant le quota. »

À urgence égale, le compteur préserve l’ordre d’insertion. Un parcours d’ensemble
peut faire varier l’ordre initial de personnes équivalentes : ne pas promettre
un ordre alphabétique déterministe dans le moteur historique.

La fenêtre de **60 secondes** est une décision métier validée, pas un optimum
mesuré. La CLI historique utilise encore **30 secondes** par défaut ; la fenêtre
produit sera appliquée avec l’intégration C1-09. Le quota réel dépendra du fournisseur.

**Preuve :** `src/notifications.py`, `src/rate_limiter.py`, `src/batching.py` et
leurs tests ; vérificateur de débit indépendant dans `src/report.py`.
La suppression des contenus périmés déjà en file et les annulations immédiates
restent prévues en C2-03.

Références : [file de priorité heapq](https://docs.python.org/3.12/library/heapq.html),
[file deque](https://docs.python.org/3.12/library/collections.html#collections.deque).

## Décisions encore ouvertes

- Fournisseur d’e-mails : accès, expéditeur validé, quotas, déduplication et
  consultation des résultats à comparer avant sélection, sans achat.
- Authentification : algorithme de hachage, stockage des sessions et protections
  à documenter lors de C1-03 ; aucun mécanisme n’est prétendu livré ici.
- Hébergement : évaluation gratuite en C2-08 ; aucune offre n’est retenue.
- Actualisation du graphe et des notifications : le délai attendu est défini,
  la solution technique sera expliquée lors de son implémentation.

## Format des prochaines entrées

Documenter : identifiant/tâche, problème, choix et provenance, alternatives,
raison adaptée au projet, limites, phrase d’explication à l’oral, preuve exécutée
et condition qui ferait réexaminer la décision. Un changement de décision reste
traçable ; il ne doit pas effacer l’explication du choix précédent.

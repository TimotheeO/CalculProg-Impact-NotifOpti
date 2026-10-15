# Résumé de reprise pour Codex — ImpactFlow

Synthèse initiale de la discussion « Recréer le PDF proprement », complétée après l’audit et les réponses de l’étudiant du 15 octobre 2026. Ce document permet de continuer le projet dans un nouveau chat. Il ne prouve pas que les fonctionnalités prévues sont déjà développées.

## Mise à jour du 15 octobre 2026

Les règles produit consolidées sont dans [PRODUCT.md](PRODUCT.md). Ce document intègre les réponses de l’étudiant et prévaut sur les formulations historiques ci-dessous en cas d’écart.

### Préférences de travail à conserver

- L’étudiant doit pouvoir expliquer les choix au jury et les comparer à d’autres possibilités. Pour chaque décision significative, actualiser [DECISIONS_TECHNIQUES.md](DECISIONS_TECHNIQUES.md) avec provenance, alternatives, avantages/limites, explication orale et preuve ; ne pas inventer de benchmark.
- À la fin de chaque tâche, indiquer comment vérifier soi-même l’avancement : commandes, actions à l’écran, résultats attendus et erreurs pertinentes. Actualiser [RECETTE_MANUELLE.md](RECETTE_MANUELLE.md), qui couvre déjà C1-01 et C1-02 ; isoler les données pour les essais modifiants.
- Ces préférences sont également enregistrées dans AGENTS.md à la racine du dépôt, pour les prochaines reprises.

- Développement individuel les jeudis/vendredis ; soutenances confirmées les 23 octobre et 6 novembre 2026 ; dépôt Hub effectué.
- Audit : 92 tests réussis, Ruff sans erreur, commit local et distant `53a39b9`, dernière CI réussie. Le site et les e-mails réels ne sont pas encore implémentés.
- Import GitHub confirmé : 19 tâches de reprise, toutes Todo au moment de l’audit, lot Reprise octobre 2026, 4 jours par cycle. Ne pas relancer un import pour les recréer.
- Anciennes tâches : 7 Done, tâche 8 en Verification ; l’étudiant confirme que cette dernière est terminée et que son statut est un oubli. Aucun statut distant n’a été modifié pendant l’audit.
- Les documents et le dossier d’import annoncés dans l’ancien échange ne sont pas disponibles ; l’étudiant confirme ne pas disposer de ces fichiers. Ne pas les traiter comme des prérequis accessibles.
- Un responsable principal par événement, avec coorganisateurs en complément ; carnet de contacts commun aux organisateurs, comprenant les comptes de l’application.
- Catalogue public pour les événements ouverts, invitations personnelles également possibles, création de compte participant au moment d’une demande si nécessaire ; le rôle organisateur reste sur invitation.
- L’invité choisit ses ateliers. Le participant peut annuler une inscription ; l’organisateur peut retirer une personne d’un atelier ou de l’événement.
- Reporter la date de l’événement décale tous ses ateliers du même décalage. Réactivation possible après annulation avec nouvelle confirmation des participants.
- Modifier une dépendance recalcule les destinataires des notifications encore en attente.
- Un retour à la valeur initiale avant envoi conserve l’historique sans notification pour ce changement ; une annulation urgente est envoyée séparément des autres changements indépendants, qui gardent leur échéance.
- Aucun fournisseur d’e-mails ni domaine n’est configuré ; l’étudiant dispose seulement de son adresse personnelle.

### Première réalisation de la reprise : C1-01

- PRODUCT.md consolide les règles et les parcours ; la palette exacte figure dans docs/maquettes/README.md.
- Trois maquettes interactives locales sont disponibles dans [maquettes/index.html](maquettes/index.html) : organisation, invitation et espace participant, avec thèmes clair/nuit et mise en page téléphone.
- Un nouveau [SCENARIO_DEMO.md](SCENARIO_DEMO.md) a été rédigé ; il ne provient pas des fichiers annoncés dans l’ancien échange.
- Les réponses et changements des maquettes restent en mémoire ; seul le thème est mémorisé. Aucun compte, base SQL ou envoi réel n’a été implémenté par ces écrans.
- Vérification : 26 contrôles navigateur réussis, aucune exception JavaScript ; 92 tests Python réussis et Ruff sans erreur. Captures dans docs/maquettes/apercus/.
- C1-01 a été enregistré dans les commits locaux `2af9335` (documentation) et `fb33a2a` (maquettes). Le push est laissé à l’étudiant et les statuts GitHub n’ont pas été modifiés par l’assistant.

### Fondation persistante C1-02

- Application dans app/, FastAPI/Jinja2, catalogue et programme des événements publiés ouverts, thèmes clair/nuit et route /health. Aucun accès aux événements privés ou données personnelles via ces pages.
- SQLite sur disque dans var/impactflow.sqlite3, SQLAlchemy et première migration Alembic 0001 ; configuration .env.example et bases/secrets ignorés par Git.
- Schéma des comptes, contacts, événements/coorganisateurs, ateliers/dépendances, invitations/réponses, demandes, participations/inscriptions, changements et liens vers les notifications.
- load_graph(session, event_id) reconstruit le graphe depuis les participations confirmées et inscriptions actives ; BFS historique réutilisé sans modification de src/.
- Commandes python -m app.cli : init-db, seed-demo, inspect et set-workshop-location pour vérifier état courant et historique après relancement. Cette dernière est une commande locale de vérification, pas un endpoint authentifié.
- Fixtures déterministes : deux événements, Alex commun aux deux, diamant/cascade, branche épargnée, atelier indépendant, multi-inscription, refus et attente exclus. Alice est déjà confirmée dans le seed, contrairement à l’état initial de la maquette.
- Contrôles : 178 tests réussis (92 historiques + 86 nouveaux), avertissements traités comme erreurs, Ruff et pip check sans erreur ; 11 contrôles du vrai serveur dans Chrome réussis, sans exception JavaScript.
- Les tests vérifient notamment l’isolation SQL, les droits métier du service local, les transactions annulées en erreur, les pages 404/500/503 sans fuite et la conservation des données entre processus.
- Versions directes et transitives fixées ; CI configurée pour tous les tests. Résultat de CI distante à vérifier après push ; ne pas confondre avec la vérification locale.
- Guide : [DEVELOPPEMENT.md](DEVELOPPEMENT.md). Connexion, formulaires admin, envoi réel et reprise des groupes ne sont pas encore implémentés. Prochaine tâche : C1-03, avec dépendance fournisseur C1-07 à préparer.

## Contexte et objectif

Je suis étudiant en Tech 3 à EPITECH Nice. Ce travail concerne le projet Simulated « Propagation d’impact et notification optimisée », appelé ImpactFlow dans le dossier final.

Un moteur Python existe déjà : graphe de dépendances, calcul des personnes impactées par BFS, fusion des notifications, file de priorité avec heapq et limiteur à fenêtre glissante. Le but est de le transformer en vrai site de coordination d’événements : organisateurs, événements et ateliers, participants, invitations, inscriptions, changements et véritables e-mails.

Le jury avait demandé une situation concrète avec un vrai espace administrateur, des participants fictifs réalistes, des changements créés depuis le site et des e-mails effectivement reçus.

## État connu : réalisé et préparé

- Archive du code initial : CalculProg-Impact-NotifOpti.zip.
- Dépôt de référence indiqué dans le plan final : TimotheeO/CalculProg-Impact-NotifOpti.
- L’assistant précédent a rapporté 92 tests réussis lors de l’audit local du ZIP. Ce nombre est un résultat passé, à revérifier sur le code actuel.
- Le code du ZIP initial n’a pas été modifié pendant la préparation du plan.
- Les règles métier ont été discutées puis validées, tâche par tâche.
- L’ancien échange annonçait un plan et un dossier d’import : Plan_GitHub_Project_ImpactFlow.md et Dossier_GitHub_Project_ImpactFlow.zip. Leur disponibilité n’est pas confirmée ; l’étudiant indique le 15 octobre ne pas disposer de ces documents.
- Les noms SPECIFICATION_FONCTIONNELLE.md, SCENARIO_DEMO.md, IMPORT_GITHUB.md et lancer_import.sh proviennent de cet échange ; leurs versions d’origine ne sont pas présentes dans le dépôt audité. Le SCENARIO_DEMO.md actuel a été créé pendant la reprise du 15 octobre.
- Le dernier message annonçait 15 tests de simulation réussis pour l’import. Ils ne prouvent ni un import réel sur GitHub, ni le développement du site.
- Au 14 octobre, l’import n’était pas confirmé dans la synthèse. L’audit du 15 octobre confirme les 19 tâches importées dans le Project.
- Le chat Work est ensuite resté bloqué avec un bouton Arrêter qui revient. Ce dysfonctionnement ne prouve aucun avancement supplémentaire.

## Périmètre et décisions validées

### Rôles, comptes et événements

- Un super-admin initial invite les organisateurs. Pas d’inscription organisateur libre.
- Invitation personnelle, expirante, révocable et à usage unique ; possibilité de désactiver un accès.
- Chaque organisateur ne gère que les événements auxquels il est autorisé.
- Un utilisateur peut organiser un événement et participer à un autre.
- Plusieurs événements réels peuvent être créés depuis l’interface : nom, description, dates/heures, lieu, brouillon/publication.
- Deux modes : participation sur invitation, ou demandes ouvertes avec acceptation/refus par l’organisateur.
- Annuler/archiver un événement utilisé en conservant l’historique ; suppression limitée aux brouillons sans activité.

### Invitations et espace participant

- Carnet de contacts nom/e-mail, recherche et sélection de plusieurs invités, propositions d’ateliers et suivi des réponses.
- Invitations en attente, acceptées, refusées, révoquées ou expirées.
- Une attente ou un refus ne crée aucune participation/inscription active.
- Le lien présente l’événement et permet Accepter/Refuser ; une simple ouverture du lien ne change pas la réponse.
- À l’acceptation : retrouver le compte existant ou créer le compte, confirmer la participation et enregistrer les ateliers de manière idempotente.
- Connexion habituelle par e-mail et mot de passe. Pas de magic link de connexion.
- Récupération du mot de passe par lien temporaire à usage unique.
- Espace personnel : invitations, événements confirmés, ateliers, planning et boîte de notifications avec état lu/non lu.
- La boîte interne reste utilisable même si l’envoi de l’e-mail externe échoue.

### Ateliers, capacités et horaires

- Ateliers avec nom, description, début/fin, salle ou lieu, capacité limitée ou illimitée, état actif/annulé.
- Inscriptions uniques ; contrôle transactionnel de la capacité, y compris deux demandes concurrentes pour la dernière place.
- Désinscription possible, libérant la place.
- Bloquer les chevauchements d’inscriptions actives, même entre événements différents. Le message indique l’atelier déjà réservé et son horaire.
- Deux créneaux adjacents restent autorisés : 14–15 h puis 15–16 h.
- Un atelier annulé ou une inscription refusée ne réserve pas de créneau.
- Si un changement d’horaire crée un conflit existant, le signaler/notifier sans supprimer automatiquement une inscription.
- Liste d’attente automatique hors engagement.

### Dépendances, impacts et changements

- Dépendances entre ateliers du même événement, éditées par formulaires.
- Refuser les liens vers soi-même, vers un autre événement ou créant une boucle dans l’interface. Le moteur garde ses tests de robustesse aux cycles.
- Une dépendance propage l’impact ; elle ne décale pas automatiquement les horaires.
- Avant confirmation d’un changement : montrer ancienne/nouvelle valeur, ateliers impactés, destinataires uniques, personnes épargnées et raison directe/cascade/globale.
- Changement d’atelier : BFS sur participations confirmées et inscriptions actives.
- Changement global de l’événement : tous ses participants confirmés, même sans atelier.
- Exclure personnes en attente/refusées, branches non concernées et autres événements.
- Recalculer à la confirmation ; pas de notification pour une valeur identique.
- Historique durable avec auteur, date, ancienne/nouvelle valeur et lien aux notifications.

### Fusion, priorité et envoi

- Fenêtre fixe de 60 secondes par défaut, configurable, démarrant au premier changement ; les changements suivants ne repoussent pas son échéance.
- Même champ : conserver la dernière valeur. Plusieurs champs/ateliers : message cohérent par personne et par événement. Séparer les événements.
- Exemple : changements à t=0 et t=50 → message final préparé à t=60, les deux changements restant dans l’historique.
- Annulation prioritaire, disponible au prochain passage du worker sans attendre les 60 secondes, tout en respectant le quota.
- Retirer des messages non envoyés les informations devenues caduques ; conserver les informations pertinentes des autres ateliers.
- Si un e-mail est déjà parti, envoyer une information d’annulation ; aucun rappel du message déjà transmis.
- File de priorité des messages disponibles et limiteur fournisseur global, avec un seul ordonnanceur.
- UNE tentative automatique par e-mail. Aucun réessai automatique, y compris après redémarrage.
- Relance manuelle par organisateur autorisé après échec confirmé, tracée et protégée contre doubles clics/concurrence.
- Résultat incertain : vérifier auprès du fournisseur avant relance.
- Revérifier la pertinence et les inscriptions avant un envoi encore en attente.
- Continuer le traitement lorsque la page est fermée tant que le serveur fonctionne.

### Persistance, qualité et interface

- Base persistante obligatoire : comptes, événements, ateliers, invitations/réponses, inscriptions, changements et historique.
- Au cycle 2, persister aussi groupes de fusion, échéances, file, contenu/révision et résultats des tentatives.
- Au redémarrage, reprendre le temps restant sans ouvrir une nouvelle fenêtre ; ne pas retenter automatiquement un envoi déjà commencé ou terminé.
- Fixtures déterministes : atelier indépendant, dépendance directe, cascade, chemins multiples, multi-inscriptions, branche épargnée, refus/en attente et deux événements avec une personne commune.
- Authentification protégée : mots de passe hachés, cookies sécurisés selon l’environnement, CSRF, limitation des tentatives et secrets hors dépôt.
- Identité visuelle bordeaux sombre et mat.
- Mode clair blanc cassé/noir doux, mode nuit noir doux/cartes gris sombre ; bouton soleil/lune, préférence mémorisée, thème système au premier accès.
- Tableau de bord et graphe d’impact consultable : source/cascade/branches épargnées ; édition des dépendances par formulaire, pas d’éditeur par glisser-déposer demandé.
- Journal/boîte actualisés périodiquement sous 3 secondes lorsque le serveur fonctionne.
- Compteurs fondés sur les données réelles ; distinguer simulation, acceptation fournisseur et réception démontrée.
- Recherche, filtres, exports CSV protégés et archivage en lecture seule.
- Préserver la CLI et les tests initiaux, ajouter des tests métier pertinents et maintenir Ruff/CI.

### Technique et hébergement

- Le plan final prévoit FastAPI/Jinja2 et une base SQL ; SQLite sur disque en local.
- L’ancien document proposait aussi HTMX, SQLAlchemy/Alembic et des canaux Mailer HTTP/SMTP/mémoire. Vérifier le dépôt et la spécification finale avant de considérer chaque détail comme arrêté ; ne pas laisser cet ancien document écraser les décisions finales.
- Les vrais e-mails sont requis ; vérifier les conditions du fournisseur lors de sa sélection, sans considérer les anciens quotas comme garantis.
- Hébergement STRICTEMENT GRATUIT. Aucun abonnement ni paiement.
- Si aucune offre gratuite compatible avec Python, HTTPS, stockage durable et envoi externe n’est accessible, abandonner la mise en ligne et livrer une démonstration locale reproductible avec vidéo de secours.
- L’absence d’hébergement gratuit ne doit pas bloquer les fonctionnalités du site.

## Planning final à conserver

Deux cycles de deux semaines, présence jeudi/vendredi : objectif de 4 jours-homme par cycle, soit 8 jours-homme au total. Ces estimations sont optimistes, sans marge dédiée. Suivre séparément le temps réellement passé, y compris hors campus.

L’ancien plan annonçait 24 tâches et 15,25 jours-homme : il a été remplacé par ce plan final de 19 tâches.

| Nº | ID | Cycle | Tâche | Sizing (j-h) |
|---:|---|---:|---|---:|
| 1 | C1-01 | 1 | Définir les parcours du site et préparer les maquettes | 0,25 |
| 2 | C1-02 | 1 | Créer l’application web et la base de données persistante | 0,5 |
| 3 | C1-03 | 1 | Créer l’authentification et les invitations d’organisateurs | 0,5 |
| 4 | C1-04 | 1 | Créer et gérer plusieurs événements depuis l’admin | 0,5 |
| 5 | C1-05 | 1 | Créer les ateliers et gérer leurs dépendances | 0,5 |
| 6 | C1-06 | 1 | Sélectionner les invités et gérer leurs réponses | 0,75 |
| 7 | C1-07 | 1 | Mettre en place les vrais e-mails | 0,25 |
| 8 | C1-08 | 1 | Créer un changement avec aperçu de son impact | 0,25 |
| 9 | C1-09 | 1 | Relier le site au moteur de notifications optimisées | 0,25 |
| 10 | C1-10 | 1 | Afficher le journal et préparer la soutenance du cycle 1 | 0,25 |
| 11 | C2-01 | 2 | Construire l’espace participant et son compte e-mail/mot de passe | 0,5 |
| 12 | C2-02 | 2 | Gérer les inscriptions, capacités et conflits horaires | 0,5 |
| 13 | C2-03 | 2 | Prioriser les annulations et retirer les messages caducs | 0,5 |
| 14 | C2-04 | 2 | Reprendre les notifications après un arrêt du serveur | 0,5 |
| 15 | C2-05 | 2 | Gérer une tentative d’envoi et les relances manuelles | 0,5 |
| 16 | C2-06 | 2 | Finaliser l’interface bordeaux et le tableau de bord visuel | 0,5 |
| 17 | C2-07 | 2 | Ajouter recherche, exports et clôture des événements | 0,25 |
| 18 | C2-08 | 2 | Évaluer un hébergement gratuit et déployer si compatible | 0,25 |
| 19 | C2-09 | 2 | Vérifier le produit complet et préparer la soutenance finale | 0,5 |

| **Total cycle 1** | | **1** | | **4** |
| **Total cycle 2** | | **2** | | **4** |
| **Total** | | | | **8** |

Calendrier de travail : cycle 1 les 15/16 et 22/23 octobre 2026 ; cycle 2 les 29/30 octobre et 5/6 novembre. L’étudiant confirme les soutenances les 23 octobre et 6 novembre ; l’heure exacte n’est pas confirmée. Travail individuel les jeudis/vendredis. L’échéance initiale de dépôt Hub était le 14 octobre 2026 à 23 h 59, Europe/Paris ; l’étudiant confirme avoir effectué ce dépôt.

Mi-parcours : événement créé depuis le site → ateliers/dépendances → invitations/acceptation/refus → changement → bon ciblage/fusion → vrai e-mail reçu, journal et v0.1.

Finale : espace participant, capacités/conflits, annulations, reprise durable, relance manuelle, thèmes/graphe, exports/clôture, recette, documentation, vidéo et v1.0. Hébergement gratuit si compatible, sinon démonstration locale explicite. Ne pas présenter une fonctionnalité prévue comme livrée.

## GitHub Project et import confirmé

Project existant : https://github.com/users/TimotheeO/projects/2/views/1

- Ajouter au Project nº 2 sans supprimer ni modifier les anciennes tâches, leurs statuts, les colonnes, les vues ou le nom.
- Colonnes observées : Todo, In Progress, Verification, Done.
- Nouvelles tâches préfixées [Reprise C1-01] à [Reprise C2-09], initialement Todo, avec cycle, sizing, description, Definition of Done, dépendances et preuve.
- Champ texte Lot = Reprise octobre 2026 pour isoler les nouvelles tâches et leurs 8 jours.
- Import relançable grâce aux marqueurs : pas de doublon et pas de remise à Todo d’un statut déjà renseigné.
- Mode prévu : issues reliées au Project si dépôt public, draft items si dépôt privé afin que le planning soit visible dans le Project public.
- Ne pas changer la visibilité du dépôt/Project ni publier le code par cet import.
- L’ancien échange proposait bash lancer_import.sh après lecture d’IMPORT_GITHUB.md ; ces fichiers ne sont pas disponibles dans le dépôt audité.
- Résultat vérifié le 15 octobre : 19 tâches de reprise, 4 jours par cycle, toutes Todo. Les issues correspondantes sont les nº 9 à 27.
- L’import est déjà effectué. Ne pas recréer les tâches ; conserver les données et statuts existants.

## Reprise attendue dans Codex

1. Lire ce résumé, PRODUCT.md et les critères des issues GitHub ; les anciens documents annoncés ne sont pas disponibles. Inspecter le dépôt ou le ZIP disponible et les éventuelles instructions AGENTS.md.
2. Établir l’état réel du code, des tests et du Project. Distinguer moteur existant, documents/scripts préparés et fonctionnalités effectivement implémentées.
3. Utiliser les 19 tâches déjà importées en conservant les anciennes données du Project. Ne pas relancer un import inutile.
4. Poursuivre selon les tâches du cycle 1 et leurs dépendances, en réutilisant le moteur.
5. Conserver les décisions validées ci-dessus. Si une information manque, l’indiquer plutôt que l’inventer ; ne pas me faire revalider toutes les règles déjà arrêtées.

Le code du moteur est accessible dans le dépôt local. Le script d’import annoncé dans l’ancien échange n’est pas disponible et n’est pas nécessaire pour poursuivre les tâches déjà importées.

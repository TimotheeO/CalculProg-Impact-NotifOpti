# ImpactFlow — règles produit et parcours

État : cadrage de la reprise, consolidé avec les réponses de l’étudiant le
15 octobre 2026. Ce document décrit le produit à construire ; il ne constitue
pas une preuve de fonctionnalités livrées.

## Sources et situation actuelle

Les sources disponibles sont le sujet Simulated, les décisions de la conversation,
`Resume_ImpactFlow_pour_Codex.md` et les issues du
[GitHub Project nº 2](https://github.com/users/TimotheeO/projects/2).
Les réponses du 15 octobre prévalent sur les hypothèses antérieures.

Les anciens fichiers annoncés sous les noms `Plan_GitHub_Project_ImpactFlow.md`,
`SPECIFICATION_FONCTIONNELLE.md`, `SCENARIO_DEMO.md` et le dossier d’import n’ont
pas été récupérés. L’étudiant confirme ne pas disposer de ces anciens documents.
Un nouveau [SCENARIO_DEMO.md](SCENARIO_DEMO.md) a été rédigé le 15 octobre à partir
des règles confirmées ; il ne s’agit pas du document de l’ancien échange.
Ne pas demander la récupération des autres fichiers comme préalable au développement.

Le moteur Python et la CLI existent. Audit du 15 octobre : 92 tests réussis,
Ruff sans erreur, commit local et distant `53a39b9`, dernière CI réussie.
Le site, la base SQL, les comptes et les e-mails réels restent à développer.
Les 19 tâches de reprise sont importées, toutes en Todo lors de l’audit.
L’ancienne tâche 8 est terminée selon l’étudiant ; son statut Verification est
un oubli de suivi. Aucune modification GitHub n’a été effectuée pendant l’audit.

## Objectif et contraintes de livraison

Transformer le moteur en site de coordination d’événements utilisable sur
ordinateur et téléphone. Le jury attend un résultat plus abouti, avec création
depuis l’interface, participants réalistes, ciblage démontré et e-mail reçu.
L’étudiant ne dispose pas de grille écrite supplémentaire. Le site prévu reste
la cible de travail ; aucune validation explicite d’une équivalence à une
application mobile native n’a été rapportée.

- Développement individuel, les jeudis et vendredis.
- Soutenances confirmées les 23 octobre et 6 novembre 2026.
- Dépôt Hub effectué, confirmé par l’étudiant.
- Planning conservé : 19 tâches, 4 jours estimés par cycle, 8 jours au total.
- Sizing et temps réellement passé doivent être suivis séparément.
- Hébergement et services strictement gratuits, aucun paiement ni abonnement.
- À défaut d’hébergement compatible : démonstration locale reproductible et vidéo.
- Préserver la CLI et les tests initiaux ; ajouter les tests métier et maintenir la CI.

## Comptes, rôles et droits

- Un super-admin initial est créé par commande et invite les organisateurs.
- Aucune inscription libre ne donne le rôle organisateur.
- Chaque événement possède un responsable principal ; des coorganisateurs peuvent
  compléter son équipe. Leurs accès sont explicitement rattachés à cet événement.
- Un compte peut organiser un événement et participer à un autre.
- Le carnet de contacts est commun aux organisateurs : ils voient les comptes
  enregistrés dans l’application pour rechercher et sélectionner des invités.
- Ce carnet commun ne donne aucun accès supplémentaire aux événements,
  inscriptions, notifications ou historiques des autres organisateurs.
- L’annuaire de contacts des organisateurs n’est pas un annuaire public.
- Le parcours public permet de créer un compte participant au moment d’une demande.
- Connexion par e-mail et mot de passe, récupération par lien temporaire à usage unique.
- Mots de passe hachés, sessions protégées, CSRF, limitation des tentatives et secrets
  hors dépôt ; un compte désactivé ne peut plus utiliser ses anciennes sessions.

## Événements et découverte

Un événement comporte nom, description, lieu, début/fin et mode de participation.

| État | Comportement attendu |
|---|---|
| Brouillon | Privé, modifiable, sans admission publique ; suppression seulement sans activité |
| Publié | Visible et utilisable selon son mode de participation |
| Annulé | Nouvelles participations et inscriptions fermées ; historique conservé |
| Archivé | Données et historique consultables en lecture seule |

- Sur invitation : accès à la participation par invitation personnelle.
- Ouvert aux demandes : présent dans un catalogue public et accessible par lien ;
  demande soumise à acceptation/refus de l’organisateur.
- Un événement ouvert peut également faire l’objet d’invitations personnelles.
- Une demande en attente ne crée aucune participation active.
- Un changement global vise tous les participants confirmés de cet événement,
  même sans inscription à un atelier.
- Reporter la date de l’événement décale tous ses ateliers du même décalage.
  Montrer le programme résultant dans l’aperçu et traiter les conflits existants
  selon les règles d’horaires, sans désinscription automatique.

## Invitations et inscriptions

- Invitations personnelles, imprévisibles, expirantes et révocables.
- États : en attente, acceptée, refusée, révoquée, expirée.
- Ouvrir le lien affiche les détails sans accepter/refuser : la réponse nécessite un POST.
- L’invité choisit les ateliers précis qu’il souhaite faire ; les propositions
  de l’organisateur ne limitent pas cette sélection aux seuls ateliers proposés.
- Acceptation : retrouver le compte existant ou créer le compte avec mot de passe,
  confirmer la participation et enregistrer les choix de manière transactionnelle
  et idempotente. Un compte existant se connecte avant confirmation.
- Une invitation refusée ou en attente ne réserve aucune place et n’entre pas
  dans le graphe actif.
- Le participant peut annuler son inscription et libérer sa place.
- L’organisateur autorisé peut retirer un participant d’un atelier ou de
  l’événement entier. Retirer la participation à l’événement rend ses inscriptions
  inactives dans cet événement et conserve l’historique.
- Les inscriptions retirées ne participent plus au ciblage, sauf si une autre
  inscription active ou une cascade concerne encore la personne.

## Ateliers, capacités et horaires

- Nom, description, début/fin, salle/lieu, capacité limitée ou illimitée, état actif/annulé.
- Une inscription unique par personne et atelier, avec contrôle transactionnel
  de la dernière place, y compris en cas de demandes concurrentes.
- Refuser les chevauchements d’inscriptions actives, même entre événements.
  Expliquer quel atelier et quel horaire empêchent l’inscription.
- Autoriser les créneaux adjacents : 14–15 h puis 15–16 h.
- Un atelier annulé ne réserve plus de créneau.
- Appliquer les contrôles aux ateliers choisis lors de l’acceptation d’une invitation ;
  permettre de corriger les choix avant confirmation.
- Si une modification crée un conflit entre inscriptions existantes, le signaler
  et notifier les personnes concernées sans supprimer automatiquement leurs choix.
- Réactiver un atelier ou un événement annulé est possible, mais nécessite une
  nouvelle confirmation des participants ; ne pas restaurer silencieusement
  leurs inscriptions. Les contrôles de capacité et d’horaire s’appliquent à nouveau.
- Liste d’attente automatique hors engagement.

## Dépendances et calcul d’impact

Une dépendance est une relation métier déclarée par formulaire entre ateliers
du même événement. Convention : **A → B signifie que B dépend de A**.

Exemple : Cuisine → Dégustation → Débrief. Un changement de Cuisine impacte
les inscrits des trois ateliers. Une autre branche Poterie → Vernissage reste
épargnée. Une personne inscrite à plusieurs ateliers n’est comptée qu’une fois.

- Le BFS parcourt les dépendances à partir de l’atelier modifié.
- Seules les participations confirmées et inscriptions actives alimentent le graphe.
- Une dépendance propage l’information ; elle ne décale pas les horaires et
  n’annule pas automatiquement les ateliers dépendants.
- Refuser les liens vers soi-même, un autre événement ou créant un cycle dans
  l’interface ; conserver les tests de robustesse aux cycles dans le moteur.
- Avant confirmation : afficher ancienne/nouvelle valeur, ateliers impactés,
  destinataires uniques, personnes épargnées et raison directe/cascade/globale.
- Recalculer côté serveur à la confirmation.
- Ajouter ou retirer une dépendance recalcule aussi les destinataires et contenus
  encore en attente : inclure les nouveaux concernés et retirer les informations
  devenues non pertinentes. Ne pas réécrire les messages déjà transmis.
- Ce recalcul ne doit pas redémarrer les fenêtres existantes ni produire de doublons.

## Changements, fusion et annulations

- Historique durable : auteur, date, ancienne/nouvelle valeur, événement/atelier
  et liens vers les notifications produites.
- Valeur identique à la valeur actuelle : aucune notification.
- Fenêtre fixe de 60 secondes par défaut, configurable, ouverte au premier
  changement et non repoussée par les suivants.
- Fusion par personne et par événement ; ne pas mélanger deux événements.
- Même champ : dernière valeur ; plusieurs champs/ateliers : contenu cohérent commun.
- Retour à la valeur initiale avant envoi : conserver l’historique, retirer
  l’information sans changement net et ne rien envoyer s’il ne reste aucun autre
  changement pertinent. Ne pas compter ce cas comme un envoi effectué.
- Annulation : disponible au prochain passage du worker, sans attendre la fenêtre,
  en respectant le quota global ; supprimer les informations caduques du même atelier
  dans les groupes et messages non envoyés.
- Groupe mixte : envoyer l’annulation immédiatement, conserver les changements
  indépendants des autres ateliers en attente jusqu’à leur échéance initiale.
- Si un message est déjà transmis, envoyer l’information corrective nécessaire ;
  ne pas prétendre rappeler l’e-mail.
- Revérifier participation, inscriptions et pertinence avant l’envoi.

## Envois et reprise durable

- Un seul ordonnanceur, priorité annulation puis horaire puis information mineure.
- Limiteur fournisseur global ; continuer lorsque le navigateur est fermé tant
  que le serveur fonctionne.
- Une seule tentative automatique par e-mail, aucun réessai automatique.
- Conserver tentative, résultat/erreur et identifiant fournisseur ; un échec
  d’e-mail laisse la notification interne consultable.
- Relance manuelle après échec confirmé, réservée à l’organisateur autorisé,
  tracée, protégée contre doubles clics et soumise au débit.
- Résultat incertain : vérifier auprès du fournisseur avant une relance.
- Persister groupes, échéances, file, contenu/révision et tentatives au cycle 2.
- Après redémarrage : reprendre les échéances existantes et le quota récent ;
  ne pas retenter automatiquement un envoi commencé, terminé ou échoué.
- L’étudiant ne dispose actuellement que de son adresse personnelle : aucun
  fournisseur, domaine ou expéditeur validé n’est disponible. Choix et
  configuration du fournisseur restent à effectuer, sans achat.
- Mailer API HTTPS pour le réel, Mailer mémoire pour les tests ; ne jamais envoyer
  aux adresses fictives `example.test`.
- Distinguer simulation, acceptation par le fournisseur et réception démontrée.

## Interface et preuves

- Espaces super-admin, organisateur et participant avec navigation selon les droits.
- Espace participant : invitations, événements confirmés, ateliers, planning et
  notifications avec état lu/non lu.
- Bordeaux sombre et mat ; thème clair blanc cassé/noir doux et thème nuit
  noir doux/cartes gris sombre, préférence mémorisée et thème système au premier accès.
- Graphe consultable : source, cascade et branches épargnées ; édition par formulaires.
- Journal et boîte actualisés périodiquement sous 3 secondes lorsque le serveur fonctionne.
- Compteurs fondés sur la base ; économies calculées sur les groupes fermés.
- Recherche, filtres, CSV protégés et archivage en lecture seule.

La palette exacte et les trois écrans sont documentés dans
[maquettes/README.md](maquettes/README.md). Les valeurs choisies suivent la
direction artistique confirmée : fond blanc cassé/noir doux, cartes blanches/gris
très sombre, texte presque noir/blanc cassé et boutons bordeaux mat/éclairci.

Cycle 1 : créer un événement depuis le site, définir ses ateliers et dépendances,
inviter trois personnes, montrer acceptation/refus/attente, modifier un atelier,
observer ciblage/fusion et recevoir le vrai e-mail, avec journal et version v0.1.

Cycle 2 : démontrer espace participant, capacités/conflits, annulations, reprise,
relance manuelle, graphe/thèmes, exports et archivage ; livrer documentation,
vidéo de secours et v1.0. Hébergement seulement si une offre gratuite convient.

## Parcours par rôle

1. **Super-admin** : initialiser son compte par commande, se connecter, inviter un
   organisateur, suivre l’invitation puis pouvoir révoquer une invitation ou
   désactiver un accès. Le rôle est attribué côté serveur.
2. **Organisateur** : accepter son invitation, définir son mot de passe, créer
   un événement, ses ateliers et leurs dépendances, publier, inviter depuis le
   carnet commun, suivre les réponses, prévisualiser/confirmer un changement et
   consulter le journal. Les coorganisateurs n’accèdent qu’aux événements autorisés.
3. **Participant invité** : ouvrir le lien sans modifier sa réponse, retrouver
   son compte ou le créer, choisir ses ateliers et accepter/refuser explicitement ;
   après acceptation, retrouver ses événements et notifications par connexion habituelle.
4. **Participant venant du catalogue** : découvrir un événement ouvert, créer
   son compte si nécessaire, demander à participer, attendre l’approbation puis
   accéder aux inscriptions actives. Une invitation personnelle peut remplacer
   ce parcours pour une personne ciblée par l’organisateur.

## Livrables C1-01 au 15 octobre

- Règles, états et parcours : présent document.
- Trois maquettes interactives : [maquettes/index.html](maquettes/index.html).
- Palette, fonctionnement et limites : [maquettes/README.md](maquettes/README.md).
- Scénario des maquettes et recette visée : [SCENARIO_DEMO.md](SCENARIO_DEMO.md).
- Captures et contrôles navigateur : voir le compte rendu des maquettes.

Ces livrables sont disponibles localement pour revue ; le statut GitHub n’a pas
été modifié et ils n’ont pas été publiés ou poussés. Les fonctionnalités décrites
restent à développer et à vérifier côté serveur selon les critères des issues.

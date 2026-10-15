# ImpactFlow — scénario de démonstration

Cadrage C1-01, 15 octobre 2026. Ce scénario distingue la présentation des
maquettes disponibles de la recette du futur site. Un parcours décrit ici
n’est pas une fonctionnalité livrée tant que sa preuve n’a pas été obtenue.

## Événement de référence

**Les Rencontres créatives**, Les Ateliers du Port à Nice, jeudi 22 octobre
2026 de 14 h à 18 h, heure de Paris. Thomas Mercier en est le responsable.
Les identités et les lieux sont des fixtures fictives ; les adresses de test
utilisent exclusivement le domaine réservé `example.test`.

| Atelier | Créneau | Capacité | Dépendance d’impact |
|---|---|---:|---|
| Cuisine de saison | 14–15 h | 12 | Source de Dégustation |
| Dégustation partagée | 15–16 h | 18 | Dépend de Cuisine ; source d’Accords |
| Accords & échanges | 16–17 h | 18 | Dépend de Dégustation |
| Initiation à la poterie | 14–15 h 30 | 10 | Source de Vernissage |
| Vernissage des créations | 16–17 h | 20 | Dépend de Poterie |
| Balade photographique | 14–15 h | 12 | Indépendant |

La flèche A → B signifie que B dépend de A. Elle propage l’information et
ne réécrit pas les horaires de B.

| Personne | État initial | Ateliers actifs |
|---|---|---|
| Alice Martin | Invitation en attente | Aucun ; Cuisine et Dégustation proposées |
| Sofia Bernard | Participation confirmée | Cuisine |
| Mehdi Benali | Participation confirmée | Dégustation |
| Lina Moreau | Participation confirmée | Accords |
| Nora Petit | Participation confirmée | Poterie |
| Hugo Laurent | Participation confirmée | Vernissage |
| Emma Robert | Participation confirmée | Photo |
| Alex Dubois | Participation confirmée | Aucun |
| Bruno Lefèvre | Invitation refusée | Aucun |
| Chloé Garcia | Invitation en attente | Aucun |

Au départ : **7 participants confirmés**, **2 invitations en attente**,
**1 refus**, **6 ateliers**, **0 e-mail envoyé**.

## Présenter les maquettes actuelles

Ouvrir [la maquette](maquettes/index.html). Les actions restent en mémoire
dans ce navigateur ; un rechargement les efface. La barre supérieure permet
de changer de parcours, sans constituer une véritable connexion par rôle.

1. **Organisation** : montrer le programme, les réponses et la cascade Cuisine →
   Dégustation → Accords. Avant la réponse d’Alice, Cuisine concerne Sofia,
   Mehdi et Lina : **3 personnes sur 7**, **4 épargnées**.
2. **Invitation** : ouvrir l’invitation d’Alice. La simple consultation maintient
   son état en attente. Choisir Cuisine et Dégustation puis accepter.
   Les créneaux adjacents sont autorisés.
3. **Mon espace** : retrouver la participation confirmée d’Alice et ses deux
   ateliers dans son planning. La boîte ne prétend pas qu’un e-mail est parti.
4. **Organisation** : vérifier **8 participants confirmés**, **1 attente**
   (Chloé), **1 refus** (Bruno). Cuisine concerne **Alice, Sofia, Mehdi et Lina**,
   soit **4 personnes uniques sur 8** ; Alice n’est pas comptée deux fois.
5. Sélectionner Poterie : **Nora et Hugo** sont concernés. Sélectionner Photo :
   **Emma seule** est concernée. La personne sans atelier, Alex, reste épargnée
   pour ces changements d’atelier.
6. Créer un changement sur Cuisine de 14 h à 14 h 10. Montrer ancienne/nouvelle
   valeur, destinataires directs/en cascade et personnes épargnées. Le maintien
   de la durée décale la fin à 15 h 10 : le conflit avec la Dégustation d’Alice
   est signalé, ses inscriptions sont conservées.
7. Confirmer : le journal local conserve le changement ; Mon espace montre
   un **aperçu non envoyé** pour Alice.
8. Ramener Cuisine à 14 h : les deux changements restent dans le journal,
   mais l’aperçu à envoyer disparaît puisque la valeur initiale est restaurée.
9. Basculer clair/nuit, vérifier le rendu sur téléphone et recharger : le thème
   reste choisi et les données fictives reviennent à l’état initial.

Variante refus : après rechargement, décliner l’invitation d’Alice. Les
participants confirmés restent au nombre de 7 et Alice n’a aucun atelier actif.

Variante conflit : sélectionner Cuisine et Poterie avant d’accepter. Le
chevauchement bloque l’acceptation et invite à corriger les choix.

## Recette visée pour la soutenance du cycle 1

Objectif : **environ quatre minutes**, en dehors de l’attente de regroupement.
Utiliser les vraies routes, le serveur et la base, pas la maquette.

| Étape | Action et résultat attendu | Preuve |
|---|---|---|
| Préparation | Vérifier CI, démarrage, comptes, boîtes contrôlées et fournisseur ; configurer une fenêtre courte explicitement annoncée si nécessaire | Commandes reproductibles et configuration sans secret |
| 1 | Depuis l’interface, créer et publier l’événement, ses ateliers et dépendances | Données enregistrées ; aucune modification de JSON |
| 2 | Inviter trois personnes via des adresses réellement contrôlées ; une accepte et choisit ses ateliers, une refuse, une reste en attente | Invitation reçue et réponses persistantes |
| 3 | Prévisualiser un changement de salle de Cuisine | Bons destinataires directs/en cascade, refus et attente exclus, branches indépendantes épargnées |
| 4 | Confirmer puis corriger deux fois dans la même fenêtre | Historique complet ; une notification finale cohérente par personne concernée |
| 5 | Fermer la page organisateur pendant le traitement | Le worker continue tant que le serveur fonctionne |
| 6 | Montrer le journal et la boîte e-mail réelle | Contenu final, priorité, état et identifiant fournisseur ; réception démontrée séparément |
| 7 | Relancer l’application | Événements, participants et historique métier retrouvés ; reprise des groupes en attente réservée au cycle 2 |

Pour la séquence de fusion déterministe en tests : t=0 salle A → B,
t=20 salle B → C, t=50 ajout d’une autre information pertinente ; échéance
fixe à t=60. Sur quatre destinataires, cela représente **12 demandes**,
**4 notifications finales**, **8 notifications évitées**, une fois les groupes
fermés. Ne pas annoncer ces chiffres sans les retrouver sur les données réelles.

Les fixtures `example.test` ne doivent jamais déclencher d’appel au fournisseur.
La preuve externe utilise des boîtes contrôlées avec des adresses configurées
privément. Ne pas publier leurs adresses, les liens personnels ou les jetons
dans les captures, le dépôt ou la vidéo.

## Compléments pour la soutenance finale

- Deux événements avec une personne commune : notifications séparées par événement.
- Changement global : tous les confirmés, y compris Alex sans atelier.
- Dernière place demandée simultanément : une seule inscription acceptée.
- Annulation pendant une fenêtre et après mise en file avec débit lent : priorité
  immédiate et aucun ancien message contradictoire transmis ensuite.
- Groupe mixte : annulation envoyée, changement indépendant conservant son échéance.
- Dépendance ajoutée/retirée : destinataires encore en attente recalculés.
- Arrêt pendant regroupement puis reprise : même échéance ; tentative interrompue
  marquée incertaine, sans nouvel essai automatique.
- Échec confirmé : notification interne conservée, relance manuelle tracée,
  double clic sans double envoi.
- Report d’événement : tous les ateliers décalés ; conflits signalés.
- Réactivation après annulation : nouvelle confirmation, sans restauration silencieuse.
- Exports protégés, archive en lecture seule, interface téléphone et deux thèmes.

## Déroulement de secours

Si l’hébergement gratuit ne convient pas, utiliser le serveur local et annoncer
ce mode explicitement. Si le fournisseur échoue pendant la soutenance, montrer
l’erreur conservée et la notification interne ; utiliser une vidéo anonymisée
d’un vrai envoi réalisé auparavant comme preuve complémentaire, en précisant
qu’il s’agit d’un enregistrement. Les maquettes servent à présenter les parcours,
pas à remplacer une preuve de fonctionnement du site.

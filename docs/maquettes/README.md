# Maquettes interactives — C1-01

Trois parcours locaux, sans installation ni dépendance externe :

1. Ouvrir [index.html](index.html) dans un navigateur.
2. Parcourir **Organisation**, **Invitation** et **Mon espace** dans la barre de démonstration.
3. Utiliser le bouton soleil/lune pour vérifier les deux thèmes.

Le rechargement réinitialise les données fictives. Seul le thème choisi est
conservé dans le stockage du navigateur. Le navigateur ne stocke aucun mot de
passe, aucune clé et aucune véritable donnée personnelle.

## Écrans et interactions

| Écran | Ce qui est consultable ou interactif |
|---|---|
| Organisation | Compteurs issus des fixtures, sélection de la source dans le graphe, programme, réponses, journal et aperçu avant confirmation d’un changement d’horaire |
| Invitation | Sélection libre d’ateliers, contrôle des chevauchements dans la session, acceptation/refus explicite ; la consultation seule ne change aucune réponse |
| Mon espace | Invitation en attente ou participation confirmée, planning des ateliers choisis, exemples de notifications à préparer |

Les cartes et les compteurs se mettent à jour lors des actions de la session.
Les horaires adjacents sont acceptés. Un changement d’horaire signale les conflits
existants ; il ne supprime pas les inscriptions. Un retour à l’horaire initial
conserve le journal et retire les aperçus de notification de cet atelier.

La barre supérieure est un outil de présentation des maquettes. Les trois
parcours accessibles sans connexion ne représentent pas la gestion des droits
de l’application future.

## Direction artistique

| Élément | Clair | Nuit |
|---|---|---|
| Fond | Blanc cassé `#f7f5f1` | Noir doux `#171619` |
| Cartes et formulaires | Blanc `#ffffff`, bordures `#e6e1df` | Gris très sombre `#211f23`, bordures `#3c353d` |
| Texte | Presque noir `#242124` | Blanc cassé `#f4f0eb` |
| Texte secondaire | `#70696d` | `#b4aab0` |
| Bouton principal | Bordeaux mat `#79364b` | Bordeaux éclairci `#a75c74` |
| Texte du bouton | Blanc `#ffffff` | Blanc `#ffffff` |
| Sélections | Fond `#f4e9ed`, texte `#79364b` | Fond `#382730`, texte `#e3adc0` |

Les contrastes calculés pour le texte blanc des boutons sont de **8,60:1**
en clair et **4,74:1** en nuit. Le texte secondaire atteint **4,91:1** sur le
fond clair et **7,25:1** sur les cartes nuit. Ces calculs ne constituent pas
un audit d’accessibilité complet.

Police système, sans téléchargement ; icônes SVG intégrées ; couleurs
accompagnées de libellés ; navigation clavier, lien d’évitement et focus visibles.
Le thème système est utilisé au premier accès, puis la préférence est mémorisée
si le stockage du navigateur est disponible.

## Données et limites

Les fixtures sont détaillées dans [SCENARIO_DEMO.md](../SCENARIO_DEMO.md).
Les ensembles d’impact de la maquette sont scénarisés dans `app.js` ; le futur
site appellera le BFS Python existant avec les données persistantes.

Aucune base SQL, authentification, invitation envoyée, transaction concurrente,
fenêtre de fusion, file persistante ou intégration fournisseur n’est implémentée
par ces écrans. Les exemples de notifications sont des aperçus non envoyés.
Les contrôles dans le navigateur servent uniquement à illustrer les parcours ;
les véritables contrôles devront être imposés par le serveur.

Le catalogue public, la création de compte, le super-admin, la gestion des
coorganisateurs et les formulaires de création d’événement seront développés
dans les tâches correspondantes ; ils ne font pas partie des trois maquettes
demandées par C1-01.

## Vérification du 15 octobre 2026

Contrôles réalisés avec Chrome en mode sans fenêtre, sur les fichiers locaux,
à 1440 × 1060 et 390 × 844 : **26 vérifications réussies**, aucune exception
JavaScript observée. Les trois parcours ne débordent pas horizontalement sur
téléphone. Acceptation/refus, chevauchement, déduplication, sources indépendantes,
aperçu, retour à l’horaire initial et persistance du thème ont été exercés.
Les ressources chargées sont locales, sans requête vers un fournisseur.

La syntaxe JavaScript passe `node --check`. Les **92 tests Python** existants
et **Ruff** passent également. Cela vérifie les maquettes et l’absence de
régression du moteur ; cela ne valide pas le futur backend.

Captures produites pendant cette vérification :

- [Organisation, clair](apercus/organisateur-clair.png)
- [Invitation, clair](apercus/invitation-clair.png)
- [Espace participant, clair](apercus/participant-clair.png)
- [Organisation, nuit](apercus/organisateur-nuit.png)
- [Organisation sur téléphone, nuit](apercus/organisateur-mobile-nuit.png)
- [Invitation acceptée sur téléphone, nuit](apercus/invitation-mobile-nuit.png)
- [Espace participant sur téléphone, nuit](apercus/participant-mobile-nuit.png)

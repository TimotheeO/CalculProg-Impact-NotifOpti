# ImpactFlow — démonstration générale

Guide unique à mettre à jour au fil des fonctionnalités et des soutenances.
Passage principal de 8 à 10 minutes ; variantes et contrôles complémentaires
ci-dessous. Ce guide ne constitue pas une preuve de répétition humaine réussie.

## Préparation avant le chronomètre

Le script prépare une base fictive séparée dans **`var/demo-seance-01`**.
Les Rencontres ont lieu le prochain jeudi, 14–18 h à Paris ; utiliser la date
affichée dans le programme. Un dossier déjà préparé conserve ses changements.
Arrêter ton éventuel ancien serveur sur 8000 avec Ctrl+C dans son terminal.
Depuis `/home/timothee/Annee_3/Simulated/CalculProg-Impact-NotifOpti` :

```bash
# Terminal 1 : réutilise Mailpit s’il tourne déjà, sinon le démarre.
./scripts/mailpit.sh
```

```bash
# Terminal 2 : sélection explicite de la base de répétition.
DEMO_DIRECTORY=var/demo-seance-01 BATCH_WINDOW_SECONDS=60 ./scripts/run_prepared_demo.sh
```

Application : <http://127.0.0.1:8000> ; Mailpit : <http://127.0.0.1:8025>.
Le terminal doit annoncer `demo-seance-01/impactflow.sqlite3`, fenêtre **60 s**,
débit **1 tentative/s**. Aucun serveur n’a été démarré par la préparation du guide.

Ouvrir Chrome normal pour **Thomas** (`demo-thomas@example.test`) et une fenêtre
privée pour **Alice** (`demo-alice@example.test`). Mot de passe des deux comptes
fictifs : **`Demo-ImpactFlow-2026!`**. Les onglets ordinaires partagent leur session.
Préparer Les Rencontres créatives, son Journal et envois, Mailpit et Mon espace
d’Alice. Garder ce guide à côté et lancer un chronomètre au début du passage.

Les Rencontres commencent avec **8 confirmés et 6 ateliers**. Aucun nouveau
changement/envoi n’est préchargé. Mailpit peut contenir tes anciens messages :
vérifier le destinataire et la date/heure des nouveaux courriers sans supprimer
les anciens. Ne pas accepter de nouvelle invitation avant l’étape 7.

## Passage à refaire dans cet ordre

### 1 — 0:00 à 0:40 : le problème

Dire avec tes mots : « Dans un événement avec plusieurs ateliers, un changement
ne concerne pas forcément tout le monde. Je calcule les conséquences sur le
programme, cible les inscrits concernés et regroupe leurs messages. »
Annoncer que les comptes et le programme sont préparés ; les changements et
messages suivants seront produits en direct.

### 2 — 0:40 à 1:20 : le programme

Montrer les 8 confirmés, les 6 ateliers et Dépendances. Expliquer A→B : B attend
la fin de A. Cuisine→Dégustation→Accords, plus Cuisine→Accords, forme un diamant ;
Poterie est sur une branche distincte.
Attendu : Cuisine 14–15, Dégustation 15–16, Accords 16–17 ; Poterie finit à 15:30,
Vernissage commence à 16:00. Alice fait Cuisine et Dégustation.

### 3 — 1:20 à 2:00 : une salle reste locale

Cuisine → Modifier → remplacer seulement `La Cuisine` par `Salle B` → Vérifier.
Attendu : **2 destinataires, 6 épargnés** ; Alice et Sofia, sans Mehdi ni Lina.
Dire : « Une salle est une information locale ; faire un atelier dépendant ne
rend pas cette information utile. » **Ne pas confirmer.** Reprendre la saisie
et remettre `La Cuisine` pour conserver les chiffres de fusion ci-dessous.

### 4 — 2:00 à 3:00 : deux changements, un résultat final

Garder le début à 14:00 ; passer seulement la fin à **15:10**, puis vérifier.
Attendu : Dégustation **15:10–16:10**, Accords **16:10–17:10**, **4 destinataires
uniques et 4 épargnés**. Confirmer et noter l’heure de cette confirmation.
Immédiatement revenir sur Modifier, passer la fin à **15:20**, vérifier et
confirmer **moins de 60 s après la première confirmation**. Utiliser le formulaire
actualisé, pas un ancien onglet ouvert avant la première modification.

Attendu après confirmation : Cuisine **14:00–15:20**, Dégustation **15:20–16:20**,
Accords **16:20–17:20** réellement enregistrés. Dire : « Les créneaux sont adjacents,
donc le retard se transmet. Je conserve les durées, confirme tout le plan dans une
transaction et ne compte Alice qu’une fois. » Les économies restent à zéro tant
que les groupes ne sont pas fermés.

### 5 — 3:00 à 4:10 : une marge absorbe le retard

Pendant l’attente, Poterie → Modifier → fin **15:45** → Vérifier, **sans confirmer**.
Attendu : **Vernissage inchangé, 16:00–17:00 ; Nora seule concernée**.
Revenir à la version enregistrée.
Dire : « La marge absorbe le retard, donc Hugo n’est pas prévenu. Une fin de Poterie
à 16:15 ne déplacerait Vernissage que de 15 minutes. Le BFS trouve les candidats,
puis l’ordre topologique calcule les conséquences après tous leurs prérequis. »
Expliquer aussi : « La fenêtre fixe démarre au premier changement ; elle n’est
pas repoussée. L’historique conserve les étapes, le message conserve le résultat final. »

### 6 — 4:10 à 5:20 : vérifier les messages

Attendre **60 s depuis la première confirmation**, puis quelques secondes pour
les 4 tentatives à 1/s et le rafraîchissement du journal. Le temps dépend des
confirmations réelles, pas seulement du chronomètre de présentation.
Attendu : **8 demandes naïves → 4 messages finaux → 4 évités**.

Dans Mailpit, montrer les nouveaux messages : Alice voit Cuisine finir à **15:20**
et Dégustation **15:20–16:20** ; Lina voit Accords **16:20–17:20**, avec la cause
de la cascade. Aucun horaire intermédiaire à 15:10 ni changement de salle.
Nora ne reçoit pas ce changement. Dans la session privée d’Alice, actualiser Mes
notifications, montrer le même contenu final et le marquer comme lu.
Dire : « Mailpit prouve une transmission SMTP locale, pas une réception Gmail.
La notification dans le site persiste également. »

### 7 — 5:20 à 7:40 : création et invitation

Organisation → brouillon **Festival des savoir-faire** → créer l’atelier
`Découverte`, salle `Espace démo`, capacité `5`, **le jour affiché du brouillon**,
de **14:00 à 15:00**. Montrer le calendrier français/cadran 24 h, puis l’atelier
enregistré dans le programme. Revenir aux Rencontres.

Invitations → sélectionner **Noé Laurent** → envoyer. Ouvrir le nouveau courrier
de Noé dans Mailpit. Déconnecter Alice dans la session privée ; y ouvrir le lien
de Noé, créer son compte et sélectionner Cuisine + Dégustation avant d’accepter.
Le mot de passe fictif peut être `Demo-ImpactFlow-2026!`.
Attendu : ouvrir le lien seul ne confirme rien ; accepter crée ses inscriptions.
Chez Thomas, **9 confirmés**, Noé apparaît. Les chiffres de l’étape 6 étaient
mesurés avant cette nouvelle admission.

Si tu dépasses le temps, montrer l’envoi et le formulaire sans accepter, puis
terminer l’acceptation hors chronomètre. Pour t’entraîner au refus, le lien de
Julie dans `var/demo-seance-01/invitations.html` permet ensuite de refuser
sans créer de compte ; utiliser la session participante déconnectée.

### 8 — 7:40 à 9:00 : annulation et limites

Cuisine → Modifier → état Annulé → Vérifier. Attendu : Dégustation et Accords
également annulés dans le plan ; Poterie épargnée. **5 destinataires si Noé a
accepté, sinon 4**. Dire : « Annuler le prérequis rend la suite impossible :
j’annule les dépendants, en conservant les inscriptions et l’historique. »
Confirmer **en dernier** et ouvrir Dégustation : état Annulé. Les messages
attendent encore leur fenêtre dans cette version ; les vérifier après le passage.
Le départ immédiat et la réactivation avec nouvelle confirmation restent au cycle 2.

Présenter les limites restantes : parcours participant complet, reconfirmation,
reprise/relance aboutie, graphe visuel, exports et archivage. Les choix et comparaisons utiles figurent dans les questions ci-dessous
et dans le [README](../README.md#architecture-et-choix).

## Refaire le passage et tester les erreurs

Relancer 01 conserve tes changements et annulations. Pour repartir du même état,
arrêter seulement ton serveur et choisir un **nouveau dossier**, 02 puis 03… :

```bash
DEMO_DIRECTORY=var/demo-seance-02 BATCH_WINDOW_SECONDS=60 ./scripts/run_prepared_demo.sh
```

Ne pas supprimer tes bases. Pour la soutenance, préparer encore un dossier neuf.
Les liens préchargés sont dans le dossier choisi, expirent après 48 h et ne doivent
pas être mélangés avec ceux d’une autre base. Mailpit peut rester ouvert.

Hors chronomètre, dans une nouvelle copie : tenter Accords→Cuisine (boucle refusée)
et une fin de Cuisine à **16:10** (cascade au-delà de 18:00 : refus complet sans
modification partielle). Une répétition humaine n’est pas remplacée par les tests.
Si l’aperçu diffère de l’attendu, arrêter avant confirmation et relever le premier écart.

## Contrôles complémentaires

Dans une nouvelle copie, essayer aussi :

- Cuisine + Poterie à l’inscription : chevauchement refusé ; Cuisine + Dégustation
  adjacent autorisé. Atelier complet : refus sans inscription partielle.
- Thomas ouvre `/organisateur/evenements/demo-fabrique` : 404 ; le carnet partagé
  ne donne pas les droits sur l’événement de Léa. Un participant ne peut pas ouvrir l’admin.
- Confirmer fin Cuisine 15:10, puis reporter l’événement d’un jour avant l’envoi :
  les messages doivent afficher les nouvelles dates réelles des ateliers.
- Ouvrir un formulaire puis modifier son programme/dépendances dans un autre
  onglet : confirmation refusée avec 409, nouvel aperçu nécessaire.
- Deux changements de salle puis retour à la salle initiale avant envoi :
  historique conservé, aucun message pour ce champ.
- Après traitement, redémarrer sur la même base : programme, réponses et état lu
  conservés ; aucun réessai automatique des courriers déjà tentés.

En cas d’erreur, conserver la base et les messages du terminal ; ne pas la
réinitialiser pour masquer le problème. Les scénarios indépendants utilisent
des dossiers distincts pour retrouver les mêmes effectifs de départ.

## Retour après ta répétition

```text
Durée totale :
Dernière étape terminée :
Deux changements Cuisine confirmés en moins de 60 s : oui/non
Compteurs avant l’invitation de Noé :
Écran et compte utilisés lors du problème :
Action précise et valeurs saisies :
Résultat attendu / résultat observé :
Heure et message d’erreur éventuel :
Passage que je n’arrive pas encore à expliquer :
```

Conserver la base et le terminal serveur en cas de problème. Une capture de
l’écran concerné et les lignes d’erreur aideront à reproduire le cas.


## Comptes, données et autres parcours

Les accès complets sont générés dans `var/demo-seance-01/ACCES_DEMO.md`, les liens
préchargés dans `invitations.html`. Ces liens n’ont pas été envoyés et ne remplacent
pas la preuve SMTP de l’invitation de Noé. Usage unique, expiration 48 h.

| Compte fictif | Parcours complémentaire |
|---|---|
| `admin.demo@example.test` | Super-admin : inviter/révoquer un organisateur, désactiver un accès |
| `demo-lea@example.test` | Coorganisatrice des Rencontres ; responsable de La Fabrique |
| `demo-nora@example.test` | Participante épargnée lors d’un changement Cuisine |
| `demo-alex@example.test` | Confirmé sans atelier aux Rencontres : concerné par un changement global |
| `demo-chloe@example.test` | Compte existant, invitation aux Rencontres et demande à La Fabrique |

Même mot de passe fictif que Thomas/Alice. Camille et Julie n’ont pas de compte
avant réponse ; Chloé conserve son mot de passe/rôle en acceptant. La Fabrique est
ouverte le lendemain ; Festival est un brouillon pour la création en direct.

Pour démontrer l’événement global, après le scénario principal dans une autre
copie initiale, modifier le lieu de l’événement entier : huit confirmés concernés,
y compris Alex. Pour les capacités/conflits/droits, utiliser les contrôles complémentaires ci-dessous.

## Parcours depuis une base vide

Pour une présentation centrée sur la création, préparer un autre fichier sans
charger le seed. Depuis le dépôt, avec l’environnement installé :

```bash
export DATABASE_URL="sqlite:///$PWD/var/demo-vide-01/impactflow.sqlite3"
venv/bin/python -m app.cli init-db
venv/bin/python -m app.cli create-super-admin --email admin@example.test --name "Admin démonstration"
./scripts/run_demo.sh
```

Mailpit doit tourner dans l’autre terminal. Le mot de passe admin est saisi
localement, deux fois ; il n’existe pas de valeur par défaut sur une base vide.
Ne pas démarrer simultanément le serveur de base prête et celui-ci sur 8000.

1. Inviter un organisateur depuis l’admin ; ouvrir son courrier Mailpit dans
   une autre session, confirmer le compte puis créer un événement ouvert 14–18 h.
2. Créer Cuisine 14–15, Dégustation 15–16, Accords 16–17 et Poterie 14–15:30.
   Ajouter les liens et publier. Montrer le catalogue, puis les invitations.
3. Ajouter des contacts fictifs via le carnet, inviter Alice et Nora ; accepter
   Cuisine+Dégustation pour Alice, Poterie pour Nora. Inviter Bruno et Chloé ;
   refuser Bruno sans compte, garder Chloé en attente.
4. Refaire le changement de fin Cuisine 15:10 puis 15:20 dans la fenêtre :
   avec Alice seule sur cette branche, **2 demandes → 1 message → 1 évité**.
   Les effectifs du parcours principal ne s’appliquent pas à cette petite base.

Ce parcours complet prend davantage de temps ; préparer les réponses avant le
passage si nécessaire et annoncer clairement ce qui était préparé.

## Questions à préparer à l’oral

| Question | Explication et comparaison |
|---|---|
| BFS plutôt que DFS ? | Les deux donnent l’accessibilité ; BFS existe déjà et est testé. Le tri topologique calcule ensuite les horaires après tous les parents. |
| Pourquoi un graphe ? | Les liens déclarés décrivent les cascades ; une liste fixe oublierait leurs évolutions. |
| Pourquoi une fenêtre fixe ? | Contrairement au debouncing, des changements continus ne repoussent pas indéfiniment l’échéance. |
| SQLite plutôt que PostgreSQL ? | Transactions locales sans serveur supplémentaire ; PostgreSQL à réexaminer pour plusieurs instances/concurrence accrue. |
| Worker local plutôt que Celery ? | Un processus suffit au périmètre local, sans Redis ; une distribution ajouterait exploitation et coordination. |
| Pourquoi pas de réessai automatique ? | Après un résultat incertain, le transport peut avoir accepté le message : un réessai peut doubler l’envoi. |
| Mailpit prouve quoi ? | La transmission SMTP et le courrier final capturé localement, pas la réception externe ni l’antispam. |
| Quel bénéfice mesuré ? | Ici 8→4 messages, 4 évités ; un test métier vérifie 18→6. Aucun benchmark de charge comparatif revendiqué. |

Le [README](../README.md) rassemble architecture, configuration, vérifications
et état du projet ; les rapports datés restent dans docs/preuves.

## Dépannage et solution de secours

| Problème | Contrôle/action |
|---|---|
| Port 8000 occupé | Arrêter le serveur précédent dans son propre terminal puis relancer avec la base choisie |
| Mailpit indisponible | Vérifier le terminal 1 et le binaire ; installation dans le README |
| Aucun courrier | Vérifier Mailpit, fenêtre/débit, état du journal et bonne base ; après un échec, aucun réessai automatique |
| Compteurs différents | Vérifier confirmations dans la fenêtre, invitations acceptées, autres changements confirmés et réutilisation d’une base |
| Ancien formulaire refusé | Recharger le programme et refaire l’aperçu ; ne pas contourner la révision |
| Lien expiré/utilisé | Utiliser le dernier courrier de la bonne base ; renvoyer explicitement une invitation si nécessaire |

Si l’application est indisponible, expliquer le schéma de développement et utiliser
la [vidéo historique de secours](preuves/cycle-1/secours-cycle1.webm) en annonçant
sa date et ses limites : montage de captures du 22 octobre, pas vidéo continue,
ni preuve du ciblage corrigé le lendemain. Aucun PNG indépendant n’est conservé.
Le moteur peut aussi être montré avec `venv/bin/python cli.py` : temps et envois
simulés, graphe générique distinct des règles de planning du site.

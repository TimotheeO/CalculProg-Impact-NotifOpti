# ImpactFlow — démonstration générale

Guide unique des deux cycles, à mettre à jour au fil des répétitions.
Passage principal : **8 à 10 minutes**. Les contrôles complémentaires utilisent
le même guide, hors chronomètre et dans une nouvelle base.

## Préparer avant le chronomètre

Depuis `/home/timothee/Annee_3/Simulated/CalculProg-Impact-NotifOpti`, arrêter
l’ancien serveur avec Ctrl+C dans son terminal. Ne pas supprimer ses données.

```bash
# Terminal 1 : conserve Mailpit et ses anciens messages s’il tourne déjà.
./scripts/mailpit.sh
```

```bash
# Terminal 2 : une nouvelle copie fictive ; changer 01 en 02 pour recommencer.
DEMO_DIRECTORY=var/demo-cycle2-01 BATCH_WINDOW_SECONDS=60 ./scripts/run_prepared_demo.sh
```

- Application : <http://127.0.0.1:8000> ; Mailpit : <http://127.0.0.1:8025>.
- Utiliser **127.0.0.1**, pas localhost : les formulaires contrôlent l’origine.
- Vérifier dans le terminal : bonne base, fenêtre fixe **60 s**, **1 tentative/s**.
- Thomas dans Chrome normal, Alice dans Chrome privé. Toutes les fenêtres
  privées Chrome partagent leur session ; utiliser un autre navigateur/profil
  pour conserver un troisième compte connecté.
- La base commence avec **8 confirmés, 6 ateliers**, sans changement ni envoi
  préchargé. Les Rencontres ont lieu le prochain jeudi, 14–18 h à Paris :
  utiliser les dates réellement affichées. Le brouillon est la semaine suivante.
- Un dossier déjà préparé conserve ses modifications. Choisir un nouveau
  dossier pour revenir au point de départ, sans écraser une ancienne répétition.

| Compte fictif | Adresse | Usage |
|---|---|---|
| Thomas | `demo-thomas@example.test` | Organisateur des Rencontres |
| Alice | `demo-alice@example.test` | Cuisine + Dégustation |
| Léa | `demo-lea@example.test` | Coorganisatrice ; responsable de La Fabrique |
| Nora | `demo-nora@example.test` | Branche Poterie, épargnée par Cuisine |
| Alex | `demo-alex@example.test` | Confirmé sans atelier, concerné par un changement global |
| Super-admin | `admin.demo@example.test` | Gestion uniquement, aucune participation |

**Mot de passe test commun : `Demo-ImpactFlow-2026!`.** Les accès complets sont
locaux dans `var/demo-cycle2-01/ACCES_DEMO.md`. Aucun compte personnel
supplémentaire n’est créé pour le super-admin. Les liens préchargés dans
`invitations.html` ne sont pas des preuves d’envoi ; ils expirent après 48 h.

Ouvrir le programme, son tableau de bord, son journal, Mailpit et l’espace d’Alice.
Les onglets d’une même session partagent le compte. Dans Mailpit, vérifier
l’heure et l’adresse : d’anciens messages peuvent être présents.

## Passage principal, dans cet ordre

### 1 — 0:00 à 0:45 : le problème et les rôles

Dire avec tes mots : « Un changement ne concerne pas forcément tout l’événement.
Je calcule les conséquences sur le programme, puis les personnes concernées,
et je regroupe leurs informations avant d’envoyer les messages. »
Montrer que Thomas organise et qu’Alice participe. Le super-admin gère les accès
organisateurs dans un espace distinct ; il ne participe pas avec ce compte.

### 2 — 0:45 à 1:30 : le graphe réel

Ouvrir **Tableau de bord et graphe**. Montrer les 8 confirmés et 6 ateliers.
Sélectionner Cuisine : Cuisine→Dégustation→Accords, plus Cuisine→Accords, forme
un diamant. Poterie→Vernissage constitue une autre branche ; Photo est indépendante.

A→B signifie que B attend la fin de A. Cuisine 14–15, Dégustation 15–16,
Accords 16–17 ; Poterie finit à 15:30, Vernissage commence à 16:00.
Les liens représentent des dépendances : l’aperçu d’un changement détermine
ensuite les conséquences réellement proposées.

### 3 — 1:30 à 2:10 : une salle reste locale

Cuisine → Modifier → remplacer seulement `La Cuisine` par `Salle B` → Vérifier.
Attendu : **2 destinataires, 6 épargnés**, Alice et Sofia. Le graphe de l’aperçu
montre uniquement la source modifiée. Mehdi et Lina sont épargnés.

**Ne pas confirmer.** Reprendre la saisie et remettre `La Cuisine` pour garder
les chiffres du scénario de fusion.

### 4 — 2:10 à 3:00 : deux changements, un résultat final

Garder le début à 14:00. Passer seulement la fin à **15:10**, puis vérifier.
Attendu : Dégustation 15:10–16:10, Accords 16:10–17:10,
**4 destinataires uniques**, et les deux conséquences sur le graphe.

Confirmer et noter l’heure. Revenir immédiatement sur Modifier, passer la fin
à **15:20**, vérifier et confirmer **moins de 60 secondes après la première
confirmation**. Utiliser le formulaire actualisé.

Attendu après enregistrement : Cuisine 14:00–15:20, Dégustation 15:20–16:20,
Accords 16:20–17:20. Les horaires sont réellement modifiés dans la base.
Expliquer : BFS trouve les candidats ; l’ordre topologique traite tous les
prérequis avant leurs dépendants. La durée des ateliers est conservée.

### 5 — 3:00 à 3:45 : la marge absorbe le retard

Pendant le regroupement, Poterie → Modifier → fin **15:45** → Vérifier,
**sans confirmer**. Attendu : Vernissage inchangé, 16–17 h ; **Nora seule**.
Revenir à la version enregistrée.

Dire : « Le retard est absorbé par la marge. Hugo n’est donc pas prévenu.
La fenêtre commence au premier changement et n’est pas repoussée. L’historique
garde les étapes, le message conserve le résultat final. »

### 6 — 3:45 à 5:00 : comparer le site et les e-mails

Attendre **60 secondes depuis la première confirmation**, puis les quatre
transmissions à 1/s. Actualiser le journal si nécessaire.
Attendu : **8 demandes naïves → 4 messages finaux → 4 évités**.
Ces compteurs sont mesurés avant les nouvelles opérations qui suivent.

Dans Mailpit : Alice voit Cuisine finir à 15:20 et Dégustation 15:20–16:20 ;
Lina voit Accords 16:20–17:20 et la cause de la cascade. Aucun 15:10 ni Salle B.
Nora ne reçoit pas ce changement. Dans la session d’Alice, montrer le même
contenu final et le marquer comme lu.

Dire : « Mailpit capture un véritable échange SMTP local. Ce contrôle ne prouve
pas une réception Gmail. Le message reste aussi dans le site si l’e-mail échoue. »

### 7 — 5:00 à 6:30 : inviter et laisser choisir

Chez Thomas : Invitations → sélectionner **Noé Laurent** → envoyer.
Ouvrir son nouveau courrier dans Mailpit. Déconnecter Alice dans la session
privée, puis y ouvrir le lien de Noé. Créer son compte avec le mot de passe
fictif et sélectionner Cuisine + Dégustation avant d’accepter.

Attendu : ouvrir le lien ne confirme rien ; accepter crée les inscriptions.
Chez Thomas : **9 confirmés**. Pour une création complète, utiliser ensuite
le brouillon Festival hors chronomètre, comme indiqué plus bas.

### 8 — 6:30 à 7:15 : annulation prioritaire

Cuisine → Modifier → Annulé → Vérifier. Attendu : Dégustation et Accords
également annulés, Poterie épargnée ; **5 destinataires si Noé a accepté**,
sinon 4. Confirmer.

L’annulation est prête au prochain passage du worker, **sans attendre 60 s**,
mais les cinq tentatives gardent le débit d’une par seconde. Montrer l’état
Annulé dans les ateliers et un nouveau courrier d’annulation.

Un ancien message non envoyé devenu caduc est écarté. Une information d’un
autre atelier conserve son échéance ; un message déjà transmis n’est pas rappelé.

### 9 — 7:15 à 8:30 : proposer la réactivation et reconfirmer

Cuisine → Modifier → Actif. Montrer l’option **Proposer aussi la réactivation
des ateliers dépendants annulés**, laissée **décochée** pour cette étape.
Vérifier puis confirmer. Dégustation et Accords restent annulés.

Déconnecter Noé dans la session privée, reconnecter Alice. Son espace signale
l’atelier réactivé à confirmer. Ouvrir ses choix, sélectionner Cuisine, confirmer
explicitement puis enregistrer. Les places et conflits sont vérifiés à nouveau.
Dire : « Réactiver n’a pas réservé automatiquement les anciennes places. »

### 10 — 8:30 à 10:00 : suivre et clôturer

Chez Thomas : **Participants et exports** → filtrer Alice ou un atelier →
télécharger un CSV. Les exports restent limités aux événements autorisés.

En dernier, annuler l’événement entier après confirmation : **9 confirmés
concernés**, même Alex sans atelier. Les invitations/demandes en attente sont
fermées. Archiver en recopiant le nom de l’événement. Montrer que le programme,
les participants et le journal restent consultables, avec modifications fermées.
Les envois dus peuvent encore terminer sous le débit ; les vérifier après le passage.

Si le chronomètre dépasse 10 minutes, terminer après l’export, puis montrer la
clôture hors chronomètre. Ne pas accélérer en sautant les confirmations.

## Contrôles complémentaires, hors chronomètre

Utiliser un **nouveau dossier** : `var/demo-cycle2-02`, puis 03… Arrêter le serveur
et relancer la commande de préparation avec ce dossier. Mailpit peut rester ouvert.
Ne pas accepter de nouvelles invitations avant de mesurer les 8→4→4.

| Contrôle | Manipulation et résultat attendu |
|---|---|
| Création depuis le site | Brouillon Festival → atelier Découverte, Espace démo, 5 places, 14–15 h **le jour affiché du brouillon** → calendrier français et cadran 24 h → enregistrer, publier, retrouver au catalogue |
| Compte organisateur | Depuis le super-admin, inviter une adresse fictive neuve, ouvrir le courrier dans Mailpit dans une session déconnectée, définir son mot de passe et confirmer son rôle |
| Invitation existante | Chloé accepte avec son propre compte ; mot de passe et rôle conservés. Julie peut refuser depuis le lien local, sans création de compte |
| Capacité/conflit | Choisir Cuisine + Poterie : chevauchement refusé avec atelier/horaire. Cuisine + Dégustation adjacent autorisé. Dernière place refusée si déjà prise |
| Retrait participant | Alice confirme sa désinscription d’un atelier ou de l’événement. Place libérée, planning et cibles en attente recalculés |
| Retrait organisateur | Participants et exports → Retirer cette personne → un atelier ou l’événement entier → confirmation ; autre atelier conservé si retrait ciblé |
| Reconfirmation globale | Annuler puis réactiver l’événement : anciennes participations à confirmer, aucune place réservée automatiquement. L’archive ne peut pas être réactivée |
| Graphe et données | Accords→Cuisine crée une boucle : refus. Une fin Cuisine à 16:10 dépasse 18 h après cascade : refus complet, aucun horaire partiellement enregistré |
| Contenu cohérent | Salle changée puis retour à sa valeur initiale avant envoi : historique conservé, aucun message pour ce champ. Reporter l’événement après un changement atelier affiche les dates finales réelles |
| Conflit créé par report | L’aperçu signale le conflit ; la notification participant l’indique également, sans supprimer ses inscriptions |
| Droits | Thomas ouvre La Fabrique ou son export : 404. Alice n’accède pas à l’admin. Super-admin sur `/espace` : 403. Aucun droit privé ne vient du carnet partagé |
| Formulaire périmé | Ouvrir deux formulaires, modifier le programme/dépendances dans l’autre onglet : ancien aperçu refusé avec 409 |
| Thèmes et mobile | Basculer soleil/lune, changer de page et recharger : préférence conservée. Vérifier à 390 px ; graphe défilable dans sa carte, boutons et formulaires utilisables |

### Récupération du mot de passe

Déconnecter le compte de la session de test. Connexion → Mot de passe oublié →
`demo-nora@example.test`. La réponse publique reste neutre. Ouvrir le nouveau
courrier dans Mailpit et son lien, choisir une nouvelle phrase de passe d’au
moins 15 caractères, puis se reconnecter.

Attendu : ancien mot de passe et anciennes sessions invalidés, lien utilisé
refusé, nouveau lien expirant après 30 minutes. Une nouvelle demande invalide
la précédente. Une adresse inconnue reçoit la même réponse publique sans e-mail.
Conserver le nouveau mot de passe localement pour cette base, ou utiliser une
nouvelle copie pour retrouver le mot de passe fictif initial.

### Échec et relance manuelle

Sur une base neuve avec serveur déjà démarré, arrêter **Mailpit uniquement**
avec Ctrl+C dans son terminal. Modifier le lieu de Poterie, confirmer et attendre
60 s. Le journal montre un échec confirmé `mailpit_unavailable` ; le message
final reste consultable dans l’espace de Nora.

Attendre encore : aucune tentative supplémentaire. Redémarrer `./scripts/mailpit.sh`,
puis Journal → Relance manuelle → Réessayer une seule fois. Attendu : ancien
échec conservé, une seconde tentative tracée avec son auteur, nouveau message
capturé, aucune troisième tentative au double clic. Après succès, plus de relance.

Pour un résultat **incertain**, ne pas cliquer aveuglément : vérifier auprès du
transport si le message a été accepté. Le formulaire exige cette vérification
et sa référence avant une nouvelle tentative. Les tests simulent l’interruption
pendant tentative ; ne pas provoquer une coupure brutale sur ta base de travail.

### Reprise et sauvegarde

Confirmer un changement Poterie ; attendre environ 20 s, arrêter seulement le
serveur, puis le relancer **sur la même base**. L’échéance reste celle du premier
changement : elle ne repart pas pour 60 s. Après transmission, un nouveau
redémarrage ne renvoie pas le même message. Les états lu/non lu persistent.

Les commandes de [sauvegarde et restauration](../README.md#sauvegarder-et-restaurer)
utilisent de nouveaux fichiers et contrôlent l’intégrité. Vérifier le chemin de
la base effectivement relancée. Conserver la base en cas d’écart.

## Support, secours et explications

La [préparation de livraison](../README.md#préparer-la-livraison-et-la-soutenance)
produit un ZIP local, `soutenance.html` et un manifeste SHA-256. La vidéo de
recette automatique est dans [demo-secours.webm](preuves/demo-secours.webm), intégrable dans
le ZIP. L’enregistrement continu conserve la fenêtre réelle de 60 s et le débit de
1 tentative/s. Durée de la vidéo de secours : environ 5 minutes. Elle montre des écrans réels et SMTP local ; elle ne remplace pas une
répétition humaine chronométrée ni une réception en boîte externe.

Pour expliquer les choix : BFS explore les candidats, ordre topologique pour
les effets réels, fenêtre fixe plutôt que debouncing, worker unique plutôt
qu’une infrastructure distribuée, historique des tentatives plutôt qu’une erreur
écrasée. Les alternatives et la décision d’hébergement sont dans le README.
Le moteur CLI et ses 92 tests préexistent ; distinguer ce socle des nouveaux
parcours web, de la persistance et des fonctions des deux cycles.

## Retour de répétition à renseigner

```text
Durée réelle du passage :
Dernière étape terminée :
Deux confirmations Cuisine dans la même fenêtre : oui/non
Compteurs avant invitation de Noé :
Écran, compte et action au premier écart :
Attendu / observé / message d’erreur / heure :
Passage technique difficile à expliquer :
Temps déclaré pour le cycle 2, hors campus compris : environ 3,5 jours-homme (à ajuster si nécessaire)
```

En cas d’écart : arrêter avant confirmation, conserver la base et relever le
premier problème avec les lignes utiles du terminal. Les tests et la vidéo
ne sont pas présentés comme une validation humaine ou une validation du staff.

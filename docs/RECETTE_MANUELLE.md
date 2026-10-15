# ImpactFlow — vérifier soi-même chaque étape

Mis à jour le 15 octobre 2026. Ce guide sert à constater l’avancement et à
préparer la soutenance. Chaque nouvelle tâche ajoute sa recette avec résultats
attendus, cas d’erreur et limites. Les choix sont expliqués dans
[DECISIONS_TECHNIQUES.md](DECISIONS_TECHNIQUES.md).

Les résultats d’une recette correspondent à la version décrite. Si un résultat
diffère, relever la commande, son message et la page concernée avant de corriger.

## C1-01 — Trois maquettes interactives

**Durée indicative :** 5 à 10 minutes. Aucun serveur requis.

Ouvrir [maquettes/index.html](maquettes/index.html) dans Chrome ou Firefox.

| Action | Résultat attendu |
|---|---|
| Ouvrir Organisation | 7 participants confirmés, 6 ateliers, 2 invitations en attente, 0 e-mail envoyé |
| Sélectionner Cuisine | 3 personnes sur 7 concernées ; cascade vers Dégustation et Accords |
| Ouvrir Invitation sans cliquer sur Accepter | Alice reste en attente, aucune place n’est réservée |
| Conserver Cuisine et Dégustation puis accepter | Participation confirmée dans la maquette ; les créneaux adjacents sont autorisés |
| Ouvrir Mon espace | Deux ateliers dans le planning d’Alice |
| Revenir à Organisation, sélectionner Cuisine | 8 confirmés au total ; 4 personnes uniques concernées, Alice comptée une seule fois |
| Créer le changement Cuisine 14 h → 14 h 10 | Aperçu des destinataires directs/en cascade et signalement du conflit d’Alice avec Dégustation |
| Confirmer puis ramener Cuisine à 14 h | Historique conservé, aperçu à envoyer retiré pour le retour à l’état initial |
| Basculer clair/nuit puis recharger | Thème conservé ; réponses et changements fictifs remis à zéro |

**Erreur à provoquer :** après rechargement, dans Invitation, cocher Cuisine
et Poterie puis accepter. Attendu : chevauchement signalé, Alice toujours en
attente. Retirer Poterie permet de corriger le choix.

**Limite :** la maquette fonctionne en mémoire et ne crée aucun compte ou
e-mail. Elle ne prouve pas la persistance du site ; celle-ci se vérifie ci-dessous.

## C1-02 — Application, base persistante et graphe

**Durée indicative :** 10 à 15 minutes, hors installation. Un seul terminal
suffit : arrêter le serveur avec `Ctrl+C` avant les commandes suivantes, puis
le relancer. Le navigateur peut rester ouvert.

### 1. Préparer une base isolée

Dans un terminal Bash :

```bash
cd /home/timothee/Annee_3/Simulated/CalculProg-Impact-NotifOpti
source venv/bin/activate
python --version
```

Attendu : Python **3.12.x**. Les dépendances sont déjà installées dans le venv
du poste actuel. Sur une nouvelle installation, utiliser au préalable
`python -m pip install -r requirements.txt`.

Créer un dossier temporaire différent à chaque nouvelle recette :

```bash
export IMPACTFLOW_RECETTE_DIR="$(mktemp -d /tmp/impactflow-recette-XXXXXX)"
export DATABASE_URL="sqlite:///$IMPACTFLOW_RECETTE_DIR/impactflow.sqlite3"
python -m app.cli init-db
```

Attendu : « Base initialisée ; schéma à jour ». Toutes les commandes de cette
recette doivent rester dans **ce même terminal** pour conserver `DATABASE_URL`.
La base habituelle `var/impactflow.sqlite3` n’est pas modifiée. Le dossier
temporaire n’est pas une sauvegarde durable.

### 2. Constater l’état vide, puis le chargement des données

```bash
python -m uvicorn app.main:app --port 8000
```

Ouvrir <http://127.0.0.1:8000> : attendu, message « Aucun événement ouvert ».
Arrêter le serveur avec `Ctrl+C`, puis charger les fixtures :

```bash
python -m app.cli seed-demo
python -m app.cli inspect
```

Attendu dans le JSON :

| Élément | Valeur |
|---|---|
| `events_in_database` | `2` |
| `confirmed_participants` des Rencontres | `8` |
| `workshops.w1.location` | `La Cuisine` |
| `impacted_workshops` | `w1`, `w2`, `w3` |
| `impacted_participants` | `demo-alice`, `demo-lina`, `demo-mehdi`, `demo-sofia` |
| `external_emails_sent` | `0` |

Les huit participations comprennent Alice déjà confirmée, contrairement à
l’état initial des maquettes. Bruno et Chloé ne sont pas dans l’impact.

Vérifier l’autre événement et la personne commune :

```bash
python -m app.cli inspect --event demo-fabrique --workshop fabrique-photo
```

Attendu : `confirmed_participants` vaut `1`, `impacted_workshops` contient
uniquement `fabrique-photo`, et `impacted_participants` uniquement `demo-alex`.
La notification d’exemple est dans le premier événement ; elle n’est pas un envoi réel.

### 3. Parcourir le vrai site

Relancer :

```bash
python -m uvicorn app.main:app --port 8000
```

| Page ou action | Résultat attendu |
|---|---|
| <http://127.0.0.1:8000> | Un événement public : La Fabrique du vendredi |
| Cliquer Découvrir l’événement | Programme avec Regards sur la ville, lieu de l’atelier « La Fabrique » |
| <http://127.0.0.1:8000/health> | `{"status":"ok","database":"ok"}` |
| <http://127.0.0.1:8000/events/rencontres-creatives> | Page 404 ; l’événement est sur invitation |
| <http://127.0.0.1:8000/page-inconnue> | Page 404 avec retour au catalogue |
| Changer le thème puis naviguer ou recharger | Préférence conservée |
| Réduire la fenêtre à environ 390 px, ou utiliser le mode téléphone des outils développeur | Lecture et boutons accessibles, sans débordement horizontal de la page |

Le 30 octobre, le programme affiche **14 h** pour un atelier stocké à **13 h UTC** :
la conversion Paris tient compte du changement d’heure.

### 4. Modifier, arrêter et retrouver la modification

Arrêter le serveur avec `Ctrl+C`. Modifier cette fois le lieu d’un atelier de
l’événement public pour pouvoir constater le résultat dans le navigateur :

```bash
python -m app.cli set-workshop-location --event demo-fabrique --workshop fabrique-photo --actor demo-lea --location "Salle Bordeaux"
python -m app.cli inspect --event demo-fabrique --workshop fabrique-photo
```

Attendu : message de changement conservé ; le JSON indique le lieu
« Salle Bordeaux » et un nouvel élément dans `changes` avec :

- `actor_id` : `demo-lea` ;
- `field` : `location` ;
- `old_value` : `La Fabrique` ;
- `new_value` : `Salle Bordeaux` ;
- une date avec suffixe UTC `+00:00`.

Les deux changements historiques du seed plus cette écriture donnent **3**
éléments dans `changes` pour la Fabrique. Ce sont des données de démonstration.

```bash
python -m app.cli init-db
python -m app.cli seed-demo
python -m uvicorn app.main:app --port 8000
```

Attendu : schéma à jour, démonstration déjà présente sans écrasement. Recharger
la page de la Fabrique : l’atelier reste dans **Salle Bordeaux**. Le lieu global
de l’événement reste **La Fabrique, Nice** : seule la salle de l’atelier a changé.

Ce passage vérifie plusieurs processus et un arrêt/reprise du serveur ; le
résultat n’est pas uniquement conservé dans le navigateur. Arrêter de nouveau
le serveur avant de poursuivre.

### 5. Provoquer les erreurs sans endommager de données

**Valeur identique :**

```bash
python -m app.cli set-workshop-location --event demo-fabrique --workshop fabrique-photo --actor demo-lea --location "Salle Bordeaux"
```

Attendu : « Valeur identique », aucun changement ajouté. Le nombre d’éléments
dans `changes` pour la Fabrique reste **3**.

**Acteur sans droit sur cet événement :**

```bash
python -m app.cli set-workshop-location --event demo-fabrique --workshop fabrique-photo --actor demo-thomas --location "Salle interdite"
echo $?
```

Attendu : message « pas autorisé », code de sortie **2**, aucun traceback.

**Atelier appartenant à un autre événement :**

```bash
python -m app.cli set-workshop-location --event demo-rencontres --workshop fabrique-photo --actor demo-thomas --location "Salle interdite"
echo $?
```

Attendu : « Atelier introuvable dans cet événement », code **2**.

**Lieu vide :**

```bash
python -m app.cli set-workshop-location --event demo-fabrique --workshop fabrique-photo --actor demo-lea --location ""
echo $?
```

Attendu : demande d’un lieu de 1 à 240 caractères, code **2**.

Après ces erreurs :

```bash
python -m app.cli inspect --event demo-fabrique --workshop fabrique-photo
```

Le lieu reste **Salle Bordeaux** et l’historique reste à **3** éléments.
Ces commandes vérifient le service métier local, pas une connexion utilisateur.

### 6. Vérifier les tests automatiques

```bash
python -m pytest -q -o addopts= -W error
ruff check .
python -m pip check
```

Résultat de référence C1-02 : **178 passed**, **All checks passed!** et
**No broken requirements found**. Le nombre de tests évoluera avec les tâches.
La panne SQL/503, l’erreur interne/500, le rollback après exception et les
contraintes SQL sont provoqués dans les tests automatisés isolés, sans demander
de casser manuellement la base de démonstration.

Pour constater le maintien de la CLI historique : `python cli.py` affiche les
quatre étapes de simulation, **11 demandes → 5 notifications simulées** et
un débit respecté. Aucun e-mail externe ne part.

### 7. Terminer la recette

Arrêter le serveur avec `Ctrl+C` s’il fonctionne, puis :

```bash
unset DATABASE_URL
unset IMPACTFLOW_RECETTE_DIR
```

Le prochain lancement relira la configuration habituelle (`.env` ou valeur
par défaut). Il n’est pas nécessaire de supprimer le dossier temporaire pour
terminer la recette. Pour refaire les mêmes résultats depuis zéro, repartir
de l’étape 1 avec un nouveau dossier.

### Ce que cette étape ne permet pas encore de tester

Connexion/déconnexion, création d’événement dans l’admin, invitations reçues,
inscriptions depuis le site, worker et vrais e-mails restent à développer.
Les pages publiques actuelles lisent la base ; les écritures de recette passent
par une commande locale. Les tests verts ne prouvent pas une charge de production,
un quota fournisseur ni une absence totale de bugs.

## Format des prochaines recettes

À chaque tâche : rappeler le prérequis et la version des données, donner les
commandes et actions exactes, les résultats attendus, un cas d’erreur et la
remise en état utile. Distinguer ce que l’utilisateur peut constater à l’écran,
ce qui est contrôlé par commande et ce qui nécessite un test automatique.

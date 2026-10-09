# Soutenance : démo live scriptée (environ 10 minutes)

Un seul terminal, ouvert dans le dossier du projet, environnement virtuel actif. Tous les chiffres ci-dessous ont été vérifiés en exécutant les commandes.

## Avant de commencer (2 minutes, avant le passage)

- [ ] `source venv/bin/activate`, puis `python3 -m pytest` : **92 passed**
- [ ] `ruff check .` : **All checks passed!**
- [ ] Onglet **Actions** du dépôt GitHub : dernier run **vert**
- [ ] GitHub Project ouvert : les 8 tâches en **Done**
- [ ] Terminal en grande police, `clear` fait

## Acte 1 : le problème (1 min)

**Dire :** « Dans un événement avec plusieurs ateliers, quand l'organisateur change quelque chose, notifier tout le monde est simple mais mauvais. Mon programme décide **qui** prévenir, **quoi** leur dire, **dans quel ordre** et **à quel rythme**. »

**Montrer :** le schéma de `docs/PIPELINE.md` sur GitHub (il s'affiche directement).

## Acte 2 : qui est impacté ? (2 min)

```bash
python3 cli.py --list
python3 cli.py --change 0 w1 horaire 15h
```

**Voir :** Cuisine est le point de départ, **Dégustation est impactée en cascade** (elle dépend de Cuisine), 3 personnes sur 5 à notifier (Alice, Bruno, Chloe), David et Emma épargnés.

**Dire :** « Un parcours de graphe en largeur (BFS) suit les dépendances. Bruno est inscrit aux deux ateliers mais n'est compté qu'une fois. »

```bash
python3 cli.py --change 0 w3 horaire 10h
```

**Voir :** cette fois seuls David et Emma sont touchés. **Dire :** « Même programme, autre atelier, autre ensemble : ce n'est pas une liste fixe. »

## Acte 3 : la fusion (2 min)

```bash
python3 cli.py --change 0 w1 horaire 15h --change 5 w1 horaire 16h --change 12 w1 salle B
```

**Voir :** « 9 notifications sans fusion -> 3 émises (6 évitées) ». Chaque personne reçoit **un seul** message : `horaire → 16h, salle → B`. L'ancienne valeur 15h a disparu.

**Dire :** « La dernière valeur gagne. Le message est envoyé à la fin de la fenêtre de 30 secondes, pas à chaque changement. »

## Acte 4 : priorité et débit (2 min)

```bash
python3 cli.py
```

**Voir :** à t = 30 s, les **deux annulations partent en premier**, puis les changements d'horaire, à raison de **2 par seconde**. L'histogramme se termine par « Maximum observé : 2 (limite 2) -> OK ».

```bash
python3 cli.py --limit 1
```

**Voir :** un envoi par seconde (t = 30, 31, 32, 33, 34). **Dire :** « Le débit est configurable ; un vérificateur indépendant recompte les envois pour prouver que la limite n'est jamais dépassée. »

## Acte 5 : une limite, montrée honnêtement (1 min)

```bash
python3 cli.py --change 0 w1 horaire 15h --change 15 w3 statut annulé
```

**Voir :** les changements d'horaire partent à t = 30, mais l'**annulation, arrivée plus tard, ne part qu'à t = 45**, après eux.

**Dire :** « C'est une limite que je connais : l'urgence ne raccourcit pas la fenêtre de regroupement. Ma piste : émettre immédiatement les annulations. Je l'ai laissée visible plutôt que de la cacher. »

## Acte 6 : les tests (2 min)

```bash
python3 -m pytest
```

**Voir :** 92 tests verts, avec l'histogramme du débit et le rapport de fusion affichés par les tests eux-mêmes.

**Casser le code devant le jury (option forte) :** dans `src/rate_limiter.py`, méthode `try_acquire`, remplacer `if len(self._sent_at) < self.max_per_period:` par `if True:`, relancer `python3 -m pytest` : des tests passent au rouge et l'un affiche « LIMITE DÉPASSÉE ». Puis restaurer avec `git checkout src/rate_limiter.py`.

**Dire :** « Un test qui ne peut pas échouer ne prouve rien. »

## Acte 7 : le code (si le temps le permet)

Ouvrir `src/impact.py` (la boucle BFS : `visited` évite cycles et doublons) ou `src/rate_limiter.py` (la fenêtre glissante). Le détail de chaque choix est dans le guide de soutenance.

## Conclusion (30 s)

**Dire :** « Le programme calcule qui prévenir, fusionne les changements, envoie par ordre d'urgence et respecte le débit, avec 92 tests et une CI. Pistes : émission immédiate des annulations, ordonnanceur réel avec minuteur, vrai fournisseur d'envoi. »

## Si quelque chose plante

| Problème | Solution |
|---|---|
| `ModuleNotFoundError` | L'environnement n'est pas actif : `source venv/bin/activate` |
| `fichier introuvable` | Lancer depuis la racine du projet (là où se trouve `data/`) |
| Une commande est trop longue à taper | `python3 cli.py` (scénario par défaut) montre déjà fusion, priorité et débit |
| Plus rien ne marche | `python3 demo_pipeline.py` : même démonstration, sans argument |

## Ce qui peut varier d'une exécution à l'autre

L'**ordre entre deux personnes de même urgence** (par exemple p4 avant p5, ou l'inverse) peut changer : il vient du parcours d'un ensemble, que Python ne garantit pas identique. Ce n'est pas un bug, et aucun test n'en dépend.

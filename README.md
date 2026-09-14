# garmin-recovery

Récupération et visualisation de données Garmin Connect (sommeil, fréquence cardiaque au repos, stress, pas) et des activités (GPS, allure, FC, dénivelé, tours) — sous forme de deux tableaux de bord distincts, l'un public sur GitHub Pages, l'autre destiné à Claude.

Dépôt : https://github.com/Samu7l/garmin-recovery

## Fonctionnement général

Tous les scripts sont **en lecture seule** vis-à-vis de Garmin : aucun n'écrit quoi que ce soit sur le compte.

1. **Connexion** ([garmin_login.py](garmin-ai/garmin_login.py)) — lit `GARMIN_EMAIL` / `GARMIN_PASSWORD` depuis l'environnement (jamais en argument, pour ne pas finir dans l'historique du shell), se connecte, et sauvegarde un jeton de session dans `garmin-ai/.garmintokens/`. Gère la double authentification en attendant un fichier `_mfa_code.txt`. À relancer uniquement quand le jeton a expiré.
2. **Synchro quotidienne** ([garmin_sync.py](garmin-ai/garmin_sync.py)) — récupère le bien-être (sommeil, pas, FC repos, stress) et les activités des N derniers jours (`--days`, 3 par défaut), écrit des notes markdown lisibles dans `garmin-ai/garmin/wellness/` et `garmin-ai/garmin/workouts/`, plus les données brutes dans `garmin-ai/garmin/data.json`.
3. **Détails d'activité** ([garmin_activity_detail.py](garmin-ai/garmin_activity_detail.py)) — pour chaque activité connue de `data.json`, télécharge le tracé GPS et les séries FC/allure/altitude/cadence, calcule les tours, et fait générer une image de carte (via [map_render.py](garmin-ai/map_render.py), tuiles OpenStreetMap mises en cache, tracé coloré par allure). Chaque activité n'est traitée qu'une fois (mise en cache définitive).
4. **Génération des tableaux de bord** — deux sorties séparées à partir des mêmes données :
   - [build_site.py](garmin-ai/build_site.py) → `docs/` (site public GitHub Pages) : `docs/index.html` (à partir de [site_template.html](garmin-ai/site_template.html)), `docs/data/overview.json`, `docs/data/activities/<id>.json`. Carte interactive Leaflet en direct (tuiles OSM), pas d'image de carte intégrée. Ne contient jamais les notes markdown, les données brutes complètes ni les jetons d'authentification.
   - [build_dashboard.py](garmin-ai/build_dashboard.py) (`--out <chemin>`) → assemble un fichier HTML autonome (à partir de [dashboard_template.html](garmin-ai/dashboard_template.html)) avec les cartes rendues en image intégrée, destiné à être publié comme artifact Claude.
5. **Remplissage historique** (à lancer une fois, ou ponctuellement) :
   - [garmin_bulk_backfill.py](garmin-ai/garmin_bulk_backfill.py) (`--days`, 365 par défaut) — pas, calories, FC repos et sommeil sur une longue période via les endpoints Garmin en plage de dates ; le stress retombe sur une moyenne hebdomadaire au-delà de la fenêtre couverte par la synchro quotidienne. Battery corporelle, VFC et « training readiness » volontairement ignorés (vides sur ce compte).
   - [garmin_sleep_backfill.py](garmin-ai/garmin_sleep_backfill.py) (`--start`, 2015-01-01 par défaut) — historique de sommeil seul, sur plusieurs années, stocké à part (`sleep_history`) pour ne pas polluer la vue mensuelle.

## Utilisation

Un environnement virtuel (`garmin-ai/.venv/`, ignoré par git) évite les soucis de `python`/`python3` ambigus selon le terminal — à créer une seule fois :

```bash
cd garmin-ai
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# une seule fois (ou après expiration du jeton)
GARMIN_EMAIL=... GARMIN_PASSWORD=... ./.venv/bin/python3 garmin_login.py

# synchro + détails + publication du site public
./.venv/bin/python3 garmin_sync.py --days 5
./.venv/bin/python3 garmin_activity_detail.py
./.venv/bin/python3 build_site.py
```

### Rafraîchissement en un clic

Enchaîne synchro → détails d'activité → build du site → `git add docs/ garmin-ai/` → commit → push. Le tableau de bord Claude (`build_dashboard.py`) n'est pas inclus dans ce script et doit être régénéré séparément.

- **Windows** : double-cliquer [refresh.bat](garmin-ai/refresh.bat)
- **Mac** : double-cliquer [refresh.command](garmin-ai/refresh.command) dans le Finder (ouvre Terminal et lance le script) — nécessite que `garmin-ai/.venv/` existe déjà (voir *Utilisation* ci-dessus). Au premier lancement, macOS (Gatekeeper) peut bloquer le fichier car il vient d'être créé/téléchargé — clic droit → *Ouvrir* une première fois pour l'autoriser, ou dans *Réglages Système → Confidentialité et sécurité* cliquer *Ouvrir quand même*. Pour un vrai « 1 clic », glisser le fichier dans le Dock ou en créer un raccourci sur le Bureau.

[run_sync.bat](garmin-ai/run_sync.bat) lance uniquement la synchro (`--days 5`) avec les logs redirigés vers `sync.log`, pour une tâche planifiée par exemple (pas d'équivalent Mac fourni — sous macOS on ferait ça avec un `launchd` plist plutôt qu'un script).

## Structure

```
garmin-ai/
  garmin_login.py            connexion Garmin (jeton + MFA)
  garmin_sync.py              synchro quotidienne (bien-être + activités récentes)
  garmin_activity_detail.py   GPS, séries, tours + rendu de carte par activité
  garmin_bulk_backfill.py     remplissage historique (bien-être, jusqu'à 1 an)
  garmin_sleep_backfill.py    remplissage historique du sommeil seul
  map_render.py               rendu d'image de carte à partir du tracé GPS
  build_site.py                génère docs/ (site public GitHub Pages)
  build_dashboard.py           génère un HTML autonome (artifact Claude)
  site_template.html / dashboard_template.html   gabarits HTML
  refresh.bat / run_sync.bat   scripts Windows
  refresh.command              équivalent Mac de refresh.bat
  garmin/                     données locales (ignorées par git) : data.json, notes markdown, détails d'activité
  .garmintokens/               jeton de session (ignoré par git)
  .venv/                       environnement virtuel Python (ignoré par git)
docs/
  index.html                  site publié (GitHub Pages)
  data/overview.json          résumé bien-être + activités
  data/activities/<id>.json   détail par activité (séries, tours, tracé GPS)
```

## Confidentialité des données

`.gitignore` exclut `garmin-ai/.garmintokens/`, `garmin-ai/.tilecache/`, `garmin-ai/sync.log` et `garmin-ai/garmin/` (données brutes et notes markdown complètes). Seul le contenu de `docs/data/` — volontairement réduit aux résumés nécessaires au site public — est poussé sur GitHub.

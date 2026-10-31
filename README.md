# MascotForge V2 (backend)

Brique produit Arivex : generation de mascottes animees par IA, sortie **video pure**
(pas de Lottie, pas de segmentation, pas de rig).

Pipeline : (1) image uploadee OU prompt texte -> (2) text-to-image genere le
personnage (Flux) -> (3) image-to-video genere 6 clips d'environ 3 s
(`idle`, `talking`, `thinking`, `clicked`, `error`, `sleeping`, Kling 3.0)
-> (4) widget video `<mascot-avatar>` -> (5) export d'un dossier importable + zip.

## Prerequis

- Python 3.12
- Une cle **fal.ai** dans `FAL_KEY` (voir `.env.example`). Sans elle, les routes de
  generation repondent `503` avec un message clair ; `GET /api/health` l'indique.

## Installation

```bash
cd ~/workspace/mascot-forge-v2
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # puis renseignez FAL_KEY
```

## Lancement

```bash
.venv/bin/python -m uvicorn backend.main:app --port 8766
```

- Studio : `http://localhost:8766/` (sert `studio/index.html` si present)
- Widget : `http://localhost:8766/widget/` (sert `widget/` si present)

## API

| Methode | Route | Description |
|---|---|---|
| GET | `/api/health` | `{"ok": true, "fal_key_configured": bool}` |
| POST | `/api/character/from-prompt` | `{"prompt"}` -> `{"character_id", "image_url"}` (503 sans FAL_KEY) |
| POST | `/api/character/from-upload` | multipart `file` -> `{"character_id", "image_url"}` (503 sans FAL_KEY) |
| POST | `/api/generate` | `{"character_id"}` -> `{"job_id"}` (429 si plafond, 503 sans FAL_KEY) |
| GET | `/api/jobs/{job_id}` | statut + etats (`video_url`, `model`, `error`) + `cost_usd_estimate` |
| POST | `/api/export/{job_id}` | `{"download_url"}` (404 si job pas termine) |
| GET | `/api/exports/{filename}` | telechargement du zip |
| GET | `/videos/{job_id}/{etat}.mp4` | clip genere (fichier local) |
| GET | `/api/cost` | `{"month", "spent_usd", "cap_usd", "mascots_completed"}` |

Tous les messages d'erreur API sont en francais (champ `detail`), sans em dash.

## Modeles fal.ai

Surchargeables par variables d'environnement (valeurs par defaut verifiees le 2026-10-19) :

- Text-to-image : `fal-ai/flux/dev` (`MASCOTFORGE_TTI_MODEL`)
- Image-to-video : `fal-ai/kling-video/v3/standard/image-to-video` (`MASCOTFORGE_I2V_MODEL`),
  720p, ~0,084 $/s, duree discrete `"3"` a `"15"`
- Fallback : `fal-ai/kling-video/v3/pro/image-to-video` (`MASCOTFORGE_FALLBACK_MODEL`)

**Note Runway** : aucun endpoint fal.ai verifie n'existe pour Runway Gen-4.5
(Runway expose sa propre API). Le fallback est donc configurable : on pourra y
brancher Runway plus tard via sa propre cle, en adaptant `backend/fal.py`.

## Couts

- Compteur mensuel persistant dans `data/cost.json`, plafond via
  `MASCOTFORGE_MONTHLY_CAP_USD` (defaut 50 $).
- Cout estime par clip : duree x tarif du modele. Tarifs dans `backend/settings.py`,
  **a verifier sur la page pricing fal.ai** avant la mise en production.
- Ordre de grandeur : 6 clips x 3 s x 0,084 $/s + image ~= **1,50 $ par mascotte**.
- Chaque clip journalise le modele qui l'a produit (visible dans
  `GET /api/jobs/{job_id}` et dans le `manifest.json` de l'export).

## Export

`POST /api/export/{job_id}` assemble `exports/mascot-{id}/mascot/` :

- `mascot.js` : copie de `widget/mascot-avatar.js` (erreur claire si absent)
- `manifest.json` : `{"name", "states", "default_state": "idle", "version": 1, "generated_at", "models"}`
- `videos/*.mp4` : les 6 clips
- `README.md` : notice d'integration en francais (snippet
  `<mascot-avatar manifest="./mascot/manifest.json">`, exemple `play('error')`,
  zero build step, chemins relatifs)

puis produit `exports/mascot-{id}.zip`.

## Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

fal.ai est entierement mocke (monkeypatch de `backend/fal.py`) : aucun appel
reseau reel, aucun cent depense. Les tests couvrent le cycle complet
(prompt -> personnage -> generation -> export -> contenu du zip), le plafond
(429), l'absence de FAL_KEY (503), le fallback de modele et les cas d'erreur.

## Fichiers

- `backend/main.py` : app FastAPI, routes, fichiers statiques (studio, widget, exports)
- `backend/fal.py` : client fal.ai (upload, text-to-image, image-to-video via file
  d'attente ; transport `fal-client` avec repli REST manuel)
- `backend/pipeline.py` : orchestration async des jobs (6 etats, parallélisme max 3,
  retry fallback, telechargement local des MP4)
- `backend/cost.py` : compteur mensuel persistant + plafond
- `backend/exporter.py` : assemblage du dossier importable + zip
- `backend/models.py` : schemas pydantic
- `backend/settings.py` : configuration (env)
- `data/` : runtime gitigne (jobs, personnages, couts, videos)

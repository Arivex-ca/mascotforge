# MascotForge (text-to-mascot)

Brique produit Arivex : tu décris une mascotte (ou tu envoies son image), tu
choisis ses états d'animation, et l'outil sort une mascotte animée à fond
transparent, prête à coller dans un site ou devant un agent IA.

Pipeline :

1. Personnage : image envoyée (PNG détouré conseillé) ou prompt texte. Flux
   génère le personnage sur fond vert uni ; une image envoyée est posée sur ce
   même vert.
2. États à la demande : presets par usage (agent IA, site web, complet), puis
   ajout, retrait ou description libre de chaque état, 12 au maximum. Chaque
   état est un clip de 3 s, en boucle ou joué une fois.
3. Kling 3.0 (image-to-video) génère un clip par état. Le clip commence et
   finit sur l'image de départ (`end_image_url`) : la boucle ne saute pas et
   le widget passe d'un état à l'autre sur cette pose commune. Audio coupé.
4. Détourage (ffmpeg) : le vert disparaît, chaque clip devient une vidéo
   « alpha empilé » de 480 px (couleur en haut, masque en bas).
5. Widget `<mascot-avatar>` : recompose la transparence en WebGL, dans tous les
   navigateurs, Safari et iOS compris.
6. Export : dossier importable + zip.

## Prérequis

- Python 3.10 ou plus
- ffmpeg et ffprobe dans le PATH (ou `MASCOTFORGE_FFMPEG`). Sans eux, la
  génération marche mais les mascottes gardent leur fond vert ; `GET /api/health`
  l'indique.
- Une clé **fal.ai** dans `FAL_KEY` (voir `.env.example`). Sans elle, les routes
  de génération répondent `503` avec un message clair.

## Installation

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt   # Windows : .venv\Scripts\pip
cp .env.example .env                        # puis renseigne FAL_KEY
```

## Lancement

```bash
.venv/bin/python -m uvicorn backend.main:app --port 8766 --env-file .env
```

`--env-file` charge `FAL_KEY` et les réglages depuis `.env` (le backend ne lit
que les variables d'environnement).

- Studio : `http://localhost:8766/`
- Widget et démo : `http://localhost:8766/widget/`

## API

| Méthode | Route | Description |
|---|---|---|
| GET | `/api/health` | `{"ok", "fal_key_configured", "ffmpeg_available"}` |
| GET | `/api/presets` | presets d'états, coût par état, nombre max d'états |
| POST | `/api/character/from-prompt` | `{"prompt"}` -> `{"character_id", "image_url"}` (429 si plafond) |
| POST | `/api/character/from-upload` | multipart `file`, 10 Mo max -> `{"character_id", "image_url"}` |
| POST | `/api/generate` | `{"character_id", "states": [{"name", "prompt", "loop"}]}` ou `{"character_id", "usage"}` -> `{"job_id"}` |
| GET | `/api/jobs/{job_id}` | statut, états (`video_url`, `model`, `error`, `loop`), coût estimé et réel |
| POST | `/api/jobs/{job_id}/retry` | relance les seuls états en échec (409 s'il n'y en a pas) |
| GET | `/api/jobs/{job_id}/manifest.json` | manifest du widget pour l'aperçu |
| POST | `/api/export/{job_id}` | `{"download_url"}` (409 si le job n'est pas terminé) |
| GET | `/api/exports/{filename}` | téléchargement du zip |
| GET | `/videos/{job_id}/{etat}.mp4` | clip détouré |
| GET | `/api/cost` | `{"month", "spent_usd", "reserved_usd", "cap_usd", "mascots_completed"}` |

Les messages d'erreur sont en français (champ `detail`), sans em dash. Les
erreurs de fal.ai ou de ffmpeg restent dans les logs du serveur ; l'API ne
renvoie qu'un message propre.

## Modèles fal.ai

Surchargeables par variables d'environnement :

- Text-to-image : `fal-ai/flux/dev` (`MASCOTFORGE_TTI_MODEL`)
- Image-to-video : `fal-ai/kling-video/v3/standard/image-to-video`
  (`MASCOTFORGE_I2V_MODEL`). Schéma lu le 2026-10-30 : `start_image_url`
  (requis), `end_image_url`, `generate_audio`, durée `"3"` à `"15"`.
- Fallback : `fal-ai/kling-video/v3/pro/image-to-video` (`MASCOTFORGE_FALLBACK_MODEL`)

## Coûts

- 0,084 $/s en Kling 3.0 standard sans audio (page tarif fal.ai, 2026-10-30) :
  environ 0,25 $ par état de 3 s. Une mascotte de 4 états coûte environ 1 $,
  plus 0,025 $ si l'image vient d'un prompt.
- Plafond mensuel `MASCOTFORGE_MONTHLY_CAP_USD` (défaut 50 $), compteur dans
  `data/cost.json`. Chaque job réserve son estimation avant de partir : deux
  jobs lancés en même temps ne dépassent pas le plafond ensemble.
- Un clip généré est compté même si son téléchargement échoue ; la relance le
  retélécharge sans le repayer.
- Tarif du modèle pro : estimation, à vérifier sur la page tarif fal.ai.

## Export

`POST /api/export/{job_id}` assemble `exports/mascot-{id}/mascot/` :

- `mascot.js` : le widget
- `manifest.json` (v2) : `{"default_state", "alpha": "stacked", "states": {"idle": {"src", "loop"}, ...}, "models"}`
- `videos/*.mp4` : un clip par état
- `README.md` : notice d'intégration générée à partir des états

## Widget

```html
<mascot-avatar manifest="./mascot/manifest.json" label="Mon assistant"></mascot-avatar>
<script src="./mascot/mascot.js"></script>
<script>
  document.querySelector("mascot-avatar").play("thinking");
</script>
```

Attributs : `click-state` (défaut `clicked` s'il existe), `sleep-state` (défaut
`sleeping` s'il existe), `sleep-after` (secondes, 0 pour désactiver), `switch`
(`loop-end` par défaut, ou `immediate`), `parallax`, `label`. Le widget lit
aussi les manifests v1 de la V2.

## Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

fal.ai est mocké : aucun appel réseau, aucun cent dépensé. `tests/test_alpha.py`
lance le vrai ffmpeg sur un clip synthétique. `tests/test_widget_chromium.py`
saute si Playwright n'est pas installé ; `widget/smoke.html` se lance dans un
navigateur.

## Fichiers

- `backend/main.py` : app FastAPI, routes, fichiers statiques
- `backend/states.py` : presets d'états et validation des états libres
- `backend/fal.py` : client fal.ai (upload, text-to-image, image-to-video)
- `backend/alpha.py` : fond vert et détourage ffmpeg
- `backend/pipeline.py` : jobs, fallback, téléchargement, relance, reprise au démarrage
- `backend/cost.py` : compteur mensuel, réservations, plafond
- `backend/exporter.py` : manifest v2, dossier importable, zip
- `widget/mascot-avatar.js` : le composant web
- `studio/` : l'interface de création

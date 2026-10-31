"""Assemble le dossier d'export importable d'une mascotte, puis le zip.

Contenu de ``exports/mascot-{id}/mascot/`` :
  mascot.js      copie de widget/mascot-avatar.js (le composant web V2)
  manifest.json  etats, etat par defaut, modeles IA utilises
  videos/        un MP4 par etat (copies locales de data/videos/{job_id}/)
  README.md      notice d'integration (francais, sans em dash)
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from backend import settings
from backend.pipeline import STATES

MANIFEST_VERSION = 1

README_TEMPLATE = """# {name}

Mascotte animee generee par MascotForge V2 (Arivex).

## Contenu du dossier

- `mascot.js` : le composant web `<mascot-avatar>` (aucune dependance, zero build step)
- `manifest.json` : etats disponibles, etat par defaut, modeles IA utilises
- `videos/` : un clip MP4 par etat (idle, talking, thinking, clicked, error, sleeping)

## Integration (chemins relatifs)

Copiez le dossier `mascot/` a cote de votre page, puis :

```html
<mascot-avatar manifest="./mascot/manifest.json"></mascot-avatar>
<script src="./mascot/mascot.js"></script>
```

## Changer d'etat en JavaScript

```js
const avatar = document.querySelector("mascot-avatar");
avatar.play("error"); // idle, talking, thinking, clicked, error, sleeping
```

## Provenance

- Job MascotForge : {job_id}
- Genere le : {generated_at}
- Modeles IA : voir le champ `models` de `manifest.json`
"""


class ExportError(Exception):
    pass


def _short_id(job_id: str) -> str:
    return job_id[:8]


def build_export(job: dict) -> dict:
    """Construit l'export d'un job termine. Retourne {filename, download_url}."""
    if job["status"] != "done":
        raise ExportError(
            f"Export impossible : le job {job['job_id']} n'est pas termine "
            f"(statut : {job['status']})."
        )
    job_id = job["job_id"]
    short = _short_id(job_id)
    name = f"mascot-{short}"

    root = settings.exports_dir() / name
    mascot_dir = root / "mascot"
    videos_dir = mascot_dir / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    # 1. Le composant web (source du widget V2)
    widget_src = settings.widget_source_file()
    if not widget_src.is_file():
        raise ExportError(
            "Export impossible : le fichier widget/mascot-avatar.js est introuvable "
            "dans le projet. Ajoutez le widget V2 avant d'exporter."
        )
    shutil.copyfile(widget_src, mascot_dir / "mascot.js")

    # 2. Les videos (copies locales telechargees pendant le job)
    for state in STATES:
        src = settings.data_dir() / "videos" / job_id / f"{state}.mp4"
        if not src.is_file():
            raise ExportError(
                f"Export impossible : la video de l'etat {state!r} est manquante "
                f"({src}). Relancez la generation du job."
            )
        shutil.copyfile(src, videos_dir / f"{state}.mp4")

    # 3. Le manifest
    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "name": name,
        "states": {state: f"videos/{state}.mp4" for state in STATES},
        "default_state": "idle",
        "version": MANIFEST_VERSION,
        "generated_at": generated_at,
        "models": {state: job["states"][state].get("model") for state in STATES},
    }
    (mascot_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    # 4. Le README (francais, sans em dash)
    readme = README_TEMPLATE.format(
        name=name, job_id=job_id, generated_at=generated_at
    )
    if "\u2014" in readme:  # garde-fou : aucun em dash dans les textes utilisateur
        raise ExportError("Le template README contient un em dash (interdit).")
    (mascot_dir / "README.md").write_text(readme, encoding="utf-8")

    # 5. Le zip
    zip_path = settings.exports_dir() / f"{name}.zip"
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(root), "zip", root_dir=root)

    filename = f"{name}.zip"
    return {"filename": filename, "download_url": f"/api/exports/{filename}"}

"""Assemble le dossier d'export importable d'une mascotte, puis le zip.

Contenu de ``exports/mascot-{id}/mascot/`` :
  mascot.js      copie de widget/mascot-avatar.js (le composant web)
  manifest.json  etats (clip + boucle), etat par defaut, mode alpha, modeles IA
  videos/        un MP4 par etat (copies locales de data/videos/{job_id}/)
  README.md      notice d'integration (francais, sans em dash)
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from typing import Callable

from backend import settings

MANIFEST_VERSION = 2

README_TEMPLATE = """# {name}

Mascotte animee generee par MascotForge (Arivex).

## Contenu du dossier

- `mascot.js` : le composant web `<mascot-avatar>` (aucune dependance, zero build step)
- `manifest.json` : etats disponibles, etat par defaut, modeles IA utilises
- `videos/` : un clip MP4 par etat ({state_list})

## Integration (chemins relatifs)

Copiez le dossier `mascot/` a cote de votre page, puis :

```html
<mascot-avatar manifest="./mascot/manifest.json" label="{name}"></mascot-avatar>
<script src="./mascot/mascot.js"></script>
```

## Changer d'etat en JavaScript

```js
const avatar = document.querySelector("mascot-avatar");
avatar.play("{example}"); // {state_list}
```

Les etats en boucle ({loop_list}) tournent tant qu'ils sont actifs. Les autres
jouent une fois puis reviennent a l'etat precedent. Le changement d'etat attend
la fin du clip en cours, sur la pose commune, pour eviter tout saut :
`play(etat, {{ immediate: true }})` force un changement sans attendre.

## Provenance

- Job MascotForge : {job_id}
- Genere le : {generated_at}
- Modeles IA : voir le champ `models` de `manifest.json`
"""


class ExportError(Exception):
    pass


def _short_id(job_id: str) -> str:
    return job_id[:8]


def build_manifest(job: dict, src_for: Callable[[str], str], generated_at: str) -> dict:
    """Manifest v2 du widget. src_for(etat) donne le chemin du clip."""
    return {
        "version": MANIFEST_VERSION,
        "name": f"mascot-{_short_id(job['job_id'])}",
        "default_state": job["default_state"],
        "alpha": job.get("alpha") or "none",
        "states": {
            name: {"src": src_for(name), "loop": info["loop"]}
            for name, info in job["states"].items()
            if info["status"] == "done"
        },
        "generated_at": generated_at,
        "models": {name: info.get("model") for name, info in job["states"].items()},
    }


def build_export(job: dict) -> dict:
    """Construit l'export d'un job termine. Retourne {filename, download_url}."""
    if job["status"] != "done":
        raise ExportError(
            f"Export impossible : le job {job['job_id']} n'est pas termine "
            f"(statut : {job['status']})."
        )
    job_id = job["job_id"]
    name = f"mascot-{_short_id(job_id)}"
    state_names = list(job["states"])

    root = settings.exports_dir() / name
    if root.exists():
        shutil.rmtree(root)  # un etat retire d'un export precedent ne doit pas trainer
    mascot_dir = root / "mascot"
    videos_dir = mascot_dir / "videos"
    videos_dir.mkdir(parents=True, exist_ok=True)

    # 1. Le composant web
    widget_src = settings.widget_source_file()
    if not widget_src.is_file():
        raise ExportError(
            "Export impossible : le fichier widget/mascot-avatar.js est introuvable "
            "dans le projet. Ajoutez le widget avant d'exporter."
        )
    shutil.copyfile(widget_src, mascot_dir / "mascot.js")

    # 2. Les videos (versions web, detourees si ffmpeg etait la)
    for state in state_names:
        src = settings.data_dir() / "videos" / job_id / f"{state}.mp4"
        if not src.is_file():
            raise ExportError(
                f"Export impossible : la video de l'etat {state!r} est manquante. "
                "Relancez les etats en echec."
            )
        shutil.copyfile(src, videos_dir / f"{state}.mp4")

    # 3. Le manifest
    generated_at = datetime.now(timezone.utc).isoformat()
    manifest = build_manifest(job, lambda s: f"videos/{s}.mp4", generated_at)
    (mascot_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    # 4. Le README (francais, sans em dash)
    loops = [s for s in state_names if job["states"][s]["loop"]]
    readme = README_TEMPLATE.format(
        name=name,
        job_id=job_id,
        generated_at=generated_at,
        state_list=", ".join(state_names),
        loop_list=", ".join(loops),
        example=next((s for s in state_names if s != job["default_state"]), state_names[0]),
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

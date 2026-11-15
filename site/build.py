"""Vendor MascotForge's local browser engines and demo assets into site/.

The generated site has no runtime dependency on files outside this directory.
Run this script again after updating an engine, widget, license, or gallery asset.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE = Path(__file__).resolve().parent

COPIES = {
    ROOT / "engines/blob-atelier/agent-mascot.js": SITE / "vendor/agent-mascot.js",
    ROOT / "engines/blob-atelier/LICENSE": SITE / "licenses/Blob-Atelier-LICENSE.txt",
    ROOT / "engines/blob-atelier/vendor/three.module.min.js": SITE / "vendor/three.module.min.js",
    ROOT / "engines/blob-atelier/vendor/three.LICENSE.txt": SITE / "licenses/three-LICENSE.txt",
    ROOT / "engines/wobnimo/dist/wobnimo.js": SITE / "vendor/wobnimo.js",
    ROOT / "engines/wobnimo/LICENSE": SITE / "licenses/Wobnimo-LICENSE.txt",
    ROOT / "widget/mascot-avatar.js": SITE / "vendor/mascot-avatar.js",
    ROOT / "docs/media/renard-video-etats.gif": SITE / "media/renard-video-etats.gif",
    ROOT / "exports/blob-v2-essai/lapin-final.png": SITE / "media/lapin-final.png",
    ROOT / "exports/orbi-clavier/orbi-clavier.json": SITE / "data/orbi-clavier.json",
    ROOT / "exports/agent-essai-v2/patch-mascot/mascot/manifest.json": SITE / "data/patch-manifest.json",
}


def copy_sources() -> None:
    missing = []
    for source, destination in COPIES.items():
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        elif destination.is_file():
            print(f"Keeping vendored asset without local source: {destination.relative_to(SITE)}")
        else:
            missing.append(str(source))
    if missing:
        raise FileNotFoundError("Missing site source files and vendored copies:\n" + "\n".join(missing))


def write_manifests() -> None:
    with (SITE / "data/orbi-clavier.json").open(encoding="utf-8-sig") as handle:
        orbi_spec = json.load(handle)

    orbi_manifest = {
        "version": 2,
        "name": "Orbi",
        "engine": "3d",
        "engine_src": "../vendor/wobnimo.js",
        "engine_config": {"character": "volt", "state": "working"},
        "engine_spec": orbi_spec,
        "default_state": "working",
        "alpha": "none",
        "states": {
            state: {"loop": True}
            for state in (
                "idle",
                "listening",
                "thinking",
                "talking",
                "working",
                "happy",
                "done",
                "error",
                "sleeping",
            )
        },
        "credit": "Wobnimo by Pourya Akhbari (MIT)",
    }
    (SITE / "data/orbi-manifest.json").write_text(
        json.dumps(orbi_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with (SITE / "data/patch-manifest.json").open(encoding="utf-8-sig") as handle:
        patch_manifest = json.load(handle)
    patch_manifest["engine_src"] = "../vendor/agent-mascot.js"
    patch_manifest["engine_three_src"] = "../vendor/three.module.min.js"
    (SITE / "data/patch-site-manifest.json").write_text(
        json.dumps(patch_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    copy_sources()
    write_manifests()
    print(f"Built self-contained site assets in {SITE}")

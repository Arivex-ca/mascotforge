"""Test reel unique : 1 clip Kling via le vrai code du backend (fal.py).

Usage : .venv/bin/python tests-reels/test_1_clip.py
Cout : ~0,25 $ (1 clip de 3 s). La cle FAL_KEY est lue via le substitut authd,
jamais en clair.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, "/opt/muse/skills/custom-connector-setup/bin")
from dynamic_credentials import dynamic_credential_entry  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Transport SDK (fal-client 1.0.3 installe) : c'est la voie officielle, et l'upload
# via sdk.upload_file utilise le bon endpoint courant (le REST manuel vers
# rest.alpha.fal.ai/storage retourne 401 avec cette cle).
os.environ["MASCOTFORGE_FAL_TRANSPORT"] = "sdk"

# Contournement sandbox : ce httpx interprete mal les IPv6 entre crochets
# dans no_proxy ("[::1]" -> Invalid port). On les retire, "::1" non crochete
# suffit pour le bypass localhost.
for _var in ("no_proxy", "NO_PROXY"):
    _val = os.environ.get(_var, "")
    os.environ[_var] = ",".join(p for p in _val.split(",") if "[" not in p)

from backend import fal  # noqa: E402


async def main() -> None:
    entry = dynamic_credential_entry("custom.fal-ai")
    os.environ["FAL_KEY"] = entry["surrogate"]
    print("cle : substitut authd OK", flush=True)

    import base64

    lion = Path.home() / "workspace/mascot-forge/mascots/avatar-1792047766223558528-0-15828f/original.webp"
    raw = lion.read_bytes()
    # Pas d'upload : le stockage fal.ai refuse cette cle (401). On passe
    # l'image en data URI directement, accepte par les modeles fal.ai.
    image_url = f"data:image/webp;base64,{base64.b64encode(raw).decode()}"
    print(f"data URI prete ({len(raw)} octets)", flush=True)

    print("generation du clip idle (Kling, ~3 s, quelques minutes)...", flush=True)
    video_url, model = await fal.generate_state_video(image_url, "idle")
    print(f"clip OK : modele={model}", flush=True)
    print(f"video_url={video_url}", flush=True)

    out = ROOT / "tests-reels" / "idle-reel.mp4"
    out.parent.mkdir(exist_ok=True)
    import httpx

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.get(video_url)
        r.raise_for_status()
        out.write_bytes(r.content)
    print(f"telecharge : {out} ({out.stat().st_size} octets)", flush=True)


if __name__ == "__main__":
    asyncio.run(main())

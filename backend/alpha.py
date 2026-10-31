"""Detourage par fond vert, via ffmpeg.

Avant Kling : put_on_green() pose l'image du personnage sur un vert uni.
Apres Kling : to_stacked_alpha() retire le vert et produit une video
"alpha empile" : couleur premultipliee en haut, masque alpha en niveaux de
gris en bas, en H.264. Le widget recompose la transparence en WebGL. Ce
format se lit dans tous les navigateurs, Safari et iOS compris, la ou le
WebM transparent ne passe pas partout.

Sans ffmpeg, available() renvoie False : le pipeline garde les clips bruts
(opaques) et le signale.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

GREEN = "0x00FF00"
# Tolerance du detourage (0-1). Plus haut : retire plus de vert, mais peut
# mordre les zones vertes du personnage.
KEY_SIMILARITY = 0.28
KEY_BLEND = 0.08
OUTPUT_SIZE = 480  # largeur du clip web ; 960 px pour une mascotte de 320 px gaspille


class AlphaError(RuntimeError):
    pass


def ffmpeg_bin() -> str | None:
    return os.environ.get("MASCOTFORGE_FFMPEG") or shutil.which("ffmpeg")


def ffprobe_bin() -> str | None:
    override = os.environ.get("MASCOTFORGE_FFMPEG")
    if override:
        candidate = Path(override).with_name(Path(override).name.replace("ffmpeg", "ffprobe"))
        if candidate.is_file():
            return str(candidate)
    return shutil.which("ffprobe")


def available() -> bool:
    return bool(ffmpeg_bin() and ffprobe_bin())


def _run(args: list[str]) -> None:
    exe = ffmpeg_bin()
    if not exe:
        raise AlphaError("ffmpeg est introuvable : installe-le ou renseigne MASCOTFORGE_FFMPEG.")
    proc = subprocess.run(
        [exe, "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AlphaError(f"ffmpeg a echoue ({proc.returncode}) : {proc.stderr.strip()[-400:]}")


def image_size(path: Path) -> tuple[int, int]:
    exe = ffprobe_bin()
    if not exe:
        raise AlphaError("ffprobe est introuvable.")
    proc = subprocess.run(
        [exe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise AlphaError(f"Image illisible : {path.name}.")
    stream = json.loads(proc.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def put_on_green(src: Path, dest: Path) -> None:
    """Pose l'image (transparente ou non) sur un fond vert uni, en PNG."""
    width, height = image_size(src)
    _run([
        "-f", "lavfi", "-i", f"color=c={GREEN}:s={width}x{height}",
        "-i", str(src),
        "-filter_complex", "[0:v][1:v]overlay=format=auto,format=rgb24",
        "-frames:v", "1", str(dest),
    ])


def to_stacked_alpha(src: Path, dest: Path, size: int = OUTPUT_SIZE) -> None:
    """Clip sur fond vert -> MP4 alpha empile (hauteur doublee), sans audio."""
    graph = (
        f"[0:v]scale={size}:-2,"
        f"chromakey=color={GREEN}:similarity={KEY_SIMILARITY}:blend={KEY_BLEND},"
        "format=rgba,despill=type=green,premultiply=inplace=1,split[c][a];"
        "[a]format=rgba,alphaextract,format=yuv420p[am];"
        "[c]format=yuv420p[cm];"
        "[cm][am]vstack,format=yuv420p"
    )
    _run([
        "-i", str(src),
        "-filter_complex", graph,
        "-an", "-c:v", "libx264", "-crf", "23", "-preset", "medium",
        "-movflags", "+faststart", str(dest),
    ])

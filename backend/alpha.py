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


def to_stacked_alpha(
    src: Path, dest: Path, size: int = OUTPUT_SIZE, fps: int | None = None,
    all_intra: bool = False,
) -> None:
    """Clip sur fond vert -> MP4 alpha empile (hauteur doublee), sans audio.

    all_intra : une image cle par image, pour que le widget saute a n'importe
    quelle image sans saccade (clip du suivi du curseur).
    """
    graph = (
        f"[0:v]{f'fps={fps},' if fps else ''}scale={size}:-2,"
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
        *(["-g", "1"] if all_intra else []),
        "-movflags", "+faststart", str(dest),
    ])


SAMPLE = 64  # cote de l'image reduite analysee par head_offsets
MAX_SHIFT = 6  # deplacement maximal cherche, en pixels de l'image reduite
MIN_SHIFT_PX = 0.3  # en dessous, on considere que la tete ne bouge pas sur cet axe
INSET = 2  # pixels ignores le long du bord de la silhouette : le contour bouge peu


def head_shifts(stacked: Path) -> list[tuple[float, float]]:
    """Direction du regard sur chaque image d'un clip alpha empile.

    Recale l'interieur de la tete (le haut de la silhouette) sur la premiere
    image : le decalage qui ressemble le plus donne le deplacement du visage.
    Un clignement change l'apparence sans rien deplacer, il ne fausse donc
    pas la mesure. Retourne [(dx, dy), ...] en pixels de l'image reduite :
    dx > 0 la tete regarde vers la droite de l'ecran, dy < 0 vers le haut.
    """
    exe = ffmpeg_bin()
    if not exe:
        raise AlphaError("ffmpeg est introuvable : installe-le ou renseigne MASCOTFORGE_FFMPEG.")
    graph = (
        "[0:v]split[t][b];"
        f"[t]crop=iw:ih/2:0:0,scale={SAMPLE}:{SAMPLE},format=gray[c];"
        f"[b]crop=iw:ih/2:0:ih/2,scale={SAMPLE}:{SAMPLE},format=gray[m];"
        "[c][m]vstack"
    )
    proc = subprocess.run(
        [exe, "-hide_banner", "-loglevel", "error", "-i", str(stacked),
         "-filter_complex", graph, "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise AlphaError(f"ffmpeg a echoue ({proc.returncode}) : {proc.stderr.decode(errors='replace')[-400:]}")
    size = SAMPLE * SAMPLE
    raw = proc.stdout
    frames = [(raw[i:i + size], raw[i + size:i + 2 * size]) for i in range(0, len(raw) - 2 * size + 1, 2 * size)]
    if not frames:
        raise AlphaError("Clip vide : aucune image a analyser.")

    # Zone de la tete : le haut (55 %) de la silhouette de la premiere image.
    mask0 = frames[0][1]
    rows = [y for y in range(SAMPLE) if any(mask0[y * SAMPLE + x] > 128 for x in range(SAMPLE))]
    if not rows:
        raise AlphaError("Silhouette introuvable dans le clip.")
    top, bottom = rows[0], rows[-1]
    head_bottom = top + max(2, int((bottom - top) * 0.55))

    # Modele : pixels interieurs de la tete sur la premiere image, loin des bords.
    color0 = frames[0][0]
    margin = INSET + MAX_SHIFT
    template = [
        (x, y, color0[y * SAMPLE + x])
        for y in range(max(margin, top), min(SAMPLE - margin, head_bottom))
        for x in range(margin, SAMPLE - margin)
        if min(mask0[y * SAMPLE + x], mask0[y * SAMPLE + x - INSET], mask0[y * SAMPLE + x + INSET],
               mask0[(y - INSET) * SAMPLE + x], mask0[(y + INSET) * SAMPLE + x]) > 128
    ]
    if not template:
        raise AlphaError("Tete trop petite pour mesurer le regard.")
    offsets = range(-MAX_SHIFT, MAX_SHIFT + 1)

    def refine(minus: float, best: float, plus: float) -> float:
        """Decalage sous-pixel : sommet de la parabole passant par 3 ecarts."""
        curve = minus - 2 * best + plus
        return 0.0 if curve <= 0 else max(-0.5, min(0.5, (minus - plus) / (2 * curve)))

    shifts = []
    for color, _mask in frames:
        cost = {
            (sx, sy): sum(abs(color[(y + sy) * SAMPLE + x + sx] - ref) for x, y, ref in template)
            for sy in offsets for sx in offsets
        }
        bx, by = min(cost, key=cost.get)
        fx = fy = 0.0
        if abs(bx) < MAX_SHIFT:
            fx = refine(cost[(bx - 1, by)], cost[(bx, by)], cost[(bx + 1, by)])
        if abs(by) < MAX_SHIFT:
            fy = refine(cost[(bx, by - 1)], cost[(bx, by)], cost[(bx, by + 1)])
        shifts.append((bx + fx, by + fy))
    return shifts


def head_offsets(stacked: Path) -> list[list[float]]:
    """head_shifts() ramene entre -1 et 1 sur chaque axe, pour le manifest."""
    shifts = head_shifts(stacked)
    span_x = max(abs(dx) for dx, _ in shifts)
    span_y = max(abs(dy) for _, dy in shifts)
    return [
        [
            round(dx / span_x, 3) if span_x >= MIN_SHIFT_PX else 0.0,
            round(dy / span_y, 3) if span_y >= MIN_SHIFT_PX else 0.0,
        ]
        for dx, dy in shifts
    ]

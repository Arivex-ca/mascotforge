"""Detourage reel avec ffmpeg (aucun mock) : saute si ffmpeg est absent."""
from __future__ import annotations

import json
import subprocess

import pytest

from backend import alpha

pytestmark = pytest.mark.skipif(not alpha.available(), reason="ffmpeg/ffprobe absents")


def _pixel(path, x: int, y: int) -> tuple[int, int, int]:
    """Couleur RGB d'un pixel de la premiere image d'un fichier video ou image."""
    out = subprocess.run(
        [alpha.ffmpeg_bin(), "-v", "error", "-i", str(path), "-frames:v", "1",
         "-vf", f"format=rgb24,crop=1:1:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout
    return out[0], out[1], out[2]


def _green_clip(path) -> None:
    """Clip 960x960 d'une seconde : carre rouge sur fond vert uni."""
    subprocess.run(
        [alpha.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i",
         "color=c=0x00FF00:s=960x960:d=1,"
         "drawbox=x=300:y=300:w=360:h=360:color=red@1:t=fill",
         "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


def test_stacked_alpha_keys_green_and_keeps_subject(tmp_path):
    src = tmp_path / "green.mp4"
    dest = tmp_path / "stacked.mp4"
    _green_clip(src)

    alpha.to_stacked_alpha(src, dest)

    width, height = alpha.image_size(dest)
    assert (width, height) == (480, 960), "couleur en haut + alpha en bas, en 480 px"

    corner_color = _pixel(dest, 10, 10)
    center_color = _pixel(dest, 240, 240)
    corner_alpha = _pixel(dest, 10, 480 + 10)
    center_alpha = _pixel(dest, 240, 480 + 240)

    assert max(corner_color) < 40, f"fond vert retire (premultiplie -> noir) : {corner_color}"
    assert center_color[0] > 180 and center_color[1] < 80, f"sujet rouge garde : {center_color}"
    assert max(corner_alpha) < 40, f"alpha nul sur le fond : {corner_alpha}"
    assert min(center_alpha) > 215, f"alpha plein sur le sujet : {center_alpha}"


def _look_clip(path) -> None:
    """Clip de 2 s sur vert : tete et corps blancs, yeux noirs qui vont a droite puis a gauche."""
    subprocess.run(
        [alpha.ffmpeg_bin(), "-v", "error", "-y",
         "-f", "lavfi", "-i", "color=c=0x00FF00:s=960x960:d=2:r=24",
         "-f", "lavfi", "-i", "color=c=white:s=400x400",
         "-f", "lavfi", "-i", "color=c=white:s=500x300",
         "-f", "lavfi", "-i", "color=c=black:s=120x60",
         "-filter_complex",
         "[0][1]overlay=280:150[a];[a][2]overlay=230:560[b];"
         "[b][3]overlay=x='420+60*sin(2*PI*t/2)':y=300:shortest=1",
         "-t", "2", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


def test_look_clip_is_all_intra_and_maps_the_gaze(tmp_path):
    src = tmp_path / "look-green.mp4"
    dest = tmp_path / "look.mp4"
    _look_clip(src)

    alpha.to_stacked_alpha(src, dest, fps=12, all_intra=True)

    probe = subprocess.run(
        [alpha.ffprobe_bin(), "-v", "error", "-select_streams", "v:0", "-show_frames",
         "-show_entries", "frame=key_frame", "-of", "json", str(dest)],
        capture_output=True, text=True, check=True,
    ).stdout
    keys = [frame["key_frame"] for frame in json.loads(probe)["frames"]]
    assert len(keys) == 24, "2 s a 12 images par seconde"
    assert set(keys) == {1}, "une image cle par image pour sauter sans saccade"

    gaze = alpha.head_offsets(dest)
    assert len(gaze) == 24
    assert gaze[0] == [0.0, 0.0]
    assert gaze[6][0] > 0.8, f"yeux a droite a 0,5 s : {gaze[6]}"
    assert gaze[18][0] < -0.8, f"yeux a gauche a 1,5 s : {gaze[18]}"
    assert all(dy == 0.0 for _, dy in gaze), "aucun mouvement vertical"


def test_put_on_green_fills_transparent_pixels(tmp_path):
    src = tmp_path / "subject.png"
    dest = tmp_path / "on-green.png"
    subprocess.run(
        [alpha.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i",
         "color=c=red:s=100x100,format=rgba,pad=200:200:50:50:color=black@0.0",
         "-frames:v", "1", str(src)],
        check=True,
    )

    alpha.put_on_green(src, dest)

    assert alpha.image_size(dest) == (200, 200)
    r, g, b = _pixel(dest, 5, 5)
    assert r < 10 and g > 245 and b < 10, f"fond vert attendu : {(r, g, b)}"
    red = _pixel(dest, 100, 100)
    assert red[0] > 240 and red[1] < 20

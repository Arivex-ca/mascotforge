"""Fiches JSON de blobs sur mesure pour Blob Atelier.

La fiche reste de la donnee. Python echantillonne son contour, le mesure et
transmet uniquement des nombres valides au moteur JavaScript.
"""
from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from backend import settings

POINT_COUNT = 72
CURVE_STEPS = 8
PREVIEW_TIMEOUT_S = 60
STATES = ("idle", "listening", "thinking", "talking", "working", "happy", "done", "error")
KINDS = {"round", "oval", "bean", "rounded-square", "drop"}
MATERIALS = {"soft", "matte", "jelly", "glass", "clay", "velvet"}
SHAPES = {"mochi", "bean", "pebble", "squircle", "pill", "drop", "kitty", "cloud"}
ANIMALS = {"bunny", "cat", "dog", "frog", "hamster", "bear", "panda", "chick"}
FABRICS = {"fluffy", "knit", "felt"}
EYES = {"capsule", "dot"}
PALETTE = {
    "lilac", "milk", "peach", "butter", "matcha", "mint", "sky",
    "bubblegum", "tangerine", "cocoa", "ink",
}
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
HEX_SHORT_OR_LONG_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
ACC_COLORS = {"ink", "cream", "tomato", "blush", "mustard", "sage", "sky", "lilac"}
BUILTIN_ACCESSORIES = {"none", "beret", "glasses", "sunglasses"}
ACCESSORY_ANCHORS = {"crown", "eyes", "nose", "left-ear", "right-ear", "neck", "left-side", "right-side"}
ACCESSORY_SHAPES = {
    "sphere": 1,
    "torus": 2,
    "cylinder": 2,
    "cone": 2,
    "rounded-box": 4,
    "capsule": 2,
}
ACCESSORY_MATERIALS = {"felt", "knit", "fur", "glossy-plastic", "metal", "glass"}
STATE_NUMBERS = {
    "lid": (0.04, 1.2),
    "eye": (0.5, 1.5),
    "tilt": (-30, 30),
    "squash": (-0.12, 0.12),
    "breathAmount": (0, 0.08),
    "blink": (0.1, 4),
    "bob": (0, 30),
    "bobSpeed": (0, 10),
    "bounce": (0, 0.12),
    "bounceSpeed": (0, 10),
    "hop": (0, 60),
    "hopSpeed": (0, 10),
    "shake": (0, 30),
    "shakeSpeed": (0, 20),
    "pulse": (0, 1),
    "pulseSpeed": (0, 20),
    "enterSquash": (-6, 6),
    "enterSparks": (0, 8),
}
STATE_KEYS = set(STATE_NUMBERS) | {
    "name", "like", "gaze", "scan", "orbit", "breath", "expression",
    "badge", "badgeColor", "accessory",
}


class BlobSpecError(ValueError):
    """Fiche refusee, avec des erreurs exploitables par un agent."""

    def __init__(self, issues: list[dict]) -> None:
        super().__init__("La fiche de blob contient encore des erreurs.")
        self.issues = issues


class BlobRenderError(RuntimeError):
    pass


def _issue(where: str, message: str, fix: str) -> dict:
    return {"level": "error", "where": where, "message": message, "fix": fix}


def _number(value: object, where: str, low: float, high: float, issues: list[dict]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        issues.append(_issue(where, "La valeur doit etre un nombre fini.", f"Utilisez un nombre entre {low:g} et {high:g}."))
        return None
    number = float(value)
    if number < low or number > high:
        issues.append(_issue(where, f"La valeur {number:g} est hors bornes [{low:g}, {high:g}].", f"Ramenez {where} entre {low:g} et {high:g}."))
        return None
    return number


def _sp(value: float, power: float) -> float:
    return math.copysign(abs(value) ** power, value)


def _sample(base: dict, bumps: list[dict]) -> list[list[float]]:
    points: list[list[float]] = []
    width = base["width"]
    height = base["height"]
    roundness = base["roundness"]
    kind = base["kind"]
    for index in range(POINT_COUNT):
        angle = index / POINT_COUNT * math.tau
        x = width * _sp(math.cos(angle), 2 / roundness)
        y = height * _sp(math.sin(angle), 2 / roundness)
        if kind == "bean":
            x += 0.15 * (y * y - 0.42)
        if kind == "drop":
            top = max(0.0, -math.sin(angle))
            x *= 1 - 0.38 * top ** 2.4
            y -= 0.22 * top ** 4
        for bump in bumps:
            center = math.radians(bump["angle"])
            delta = (angle - center + math.pi) % math.tau - math.pi
            sigma = math.radians(bump["width"]) / 2.355
            amount = bump["height"] * math.exp(-0.5 * (delta / sigma) ** 2)
            x += math.cos(center) * amount
            y += math.sin(center) * amount
        points.append([round(x, 6), round(y, 6)])
    return points


def _orientation(a: list[float], b: list[float], c: list[float]) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _segments_cross(a: list[float], b: list[float], c: list[float], d: list[float]) -> bool:
    return _orientation(a, b, c) * _orientation(a, b, d) < -1e-9 and _orientation(c, d, a) * _orientation(c, d, b) < -1e-9


def _polyline_self_intersects(points: list[list[float]]) -> bool:
    size = len(points)
    for first in range(size):
        a, b = points[first], points[(first + 1) % size]
        for second in range(first + 2, size):
            if first == 0 and second == size - 1:
                continue
            c, d = points[second], points[(second + 1) % size]
            if _segments_cross(a, b, c, d):
                return True
    return False


def _curve_points(points: list[list[float]]) -> list[list[float]]:
    """Echantillonne les cubiques Catmull-Rom utilisees par pathD du moteur."""
    curve: list[list[float]] = []
    size = len(points)
    for index in range(size):
        a = points[(index - 1) % size]
        b = points[index]
        c = points[(index + 1) % size]
        following = points[(index + 2) % size]
        c1 = [b[0] + (c[0] - a[0]) / 6, b[1] + (c[1] - a[1]) / 6]
        c2 = [c[0] - (following[0] - b[0]) / 6, c[1] - (following[1] - b[1]) / 6]
        for step in range(CURVE_STEPS):
            t = step / CURVE_STEPS
            u = 1 - t
            curve.append([
                u ** 3 * b[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t ** 3 * c[0],
                u ** 3 * b[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t ** 3 * c[1],
            ])
    return curve


def _self_intersects(points: list[list[float]]) -> bool:
    """Controle les segments et la courbe cubique reellement rendue."""
    return _polyline_self_intersects(points) or _polyline_self_intersects(_curve_points(points))


def _validate_contour(contour: object, issues: list[dict]) -> list[list[float]] | None:
    start = len(issues)
    if not isinstance(contour, dict):
        issues.append(_issue("contour", "Le contour doit etre un objet.", "Ajoutez contour.base et contour.bumps."))
        return None
    unknown_contour = set(contour) - {"base", "bumps"}
    if unknown_contour:
        issues.append(_issue("contour", f"Champ inconnu : {', '.join(sorted(unknown_contour))}.", "Gardez uniquement base et bumps."))

    raw_base = contour.get("base")
    base: dict[str, object] = raw_base if isinstance(raw_base, dict) else {}
    if not isinstance(raw_base, dict):
        issues.append(_issue("contour.base", "La base doit etre un objet.", "Ajoutez kind, width, height et roundness."))
    unknown_base = set(base) - {"kind", "width", "height", "roundness"}
    if unknown_base:
        issues.append(_issue("contour.base", f"Champ inconnu : {', '.join(sorted(unknown_base))}.", "Gardez uniquement kind, width, height et roundness."))
    kind = base.get("kind")
    if kind not in KINDS:
        issues.append(_issue("contour.base.kind", f"Base {kind!r} inconnue.", f"Choisissez parmi {', '.join(sorted(KINDS))}."))
    width = _number(base.get("width"), "contour.base.width", 0.2, 1.5, issues)
    height = _number(base.get("height"), "contour.base.height", 0.2, 1.5, issues)
    roundness = _number(base.get("roundness"), "contour.base.roundness", 1.6, 6.0, issues)

    raw_bumps = contour.get("bumps")
    if not isinstance(raw_bumps, list):
        issues.append(_issue("contour.bumps", "Les bosses doivent former une liste.", "Utilisez une liste vide ou au plus 24 bosses."))
        raw_bumps = []
    elif len(raw_bumps) > 24:
        issues.append(_issue("contour.bumps", f"Le contour contient {len(raw_bumps)} bosses, maximum 24.", "Fusionnez ou retirez des bosses."))
    bumps: list[dict] = []
    for index, raw in enumerate(raw_bumps[:24]):
        where = f"contour.bumps[{index}]"
        if not isinstance(raw, dict):
            issues.append(_issue(where, "Une bosse doit etre un objet.", "Ajoutez angle, height et width."))
            continue
        unknown = set(raw) - {"angle", "height", "width"}
        if unknown:
            issues.append(_issue(where, f"Champ inconnu : {', '.join(sorted(unknown))}.", "Gardez uniquement angle, height et width."))
        angle = _number(raw.get("angle"), f"{where}.angle", -180, 180, issues)
        bump_height = _number(raw.get("height"), f"{where}.height", -0.45, 1.2, issues)
        bump_width = _number(raw.get("width"), f"{where}.width", 5, 90, issues)
        if None not in (angle, bump_height, bump_width):
            bumps.append({"angle": angle, "height": bump_height, "width": bump_width})

    if len(issues) != start or None in (width, height, roundness):
        return None
    points = _sample({"kind": kind, "width": width, "height": height, "roundness": roundness}, bumps)
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    smallest, largest = min(span_x, span_y), max(span_x, span_y)
    minimum_radius = min(math.hypot(*point) for point in points)
    if _self_intersects(points):
        issues.append(_issue("contour", "Le contour se croise.", "Reduisez la hauteur des bosses ou augmentez leur largeur."))
    if largest > 3.2:
        issues.append(_issue("contour", f"Le contour est trop grand ({largest:.2f}, maximum 3.20).", "Reduisez la base ou la hauteur des bosses."))
    if largest < 0.8:
        issues.append(_issue("contour", f"Le contour est trop petit ({largest:.2f}, minimum 0.80).", "Agrandissez width ou height."))
    if smallest / max(largest, 1e-9) < 0.28 or minimum_radius < 0.18:
        issues.append(_issue("contour", "Le contour est trop fin pour rester lisible pendant le morphing.", "Epaississez la base ou reduisez les creux."))
    return points


def _validate_appearance(spec: dict, issues: list[dict]) -> None:
    color = spec.get("color")
    if not isinstance(color, str) or (color not in PALETTE and not _is_hex(color)):
        issues.append(_issue("color", f"Couleur {color!r} refusee.", "Utilisez une couleur Blob Atelier ou #rrggbb."))
    if spec.get("eyes") not in EYES:
        issues.append(_issue("eyes", f"Yeux {spec.get('eyes')!r} inconnus.", "Utilisez capsule ou dot."))
    if not isinstance(spec.get("cheeks"), bool):
        issues.append(_issue("cheeks", "cheeks doit etre un booleen.", "Utilisez true ou false, sans guillemets."))


def _vector(value: object, length: int, low: float, high: float, where: str, issues: list[dict]) -> list[float] | None:
    if not isinstance(value, list) or len(value) != length:
        issues.append(_issue(where, f"La valeur doit contenir exactement {length} nombres.", f"Utilisez une liste de {length} nombres entre {low:g} et {high:g}."))
        return None
    result: list[float] = []
    for index, item in enumerate(value):
        number = _number(item, f"{where}[{index}]", low, high, issues)
        if number is None:
            return None
        result.append(number)
    return result


def _validate_accessories(value: object, issues: list[dict]) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        issues.append(_issue("accessories", "accessories doit etre une liste.", "Utilisez [] ou une liste de noms et de declarations."))
        return
    registered = set(BUILTIN_ACCESSORIES)
    applied: set[str] = set()
    for index, raw in enumerate(value):
        where = f"accessories[{index}]"
        if isinstance(raw, str):
            name = raw
            if name not in registered:
                issues.append(_issue(where, f"Accessoire {name!r} inconnu.", "Utilisez un accessoire integre ou placez sa declaration avant ce nom."))
                continue
        elif isinstance(raw, dict):
            name = raw.get("name")
            if not isinstance(name, str) or not NAME_RE.fullmatch(name):
                issues.append(_issue(f"{where}.name", "Le nom doit respecter ^[a-z][a-z0-9-]{0,31}$.", "Utilisez un nom court en minuscules, chiffres et tirets."))
                continue
            if name in registered:
                issues.append(_issue(f"{where}.name", f"L'accessoire {name!r} existe deja.", "Choisissez un autre nom et mettez a jour accessories."))
                continue
            unknown = set(raw) - {"name", "anchor", "parts"}
            if unknown:
                issues.append(_issue(where, f"Champ inconnu : {', '.join(sorted(unknown))}.", "Gardez uniquement name, anchor et parts."))
            anchor = raw.get("anchor")
            if anchor not in ACCESSORY_ANCHORS:
                issues.append(_issue(f"{where}.anchor", f"Anchor {anchor!r} inconnu.", f"Choisissez parmi {', '.join(sorted(ACCESSORY_ANCHORS))}."))
            parts = raw.get("parts")
            if not isinstance(parts, list) or not parts:
                issues.append(_issue(f"{where}.parts", "parts doit etre une liste non vide.", "Ajoutez de 1 a 16 pieces."))
                continue
            if len(parts) > 16:
                issues.append(_issue(f"{where}.parts", f"L'accessoire contient {len(parts)} pieces, maximum 16.", "Retirez ou fusionnez des pieces."))
            instances = 0
            for part_index, part in enumerate(parts[:16]):
                part_where = f"{where}.parts[{part_index}]"
                if not isinstance(part, dict):
                    issues.append(_issue(part_where, "Une piece doit etre un objet.", "Ajoutez shape, size et material."))
                    continue
                unknown_part = set(part) - {"shape", "size", "material", "color", "anchor", "at", "rotate", "repeat", "arc"}
                if unknown_part:
                    issues.append(_issue(part_where, f"Champ inconnu : {', '.join(sorted(unknown_part))}.", "Retirez les champs non documentes."))
                shape = part.get("shape")
                if shape not in ACCESSORY_SHAPES:
                    issues.append(_issue(f"{part_where}.shape", f"Shape {shape!r} inconnu.", f"Choisissez parmi {', '.join(sorted(ACCESSORY_SHAPES))}."))
                    size = None
                else:
                    size = _vector(part.get("size"), ACCESSORY_SHAPES[shape], 0.01, 2, f"{part_where}.size", issues)
                material = part.get("material")
                if material not in ACCESSORY_MATERIALS:
                    issues.append(_issue(f"{part_where}.material", f"Material {material!r} inconnu.", f"Choisissez parmi {', '.join(sorted(ACCESSORY_MATERIALS))}."))
                if part.get("anchor", anchor) not in ACCESSORY_ANCHORS:
                    issues.append(_issue(f"{part_where}.anchor", f"Anchor {part.get('anchor')!r} inconnu.", f"Choisissez parmi {', '.join(sorted(ACCESSORY_ANCHORS))}."))
                if "at" in part:
                    _vector(part["at"], 3, -2, 2, f"{part_where}.at", issues)
                if "rotate" in part:
                    _vector(part["rotate"], 3, -360, 360, f"{part_where}.rotate", issues)
                repeat = part.get("repeat", 1)
                if isinstance(repeat, bool) or not isinstance(repeat, int) or not 1 <= repeat <= 12:
                    issues.append(_issue(f"{part_where}.repeat", "repeat doit etre un entier entre 1 et 12.", "Ramenez repeat entre 1 et 12."))
                    repeat = 0
                instances += repeat
                color = part.get("color")
                if color is not None and (not isinstance(color, str) or (color not in ACC_COLORS and not HEX_SHORT_OR_LONG_RE.fullmatch(color))):
                    issues.append(_issue(f"{part_where}.color", f"Color {color!r} refusee.", "Utilisez un nom acc-color ou une couleur #RGB ou #RRGGBB."))
                if "arc" in part:
                    if shape != "torus":
                        issues.append(_issue(f"{part_where}.arc", "arc est reserve aux pieces torus.", "Retirez arc ou utilisez shape torus."))
                    else:
                        _number(part["arc"], f"{part_where}.arc", 1, 360, issues)
                if size is not None and shape == "torus" and size[1] >= size[0] / 2:
                    issues.append(_issue(f"{part_where}.size", "Le tube du torus doit etre plus petit que la moitie de son diametre.", "Reduisez size[1]."))
                if size is not None and shape == "capsule" and size[1] < size[0]:
                    issues.append(_issue(f"{part_where}.size", "La hauteur de la capsule doit atteindre son diametre.", "Augmentez size[1] ou reduisez size[0]."))
                if size is not None and shape == "rounded-box" and size[3] > min(size[0], size[1]) / 2:
                    issues.append(_issue(f"{part_where}.size", "Le rayon du rounded-box depasse la moitie de sa largeur ou hauteur.", "Reduisez size[3]."))
            if instances > 64:
                issues.append(_issue(f"{where}.parts", f"L'accessoire produit {instances} pieces, maximum 64.", "Reduisez repeat ou le nombre de parts."))
            registered.add(name)
        else:
            issues.append(_issue(where, "Un accessoire doit etre un nom ou une declaration.", "Utilisez une chaine ou un objet avec name, anchor et parts."))
            continue
        if name != "none":
            if name in applied:
                issues.append(_issue(where, f"L'accessoire {name!r} est applique deux fois.", "Gardez une seule occurrence pour conserver un ordre clair."))
            applied.add(name)


def _validate_states(value: object, issues: list[dict]) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        issues.append(_issue("states", "states doit etre une liste.", "Utilisez [] ou une liste de declarations d'etat."))
        return
    if len(value) > 32:
        issues.append(_issue("states", f"La fiche declare {len(value)} etats libres, maximum 32.", "Retirez ou fusionnez des etats."))
    recipes: dict[str, dict] = {name: {} for name in STATES}
    for index, raw in enumerate(value[:32]):
        where = f"states[{index}]"
        before = len(issues)
        if not isinstance(raw, dict):
            issues.append(_issue(where, "Un etat doit etre un objet.", "Ajoutez name, like et les reglages voulus."))
            continue
        unknown = set(raw) - STATE_KEYS
        if unknown:
            issues.append(_issue(where, f"Reglage inconnu : {', '.join(sorted(unknown))}.", "Retirez-le ou utilisez un reglage documente."))
        name = raw.get("name")
        if not isinstance(name, str) or not NAME_RE.fullmatch(name):
            issues.append(_issue(f"{where}.name", "Le nom doit respecter ^[a-z][a-z0-9-]{0,31}$.", "Utilisez un nom court en minuscules, chiffres et tirets."))
        elif name in STATES:
            issues.append(_issue(f"{where}.name", f"L'etat integre {name!r} ne peut pas etre remplace.", "Choisissez un autre nom et utilisez like pour en heriter."))
        elif name in recipes:
            issues.append(_issue(f"{where}.name", f"L'etat {name!r} existe deja.", "Gardez une seule declaration par nom."))
        parent_name = raw.get("like")
        if not isinstance(parent_name, str) or parent_name not in recipes:
            issues.append(_issue(f"{where}.like", f"like {parent_name!r} ne nomme pas un etat existant.", "Utilisez un etat integre ou un etat libre declare plus haut."))
            parent: dict = {}
        else:
            parent = recipes[parent_name]
        settings = dict(parent)
        gaze_keys = [key for key in ("gaze", "scan", "orbit") if key in raw]
        if len(gaze_keys) > 1:
            issues.append(_issue(where, "Utilisez un seul reglage parmi gaze, scan et orbit.", "Retirez les reglages de regard en trop."))
        elif gaze_keys:
            for key in ("gaze", "scan", "orbit"):
                settings.pop(key, None)
        for key, (low, high) in STATE_NUMBERS.items():
            if key not in raw:
                continue
            number = _number(raw[key], f"{where}.{key}", low, high, issues)
            if number is not None:
                if key == "enterSparks" and not number.is_integer():
                    issues.append(_issue(f"{where}.{key}", "enterSparks doit etre un nombre entier entre 0 et 8.", "Utilisez 0, 1, 2, 3, 4, 5, 6, 7 ou 8."))
                else:
                    settings[key] = int(number) if key == "enterSparks" else number
        if "breath" in raw:
            breath = raw["breath"]
            if isinstance(breath, bool) or not isinstance(breath, (int, float)) or not math.isfinite(breath) or (breath != 0 and not 0.2 <= breath <= 20):
                issues.append(_issue(f"{where}.breath", "breath doit valoir 0 ou une periode entre 0.2 et 20 secondes.", "Utilisez 0 pour couper la respiration, sinon une valeur de 0.2 a 20."))
            else:
                settings["breath"] = float(breath)
        if "gaze" in raw:
            gaze = _vector(raw["gaze"], 2, -1, 1, f"{where}.gaze", issues)
            if gaze is not None:
                settings["gaze"] = gaze
        if "scan" in raw:
            scan = _vector(raw["scan"], 4, -20, 20, f"{where}.scan", issues)
            if scan is not None:
                if not (-1 <= scan[0] <= scan[1] <= 1 and -1 <= scan[2] <= 1 and 0.2 <= scan[3] <= 20):
                    issues.append(_issue(f"{where}.scan", "scan doit etre [minX, maxX, y, secondes] avec minX <= maxX, des regards entre -1 et 1 et une periode de 0.2 a 20.", "Corrigez l'ordre et les bornes des quatre valeurs."))
                else:
                    settings["scan"] = scan
        if "orbit" in raw:
            orbit = _vector(raw["orbit"], 3, 0, 20, f"{where}.orbit", issues)
            if orbit is not None:
                if orbit[0] > 1 or orbit[1] > 1 or not 0.2 <= orbit[2] <= 20:
                    issues.append(_issue(f"{where}.orbit", "orbit doit etre [radiusX, radiusY, secondes], avec des rayons de 0 a 1 et une periode de 0.2 a 20.", "Corrigez les deux rayons ou la periode."))
                else:
                    settings["orbit"] = orbit
        choices = {
            "expression": {"none", "happy", "chevrons"},
            "badge": {"none", "check", "exclamation", "pause"},
            "accessory": {"none", "rings", "dots", "orbit"},
        }
        for key, allowed in choices.items():
            if key in raw:
                if raw[key] not in allowed:
                    issues.append(_issue(f"{where}.{key}", f"Valeur {raw[key]!r} refusee.", f"Choisissez parmi {', '.join(sorted(allowed))}."))
                else:
                    settings[key] = raw[key]
        if "badgeColor" in raw:
            color = raw["badgeColor"]
            if not isinstance(color, str) or not HEX_SHORT_OR_LONG_RE.fullmatch(color):
                issues.append(_issue(f"{where}.badgeColor", "badgeColor doit etre une couleur #RGB ou #RRGGBB.", "Utilisez par exemple #30C77B."))
            else:
                settings["badgeColor"] = color
        for speed, motion in (("bobSpeed", "bob"), ("bounceSpeed", "bounce"), ("hopSpeed", "hop"), ("shakeSpeed", "shake"), ("pulseSpeed", "pulse")):
            if speed in settings and motion not in settings:
                issues.append(_issue(f"{where}.{speed}", f'"{speed}" requires "{motion}".', f"Ajoutez {motion} a cet etat ou a son parent."))
                break
        if len(issues) == before and isinstance(name, str):
            recipes[name] = settings


def _check_v1(spec: dict, issues: list[dict]) -> list[list[float]] | None:
    unknown = set(spec) - {"version", "name", "contour", "material", "color", "eyes", "cheeks"}
    if unknown:
        issues.append(_issue("spec", f"Champ inconnu : {', '.join(sorted(unknown))}.", "Retirez les champs non documentes de la fiche v1."))
    points = _validate_contour(spec.get("contour"), issues)
    if spec.get("material") not in MATERIALS:
        issues.append(_issue("material", f"Matiere {spec.get('material')!r} inconnue.", f"Choisissez parmi {', '.join(sorted(MATERIALS))}."))
    _validate_appearance(spec, issues)
    return points


def _check_v2(spec: dict, issues: list[dict]) -> list[list[float]] | None:
    allowed = {
        "version", "name", "series", "shape", "contour", "animal", "material", "fabric",
        "color", "eyes", "cheeks", "accessories", "acc_color", "states",
    }
    unknown = set(spec) - allowed
    if unknown:
        issues.append(_issue("spec", f"Champ inconnu : {', '.join(sorted(unknown))}.", "Retirez les champs non documentes de la fiche v2."))
    points = None
    series = spec.get("series")
    if series not in {"blob", "animal"}:
        issues.append(_issue("series", f"Serie {series!r} inconnue.", "Utilisez blob ou animal."))
    elif series == "blob":
        has_shape = "shape" in spec
        has_contour = "contour" in spec
        if has_shape == has_contour:
            issues.append(_issue("series", "Un blob doit definir shape ou contour, exactement un des deux.", "Gardez une forme nommee dans shape ou un contour sur mesure dans contour."))
        elif has_shape and spec.get("shape") not in SHAPES:
            issues.append(_issue("shape", f"Shape {spec.get('shape')!r} inconnu.", f"Choisissez parmi {', '.join(sorted(SHAPES))}."))
        elif has_contour:
            points = _validate_contour(spec.get("contour"), issues)
        if spec.get("material") not in MATERIALS:
            issues.append(_issue("material", f"Matiere {spec.get('material')!r} inconnue pour un blob.", f"Choisissez parmi {', '.join(sorted(MATERIALS))}."))
        for forbidden in ("animal", "fabric"):
            if forbidden in spec:
                issues.append(_issue(forbidden, f"{forbidden} ne s'applique pas a la serie blob.", f"Retirez {forbidden}."))
    elif series == "animal":
        if spec.get("animal") not in ANIMALS:
            issues.append(_issue("animal", f"Animal {spec.get('animal')!r} inconnu.", f"Choisissez parmi {', '.join(sorted(ANIMALS))}."))
        if spec.get("fabric") not in FABRICS:
            issues.append(_issue("fabric", f"Tissu {spec.get('fabric')!r} inconnu.", f"Choisissez parmi {', '.join(sorted(FABRICS))}."))
        for forbidden in ("shape", "contour", "material"):
            if forbidden in spec:
                issues.append(_issue(forbidden, f"{forbidden} ne s'applique pas a la serie animal.", f"Retirez {forbidden} et utilisez animal avec fabric."))
    _validate_appearance(spec, issues)
    acc_color = spec.get("acc_color", "ink")
    if not isinstance(acc_color, str) or (acc_color not in ACC_COLORS and not _is_hex(acc_color)):
        issues.append(_issue("acc_color", f"Couleur {acc_color!r} refusee.", "Utilisez un nom acc-color ou une couleur #rrggbb."))
    raw_accessories = spec.get("accessories", [])
    _validate_accessories(raw_accessories, issues)
    if series == "blob" and isinstance(raw_accessories, list):
        for index, item in enumerate(raw_accessories):
            if isinstance(item, str) and item in BUILTIN_ACCESSORIES - {"none"}:
                issues.append(_issue(
                    f"accessories[{index}]",
                    f"L'accessoire integre {item!r} est reserve aux animaux 3D.",
                    "Declarez un accessoire geometrique pour un blob, ou choisissez la serie animal.",
                ))
    _validate_states(spec.get("states", []), issues)
    return points


def check_spec(spec: dict) -> dict:
    issues: list[dict] = []
    if not isinstance(spec, dict):
        return {"ok": False, "issues": [_issue("spec", "La fiche doit etre un objet JSON.", "Envoyez un objet JSON conforme au guide blob.")]}
    name = spec.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        issues.append(_issue("name", "Le nom doit contenir de 1 a 80 caracteres.", "Donnez un nom court en texte simple."))
    version = spec.get("version")
    if version == 1:
        points = _check_v1(spec, issues)
    elif version == 2:
        points = _check_v2(spec, issues)
    else:
        points = None
        issues.append(_issue("version", f"Version {version!r} inconnue.", "Utilisez 1 pour une ancienne fiche ou 2 pour les series, accessoires et etats libres."))
    return {"ok": not issues, "issues": issues, **({"points": points} if not issues and points else {})}


def _is_hex(value: str) -> bool:
    if len(value) != 7 or not value.startswith("#"):
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value[1:])


def compile_spec(spec: dict) -> dict:
    report = check_spec(spec)
    if not report["ok"]:
        raise BlobSpecError(report["issues"])
    version = spec["version"]
    points = report.get("points")
    if version == 1 or spec.get("contour") is not None:
        digest = hashlib.sha256(json.dumps(points, separators=(",", ":")).encode()).hexdigest()[:12]
        shape = f"custom-{digest}"
    elif spec["series"] == "animal":
        shape = spec["animal"]
    else:
        shape = spec["shape"]
    material = spec["material"] if version == 1 or spec.get("series") == "blob" else spec["fabric"]
    config = {
        "shape": shape,
        "material": material,
        "color": spec["color"].lower() if _is_hex(spec["color"]) else spec["color"],
        "eyes": spec["eyes"],
        "cheeks": "true" if spec["cheeks"] else "false",
    }
    accessories: dict[str, dict] = {}
    states: dict[str, dict] = {}
    if version == 2:
        applied: list[str] = []
        for item in spec.get("accessories", []):
            if isinstance(item, str):
                if item != "none":
                    applied.append(item)
            else:
                name = item["name"]
                accessories[name] = {key: value for key, value in item.items() if key != "name"}
                applied.append(name)
        config["accessory"] = " ".join(applied) if applied else "none"
        config["acc-color"] = spec.get("acc_color", "ink")
        states = {
            item["name"]: {key: value for key, value in item.items() if key != "name"}
            for item in spec.get("states", [])
        }
    return {
        "name": str(spec["name"]).strip(),
        "series": "blob" if version == 1 else spec["series"],
        "shape": shape,
        "points": points,
        "config": config,
        "accessories": accessories,
        "states": states,
    }


def guide() -> str:
    return """# Fiche Blob Atelier v2 de MascotForge

La fiche est un objet JSON pur. N'ajoutez ni code, ni commentaire, ni expression.
Utilisez `series: \"blob\"` avec une `shape` integree ou un `contour` sur mesure.
Utilisez `series: \"animal\"` avec `animal` et `fabric`. Les animaux disponibles
sont bunny, cat, dog, frog, hamster, bear, panda et chick. Les tissus sont fluffy,
knit et felt. Les deux series acceptent color, eyes, cheeks, des accessoires
declares et jusqu'a 32 etats libres. Le moteur adoucit la couleur du corps : un
#rrggbb tres sombre ressort mauve-brun. Pour un corps fonce, prenez une teinte
moyenne ou un nom de la palette, puis verifiez dans la preview. Les accessoires
gardent leur couleur exacte. Les accessoires integres beret, glasses et
sunglasses sont reserves aux animaux 3D. Les accessoires declares fonctionnent
sur les deux series.

Un accessoire declare contient name, anchor et parts. Chaque piece contient shape,
size et material, puis peut ajouter color, anchor, at, rotate, repeat et arc. Lancez
`blob check` pour obtenir le chemin exact, la cause et la correction de chaque refus.
Les etats heritent avec `like`. Declarez un parent avant ses enfants.

Pour un contour, les angles sont en degres : -90 vise le haut, 0 la droite, 90 le
bas et 180 la gauche. `height` accepte -0.45 a 1.2. `width` accepte 5 a 90 degres.

Boucle : ecrivez la fiche, lancez `blob check`, corrigez chaque erreur, affichez
`blob preview`, puis lancez `blob export`. La planche montre les etats integres,
puis tous les etats libres, avec les accessoires appliques.

## Lapin 3D en tricot, casque audio et deux etats libres

```json
{"version":2,"name":"Nola","series":"animal","animal":"bunny","fabric":"knit","color":"sky","eyes":"dot","cheeks":true,"accessories":[{"name":"headphones","anchor":"eyes","parts":[{"shape":"torus","size":[1.9,0.1],"at":[0,0.22,-0.08],"arc":180,"material":"glossy-plastic","color":"#6E55C8"},{"shape":"capsule","size":[0.3,0.46],"at":[1.75,0,-0.02],"repeat":2,"material":"glossy-plastic","color":"#6E55C8"}]}],"acc_color":"lilac","states":[{"name":"sleeping","like":"idle","lid":0.08,"breath":4,"bob":0},{"name":"celebrating","like":"happy","hop":28,"hopSpeed":2.4,"expression":"happy","enterSparks":6}]}
```

## Blob sur mesure avec couronne et etat sleeping

```json
{"version":2,"name":"Cornu royal","series":"blob","contour":{"base":{"kind":"round","width":0.92,"height":0.88,"roundness":2.3},"bumps":[{"angle":-128,"height":0.62,"width":18},{"angle":-52,"height":0.62,"width":18}]},"material":"jelly","color":"#8b5cf6","eyes":"capsule","cheeks":true,"accessories":[{"name":"crown","anchor":"crown","parts":[{"shape":"cylinder","size":[0.72,0.14],"material":"metal","color":"mustard"},{"shape":"cone","size":[0.14,0.32],"material":"metal","color":"#ffd873","at":[0.16,0.2,0],"repeat":5}]}],"acc_color":"mustard","states":[{"name":"sleeping","like":"idle","lid":0.08,"breath":4}]}
```

Les fiches v1 avec contour, material, color, eyes et cheeks restent acceptees sans
modification. Elles n'ont ni animaux, ni accessoires declares, ni etats libres.
"""


def _browser() -> str | None:
    configured = os.getenv("MASCOTFORGE_BROWSER")
    local = Path(os.getenv("LOCALAPPDATA", ""))
    cached = sorted(
        local.glob("ms-playwright/chromium_headless_shell-*/**/*headless*shell.exe"),
        reverse=True,
    ) if str(local) else []
    candidates = [
        configured,
        *(str(path) for path in cached),
        shutil.which("chrome"),
        shutil.which("msedge"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    return next((str(path) for path in candidates if path and Path(path).is_file()), None)


def _temp_root() -> Path:
    root = settings.data_dir() / "tmp"
    root.mkdir(parents=True, exist_ok=True)
    return root


def render_sheet(spec: dict, out: Path) -> Path:
    compiled = compile_spec(spec)
    browser = _browser()
    if not browser:
        raise BlobRenderError("Chrome ou Edge est introuvable.")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mascotforge-blob-preview-", dir=_temp_root()) as tmp:
        tmp_dir = Path(tmp)
        engine_dir = settings.engines_dir() / "blob-atelier"
        shutil.copyfile(engine_dir / "agent-mascot.js", tmp_dir / "agent-mascot.js")
        if compiled["series"] == "animal":
            vendor_dir = tmp_dir / "vendor"
            vendor_dir.mkdir()
            shutil.copyfile(engine_dir / "vendor" / "three.module.min.js", vendor_dir / "three.module.min.js")
        state_names = [*STATES, *compiled["states"]]
        columns = 5
        rows = math.ceil(len(state_names) / columns)
        width = 1100
        height = 24 + rows * 210
        payload = {
            "config": compiled["config"],
            "shape": {"name": compiled["shape"], "points": compiled["points"]} if compiled["points"] else None,
            "accessories": compiled["accessories"],
            "states": compiled["states"],
            "stateNames": state_names,
            "animal": compiled["series"] == "animal",
        }
        # "<" escaped so no JSON string can close the <script> tag.
        data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
        page = f"""<!doctype html><meta charset=\"utf-8\"><style>
html,body{{margin:0;background:#f6f3ee;font:16px system-ui;color:#232228}}
main{{width:{width}px;min-height:{height}px;box-sizing:border-box;padding:24px;display:grid;grid-template-columns:repeat({columns},1fr);gap:14px}}
section{{height:182px;background:white;border:1px solid #ddd6ce;border-radius:18px;display:grid;place-items:center;padding:6px}}
agent-mascot{{width:160px;height:150px}}b{{font-size:13px}}
</style><main></main><script src=\"agent-mascot.js\"></script><script>
const data={data_json};
const warnings=[];
const originalWarn=console.warn;
console.warn=function(){{
  const message=Array.from(arguments).map(value=>value&&value.message?value.message:String(value)).join(' ');
  warnings.push(message); originalWarn.apply(console,arguments);
}};
let reported=false;
function report(ok,message){{
  if(reported)return; reported=true;
  fetch('/__mascotforge_result',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{ok,message}})}}).catch(()=>{{}});
}}
function declare(kind,name,callback){{
  warnings.length=0;
  if(!callback()) throw new Error(warnings[warnings.length-1]||('agent-mascot: '+kind+' '+name+' refused'));
}}
try{{
  AgentMascot.THREE_URL='./vendor/three.module.min.js';
  Object.entries(data.accessories).forEach(([name,definition])=>declare('accessory',name,()=>AgentMascot.defineAccessory(name,definition)));
  Object.entries(data.states).forEach(([name,recipe])=>declare('state',name,()=>AgentMascot.defineState(name,recipe)));
  if(data.shape) declare('shape',data.shape.name,()=>AgentMascot.defineShape(data.shape.name,data.shape.points));
  const main=document.querySelector('main');
  data.stateNames.forEach(state=>{{
    const card=document.createElement('section');
    const mascot=document.createElement('agent-mascot');
    Object.entries(data.config).forEach(([name,value])=>mascot.setAttribute(name,String(value)));
    mascot.setAttribute('state',state); mascot.setAttribute('still','');
    const label=document.createElement('b'); label.textContent=state;
    card.append(mascot,label); main.appendChild(card);
  }});
  const deadline=performance.now()+25000;
  function waitForRender(){{
    const mascots=Array.from(document.querySelectorAll('agent-mascot'));
    if(!data.animal){{ requestAnimationFrame(()=>requestAnimationFrame(()=>report(true,'SVG ready'))); return; }}
    if(mascots.length&&mascots.every(mascot=>mascot.is3D)){{ report(true,'3D ready'); return; }}
    const engineFailure=warnings.find(message=>message.includes('3D animals unavailable'));
    if(engineFailure||performance.now()>deadline){{ report(false,engineFailure||'agent-mascot: 3D animal did not become ready with local three.js.'); return; }}
    setTimeout(waitForRender,100);
  }}
  waitForRender();
}}catch(error){{ report(false,error&&error.message?error.message:String(error)); }}
</script>"""
        source = tmp_dir / "preview.html"
        source.write_text(page, encoding="utf-8")
        temp_png = tmp_dir / "preview.png"
        result: dict[str, object] = {}

        class PreviewHandler(SimpleHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                return

            def do_POST(self) -> None:
                if self.path != "/__mascotforge_result":
                    self.send_error(404)
                    return
                try:
                    length = min(int(self.headers.get("Content-Length", "0")), 16_384)
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                    if isinstance(body, dict):
                        result.update(body)
                except (ValueError, UnicodeError, json.JSONDecodeError):
                    result.update({"ok": False, "message": "Le navigateur a renvoye un resultat illisible."})
                self.send_response(204)
                self.end_headers()

        handler = functools.partial(PreviewHandler, directory=str(tmp_dir))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        command = [browser]
        if "headless-shell" not in Path(browser).name.lower():
            command.append("--headless=new")
        command += [
            "--no-sandbox", "--hide-scrollbars", "--enable-webgl", "--ignore-gpu-blocklist",
            "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
            f"--user-data-dir={tmp_dir / 'profile'}", "--allow-file-access-from-files",
            f"--window-size={width},{height}", "--force-device-scale-factor=1",
            "--run-all-compositor-stages-before-draw", "--virtual-time-budget=30000",
            f"--screenshot={temp_png}", f"http://127.0.0.1:{server.server_address[1]}/preview.html",
        ]
        try:
            try:
                proc = subprocess.run(command, capture_output=True, text=True, timeout=PREVIEW_TIMEOUT_S)
            except subprocess.TimeoutExpired as exc:
                raise BlobRenderError("Le navigateur a depasse 60 s.") from exc
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        if proc.returncode != 0 or not temp_png.is_file():
            detail = (proc.stderr or proc.stdout or f"code {proc.returncode}").strip()[-300:]
            raise BlobRenderError(f"Le navigateur n'a pas produit la planche : {detail}")
        if result.get("ok") is not True:
            message = str(result.get("message") or "Le moteur n'a pas confirme le rendu de la planche.")
            raise BlobRenderError(message)
        shutil.copyfile(temp_png, out)
    return out


def render_agent_sheet(spec: dict) -> bytes:
    with tempfile.TemporaryDirectory(prefix="mascotforge-blob-agent-", dir=_temp_root()) as tmp:
        path = Path(tmp) / "planche.png"
        render_sheet(spec, path)
        return path.read_bytes()

"""Fiches JSON de blobs sur mesure pour Blob Atelier.

La fiche reste de la donnee. Python echantillonne son contour, le mesure et
transmet uniquement des nombres valides au moteur JavaScript.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from backend import settings

POINT_COUNT = 72
CURVE_STEPS = 8
PREVIEW_TIMEOUT_S = 60
STATES = ("idle", "listening", "thinking", "talking", "working", "happy", "done", "error")
KINDS = {"round", "oval", "bean", "rounded-square", "drop"}
MATERIALS = {"soft", "matte", "jelly", "glass", "clay", "velvet"}
EYES = {"capsule", "dot"}
PALETTE = {
    "lilac", "milk", "peach", "butter", "matcha", "mint", "sky",
    "bubblegum", "tangerine", "cocoa", "ink",
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


def check_spec(spec: dict) -> dict:
    issues: list[dict] = []
    if not isinstance(spec, dict):
        return {"ok": False, "issues": [_issue("spec", "La fiche doit etre un objet JSON.", "Envoyez un objet JSON avec name, contour et apparence.")]}

    name = spec.get("name")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 80:
        issues.append(_issue("name", "Le nom doit contenir de 1 a 80 caracteres.", "Donnez un nom court en texte simple."))

    contour = spec.get("contour")
    if not isinstance(contour, dict):
        issues.append(_issue("contour", "Le contour doit etre un objet.", "Ajoutez contour.base et contour.bumps."))
        return {"ok": False, "issues": issues}
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

    material = spec.get("material")
    color = spec.get("color")
    eyes = spec.get("eyes")
    cheeks = spec.get("cheeks")
    if material not in MATERIALS:
        issues.append(_issue("material", f"Matiere {material!r} inconnue.", f"Choisissez parmi {', '.join(sorted(MATERIALS))}."))
    if not isinstance(color, str) or (color not in PALETTE and not _is_hex(color)):
        issues.append(_issue("color", f"Couleur {color!r} refusee.", "Utilisez une couleur Blob Atelier ou #rrggbb."))
    if eyes not in EYES:
        issues.append(_issue("eyes", f"Yeux {eyes!r} inconnus.", "Utilisez capsule ou dot."))
    if not isinstance(cheeks, bool):
        issues.append(_issue("cheeks", "cheeks doit etre un booleen.", "Utilisez true ou false, sans guillemets."))
    unknown = set(spec) - {"version", "name", "contour", "material", "color", "eyes", "cheeks"}
    if unknown:
        issues.append(_issue("spec", f"Champ inconnu : {', '.join(sorted(unknown))}.", "Retirez les champs non documentes."))
    if spec.get("version") != 1:
        issues.append(_issue("version", "La version doit etre 1.", "Utilisez \"version\": 1."))

    points: list[list[float]] | None = None
    if not issues and width is not None and height is not None and roundness is not None:
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

    return {"ok": not issues, "issues": issues, **({"points": points} if not issues and points else {})}


def _is_hex(value: str) -> bool:
    if len(value) != 7 or not value.startswith("#"):
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value[1:])


def compile_spec(spec: dict) -> dict:
    report = check_spec(spec)
    if not report["ok"]:
        raise BlobSpecError(report["issues"])
    points = report["points"]
    digest = hashlib.sha256(json.dumps(points, separators=(",", ":")).encode()).hexdigest()[:12]
    return {
        "name": str(spec["name"]).strip(),
        "shape": f"custom-{digest}",
        "points": points,
        "config": {
            "shape": f"custom-{digest}",
            "material": spec["material"],
            "color": spec["color"].lower() if _is_hex(spec["color"]) else spec["color"],
            "eyes": spec["eyes"],
            "cheeks": "true" if spec["cheeks"] else "false",
        },
    }


def guide() -> str:
    return """# Fiche de blob sur mesure MascotForge

La fiche est un objet JSON pur. N'ajoutez ni code, ni commentaire, ni expression.
Le contour part d'une superellipse puis ajoute au plus 24 bosses. Les angles sont
en degres : -90 vise le haut, 0 la droite, 90 le bas et 180 la gauche. `height`
accepte -0.45 a 1.2. Une valeur positive sort le contour, une valeur negative le
creuse. `width` est la largeur angulaire de la bosse, entre 5 et 90 degres.

Boucle : ecrivez la fiche, lancez `blob check`, corrigez chaque erreur, affichez
`blob preview`, puis lancez `blob export`. La planche montre les huit etats.

## Blob a deux cornes

```json
{"version":1,"name":"Cornu","contour":{"base":{"kind":"round","width":0.92,"height":0.88,"roundness":2.3},"bumps":[{"angle":-128,"height":0.62,"width":18},{"angle":-52,"height":0.62,"width":18}]},"material":"jelly","color":"#8b5cf6","eyes":"capsule","cheeks":true}
```

## Etoile

```json
{"version":1,"name":"Etoile","contour":{"base":{"kind":"round","width":0.72,"height":0.72,"roundness":2},"bumps":[{"angle":-90,"height":0.58,"width":22},{"angle":-18,"height":0.58,"width":22},{"angle":54,"height":0.58,"width":22},{"angle":126,"height":0.58,"width":22},{"angle":-162,"height":0.58,"width":22}]},"material":"matte","color":"butter","eyes":"dot","cheeks":false}
```

## Haricot tordu

```json
{"version":1,"name":"Haricot tordu","contour":{"base":{"kind":"bean","width":0.72,"height":1.02,"roundness":2.2},"bumps":[{"angle":-25,"height":0.28,"width":48},{"angle":155,"height":-0.22,"width":55}]},"material":"clay","color":"matcha","eyes":"capsule","cheeks":true}
```
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


def render_sheet(spec: dict, out: Path) -> Path:
    compiled = compile_spec(spec)
    browser = _browser()
    if not browser:
        raise BlobRenderError("Chrome ou Edge est introuvable.")
    engine_uri = settings.engines_dir().joinpath("blob-atelier", "agent-mascot.js").resolve().as_uri()
    escaped = {
        key: html.escape(str(value), quote=True)
        for key, value in compiled["config"].items()
    }
    cards = "".join(
        f'<section><agent-mascot shape="{escaped["shape"]}" material="{escaped["material"]}" color="{escaped["color"]}" eyes="{escaped["eyes"]}" cheeks="{escaped["cheeks"]}" state="{state}" still></agent-mascot><b>{state}</b></section>'
        for state in STATES
    )
    shape_json = json.dumps({"name": compiled["shape"], "points": compiled["points"]})
    page = f"""<!doctype html><meta charset=\"utf-8\"><style>
html,body{{margin:0;background:#f6f3ee;font:16px system-ui;color:#232228}}
main{{width:960px;height:600px;box-sizing:border-box;padding:28px;display:grid;grid-template-columns:repeat(4,1fr);gap:18px}}
section{{background:white;border:1px solid #ddd6ce;border-radius:20px;display:grid;place-items:center;padding:8px}}
agent-mascot{{width:180px;height:205px}}b{{font-size:14px}}
</style><main>{cards}</main><script src=\"{html.escape(engine_uri, quote=True)}\"></script><script>
const shape={shape_json}; if(!window.AgentMascot.defineShape(shape.name,shape.points)) throw new Error('invalid shape');
document.querySelectorAll('agent-mascot').forEach(el=>el.setAttribute('shape',shape.name));
</script>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mascotforge-blob-preview-") as tmp:
        tmp_dir = Path(tmp)
        source = tmp_dir / "preview.html"
        source.write_text(page, encoding="utf-8")
        temp_png = tmp_dir / "preview.png"
        command = [browser]
        if "headless-shell" not in Path(browser).name.lower():
            command.append("--headless=new")
        command += [
            "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
            f"--user-data-dir={tmp_dir / 'profile'}", "--allow-file-access-from-files",
            "--window-size=960,600", "--force-device-scale-factor=1",
            "--run-all-compositor-stages-before-draw", "--virtual-time-budget=1200",
            f"--screenshot={temp_png}", source.resolve().as_uri(),
        ]
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=PREVIEW_TIMEOUT_S)
        except subprocess.TimeoutExpired as exc:
            raise BlobRenderError("Le navigateur a depasse 60 s.") from exc
        if proc.returncode != 0 or not temp_png.is_file():
            detail = (proc.stderr or proc.stdout or f"code {proc.returncode}").strip()[-300:]
            raise BlobRenderError(f"Le navigateur n'a pas produit la planche : {detail}")
        shutil.copyfile(temp_png, out)
    return out


def render_agent_sheet(spec: dict) -> bytes:
    with tempfile.TemporaryDirectory(prefix="mascotforge-blob-agent-") as tmp:
        path = Path(tmp) / "planche.png"
        render_sheet(spec, path)
        return path.read_bytes()

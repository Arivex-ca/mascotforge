"""Mascottes en code : moteurs open source tiers, embarques dans engines/.

Une mascotte en code ne passe ni par fal.ai ni par le pipeline : elle tient
dans un manifest (moteur + reglages) que le widget <mascot-avatar> lit comme
un manifest video. Gratuit, instantane, et la mascotte suit le curseur d'elle-meme.

  blob : Blob Atelier (Victoria Wu, MIT), blobs SVG et animaux en vraie 3D.
         three.js est embarque uniquement dans les exports animaux.
  3d   : Wobnimo (Pourya Akhbari, MIT), 20 personnages, 10 humeurs.
"""
from __future__ import annotations

import re

from backend import blob, image3d, settings

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

ENGINES: dict[str, dict] = {
    "blob": {
        "label": "Blob en code",
        "credit": "Blob Atelier, par Victoria Wu (licence MIT)",
        "source": "https://github.com/victoriawu-77/blob-atelier",
        "tag": "agent-mascot",
        "script": "blob-atelier/agent-mascot.js",
        "license": "blob-atelier/LICENSE",
        "states": ["idle", "listening", "thinking", "talking", "working", "happy", "done", "error"],
        "options": {
            "shape": ["mochi", "bean", "pebble", "squircle", "pill", "drop", "kitty", "cloud",
                      "bunny", "cat", "dog", "frog", "hamster", "bear", "panda", "chick"],
            "material": ["soft", "matte", "jelly", "glass", "clay", "velvet",
                         "fluffy", "knit", "felt"],
            "color": ["lilac", "milk", "peach", "butter", "matcha", "mint", "sky",
                      "bubblegum", "tangerine", "cocoa", "ink"],
            "eyes": ["capsule", "dot"],
            "cheeks": ["true", "false"],
        },
        "series": {
            "blob": {"shapes": ["mochi", "bean", "pebble", "squircle", "pill", "drop", "kitty", "cloud"],
                     "materials": ["soft", "matte", "jelly", "glass", "clay", "velvet"]},
            "animal": {"shapes": ["bunny", "cat", "dog", "frog", "hamster", "bear", "panda", "chick"],
                       "materials": ["fluffy", "knit", "felt"]},
        },
        "free_color": "color",  # accepte aussi un #rrggbb
    },
    "3d": {
        "label": "3D en code",
        "credit": "Wobnimo, par Pourya Akhbari (licence MIT)",
        "source": "https://github.com/Pouryaak/wobnimo",
        "tag": "wobnimo-mascot",
        "script": "wobnimo/dist/wobnimo.js",
        "license": "wobnimo/LICENSE",
        "states": ["idle", "listening", "thinking", "speaking", "working", "error",
                   "celebrating", "surprised", "sleeping", "sad"],
        "options": {
            "character": ["volt", "pip", "mochi", "boo", "inky", "miso", "tad", "pebble",
                          "rex", "microduck", "drift", "cacti", "latte", "bumble", "swirl",
                          "ember", "cap", "berry", "bao", "hop"],
        },
        "free_color": None,
    },
}


class InvalidEngineError(ValueError):
    """Moteur ou reglage refuse (l'API repond 400 avec ce message)."""


def get_engine(engine: str) -> dict:
    if engine not in ENGINES:
        raise InvalidEngineError(
            f"Style inconnu : {engine!r} (attendus : {', '.join(ENGINES)})."
        )
    return ENGINES[engine]


def validate_config(engine: str, config: dict) -> dict:
    """Garde les reglages connus, valeurs par defaut = premiere option.

    En 3D, {"spec": id} remplace le personnage par une fiche creee depuis une image.
    """
    if engine == "3d" and "spec" in config:
        if set(config) != {"spec"}:
            raise InvalidEngineError("Un personnage cree depuis une image ne prend pas d'autre reglage.")
        try:
            image3d.done_spec(str(config["spec"]))
        except image3d.SpecNotFoundError as exc:
            raise InvalidEngineError(str(exc)) from exc
        return {"spec": str(config["spec"])}
    spec = get_engine(engine)
    clean: dict[str, str] = {}
    shape = str(config.get("shape", spec["options"].get("shape", [""])[0])).strip()
    defaults = {"material": "fluffy"} if engine == "blob" and shape in blob.ANIMALS else {}
    for key, allowed in spec["options"].items():
        value = str(config.get(key, defaults.get(key, allowed[0]))).strip()
        if key == spec["free_color"] and HEX_RE.match(value):
            clean[key] = value.lower()
        elif value in allowed:
            clean[key] = value
        else:
            raise InvalidEngineError(
                f"Valeur {value!r} refusee pour {key!r} (attendues : {', '.join(allowed)})."
            )
    if engine == "blob":
        animal = clean["shape"] in blob.ANIMALS
        allowed_materials = blob.FABRICS if animal else blob.MATERIALS
        if clean["material"] not in allowed_materials:
            series = "animal" if animal else "blob"
            raise InvalidEngineError(
                f"Matiere {clean['material']!r} incompatible avec la serie {series!r} "
                f"(attendues : {', '.join(sorted(allowed_materials))})."
            )
    unknown = set(config) - set(spec["options"])
    if unknown:
        raise InvalidEngineError(f"Reglage inconnu : {', '.join(sorted(unknown))}.")
    return clean


def build_manifest(engine: str, config: dict, script_src: str, name: str) -> dict:
    """Manifest v2 d'une mascotte en code. script_src : chemin du moteur."""
    spec = get_engine(engine)
    clean = validate_config(engine, config)
    manifest = {
        "version": 2,
        "name": name,
        "engine": engine,
        "engine_src": script_src,
        "engine_config": clean,
        "default_state": "idle",
        "alpha": "none",
        "states": {state: {"loop": True} for state in spec["states"]},
        "credit": spec["credit"],
    }
    if "spec" in clean:
        # Fiche sur mesure : le widget la passe a <wobnimo-mascot> (el.spec).
        manifest["engine_config"] = {}
        manifest["engine_spec"] = image3d.done_spec(clean["spec"])
    if engine == "blob" and clean.get("shape") in blob.ANIMALS:
        manifest["engine_three_src"] = _three_src(script_src)
    return manifest


def build_blob_manifest(blob_spec: dict, script_src: str) -> dict:
    """Manifest Blob Atelier v1 ou v2, avec declarations moteur ordonnees."""
    compiled = blob.compile_spec(blob_spec)
    manifest = {
        "version": 2,
        "name": compiled["name"],
        "engine": "blob",
        "engine_src": script_src,
        "engine_config": compiled["config"],
        "default_state": "idle",
        "alpha": "none",
        "states": {
            state: {"loop": True}
            for state in [*ENGINES["blob"]["states"], *compiled["states"]]
        },
        "credit": ENGINES["blob"]["credit"],
    }
    if compiled["points"]:
        manifest["engine_shape"] = {"name": compiled["shape"], "points": compiled["points"]}
    if compiled["states"]:
        manifest["engine_states"] = compiled["states"]
    if compiled["accessories"]:
        manifest["engine_accessories"] = compiled["accessories"]
    if compiled["series"] == "animal":
        manifest["engine_three_src"] = _three_src(script_src)
    return manifest


def _three_src(script_src: str) -> str:
    prefix = script_src.rsplit("/", 1)[0]
    return f"{prefix}/vendor/three.module.min.js"


def public_catalog() -> dict:
    """Ce que le studio affiche : styles, reglages, etats, credits."""
    return {
        name: {
            key: spec[key]
            for key in ("label", "credit", "source", "states", "options", "free_color", "series")
            if key in spec
        }
        for name, spec in ENGINES.items()
    }


def script_path(engine: str):  # type: ignore[no-untyped-def]
    return settings.engines_dir() / get_engine(engine)["script"]


def license_path(engine: str):  # type: ignore[no-untyped-def]
    return settings.engines_dir() / get_engine(engine)["license"]

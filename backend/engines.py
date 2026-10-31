"""Mascottes en code : moteurs open source tiers, embarques dans engines/.

Une mascotte en code ne passe ni par fal.ai ni par le pipeline : elle tient
dans un manifest (moteur + reglages) que le widget <mascot-avatar> lit comme
un manifest video. Gratuit, instantane, et la mascotte suit le curseur d'elle-meme.

  blob : Blob Atelier (Victoria Wu, MIT), serie "blobs" seulement : ses animaux
         3D chargent three.js depuis un CDN externe.
  3d   : Wobnimo (Pourya Akhbari, MIT), 20 personnages, 10 humeurs.
"""
from __future__ import annotations

import re

from backend import settings

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
            "shape": ["mochi", "bean", "pebble", "squircle", "pill", "drop", "kitty", "cloud"],
            "material": ["soft", "matte", "jelly", "glass", "clay", "velvet"],
            "color": ["lilac", "milk", "peach", "butter", "matcha", "mint", "sky",
                      "bubblegum", "tangerine", "cocoa", "ink"],
            "eyes": ["capsule", "dot"],
            "cheeks": ["true", "false"],
        },
        "free_color": "color",  # accepte aussi un #rrggbb
    },
    "3d": {
        "label": "3D en code",
        "credit": "Wobnimo, par Pourya Akhbari (licence MIT)",
        "source": "https://github.com/Pouryaak/wobnimo",
        "tag": "wobnimo-mascot",
        "script": "wobnimo/wobnimo.js",
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
    """Garde les reglages connus, valeurs par defaut = premiere option."""
    spec = get_engine(engine)
    clean: dict[str, str] = {}
    for key, allowed in spec["options"].items():
        value = str(config.get(key, allowed[0])).strip()
        if key == spec["free_color"] and HEX_RE.match(value):
            clean[key] = value.lower()
        elif value in allowed:
            clean[key] = value
        else:
            raise InvalidEngineError(
                f"Valeur {value!r} refusee pour {key!r} (attendues : {', '.join(allowed)})."
            )
    unknown = set(config) - set(spec["options"])
    if unknown:
        raise InvalidEngineError(f"Reglage inconnu : {', '.join(sorted(unknown))}.")
    return clean


def build_manifest(engine: str, config: dict, script_src: str, name: str) -> dict:
    """Manifest v2 d'une mascotte en code. script_src : chemin du moteur."""
    spec = get_engine(engine)
    return {
        "version": 2,
        "name": name,
        "engine": engine,
        "engine_src": script_src,
        "engine_config": validate_config(engine, config),
        "default_state": "idle",
        "alpha": "none",
        "states": {state: {"loop": True} for state in spec["states"]},
        "credit": spec["credit"],
    }


def public_catalog() -> dict:
    """Ce que le studio affiche : styles, reglages, etats, credits."""
    return {
        name: {key: spec[key] for key in ("label", "credit", "source", "states", "options", "free_color")}
        for name, spec in ENGINES.items()
    }


def script_path(engine: str):  # type: ignore[no-untyped-def]
    return settings.engines_dir() / get_engine(engine)["script"]


def license_path(engine: str):  # type: ignore[no-untyped-def]
    return settings.engines_dir() / get_engine(engine)["license"]

"""Etats d'animation : presets par usage et validation des etats libres.

Un etat = {"name", "prompt", "loop"} :
  name    identifiant utilise par le widget (play("thinking")), [a-z0-9-]
  prompt  mouvement decrit en texte libre (anglais conseille pour Kling)
  loop    True : le clip boucle tant que l'etat est actif
          False : le clip joue une fois puis revient a l'etat precedent
"""
from __future__ import annotations

import re

NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
MAX_STATES = 12
MAX_PROMPT_CHARS = 300

# Kling suit le mouvement du corps mais garde le visage si on ne le nomme pas :
# chaque etat expressif decrit d'abord le changement des yeux et du visage.
_IDLE = {"name": "idle", "prompt": "breathing gently, subtle idle sway, blinking", "loop": True}
_THINKING = {
    "name": "thinking",
    "prompt": "puzzled, curious expression: the eyes look up and to the side, pondering, "
              "small head tilt",
    "loop": True,
}
_TALKING = {
    "name": "talking",
    "prompt": "lively happy expression, talking cheerfully: mouth or face lights move as if "
              "speaking, small nods",
    "loop": True,
}
_ERROR = {
    "name": "error",
    "prompt": "the expression turns sad and worried, the eyes droop downward, then shaking "
              "head no with an apologetic shrug",
    "loop": False,
}
_CLICKED = {
    "name": "clicked",
    "prompt": "eyes light up with a big happy smile, happy little hop, waving hello",
    "loop": False,
}
_SLEEPING = {
    "name": "sleeping",
    "prompt": "eyes closed, slow deep breathing, sleepy head nod",
    "loop": True,
}

PRESETS: dict[str, dict] = {
    "agent": {"label": "Agent IA", "states": [_IDLE, _THINKING, _TALKING, _ERROR]},
    "site": {"label": "Site web", "states": [_IDLE, _CLICKED, _SLEEPING]},
    "complet": {
        "label": "Complet (6 états)",
        "states": [_IDLE, _TALKING, _THINKING, _CLICKED, _ERROR, _SLEEPING],
    },
}

DEFAULT_PRESET = "agent"

# Suivi du curseur : un clip ou seule la tete regarde dans les 4 directions.
# Le widget ne le lit pas : il affiche l'image qui regarde vers le curseur.
LOOK_STATE = "look"
LOOK_PROMPT = (
    "only the head moves, the body stays still: the head turns to look to the left, "
    "back to the center, to the right, back to the center, up, back to the center, "
    "down, back to the center"
)


class InvalidStatesError(ValueError):
    """Liste d'etats refusee (l'API repond 400 avec ce message)."""


def preset_states(usage: str) -> list[dict]:
    if usage not in PRESETS:
        raise InvalidStatesError(
            f"Usage inconnu : {usage!r} (attendus : {', '.join(PRESETS)})."
        )
    return [dict(s) for s in PRESETS[usage]["states"]]


def clean_prompt(name: str, prompt: str) -> str:
    """Normalise la description d'un etat. Leve InvalidStatesError."""
    prompt = " ".join(str(prompt).split())
    if not prompt:
        raise InvalidStatesError(f"Decris le mouvement de l'etat {name!r}.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise InvalidStatesError(
            f"Description trop longue pour {name!r} : {MAX_PROMPT_CHARS} caracteres max."
        )
    return prompt


def validate_states(states: list[dict]) -> list[dict]:
    """Normalise et valide une liste d'etats. Leve InvalidStatesError."""
    if not states:
        raise InvalidStatesError("Choisis au moins un etat a generer.")
    if len(states) > MAX_STATES:
        raise InvalidStatesError(
            f"Trop d'etats : {len(states)} demandes, {MAX_STATES} au maximum."
        )
    clean: list[dict] = []
    seen: set[str] = set()
    for raw in states:
        name = str(raw.get("name", "")).strip().lower()
        if not NAME_RE.match(name):
            raise InvalidStatesError(
                f"Nom d'etat invalide : {name!r}. Utilise des minuscules, chiffres "
                "et tirets (32 caracteres max), en commencant par une lettre."
            )
        if name == LOOK_STATE:
            raise InvalidStatesError(
                f"Le nom {LOOK_STATE!r} est reserve au suivi du curseur : choisis-en un autre."
            )
        if name in seen:
            raise InvalidStatesError(f"L'etat {name!r} apparait deux fois.")
        prompt = clean_prompt(name, raw.get("prompt", ""))
        seen.add(name)
        clean.append({"name": name, "prompt": prompt, "loop": bool(raw.get("loop", True))})
    if not any(s["loop"] for s in clean):
        raise InvalidStatesError(
            "Il faut au moins un etat en boucle : c'est lui que la mascotte joue au repos."
        )
    return clean


def default_state(states: list[dict]) -> str:
    """idle s'il existe, sinon le premier etat en boucle."""
    names = [s["name"] for s in states]
    if "idle" in names:
        return "idle"
    return next(s["name"] for s in states if s["loop"])

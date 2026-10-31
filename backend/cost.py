"""Compteur de depenses mensuel persistant (data/cost.json).

Le compteur se reinitialise automatiquement au changement de mois.
Les ecritures sont atomiques (fichier temporaire + rename).
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

from backend import settings

_lock = threading.Lock()


def _path():  # type: ignore[no-untyped-def]
    return settings.data_dir() / "cost.json"


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _write(data: dict) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read() -> dict:
    month = _current_month()
    path = _path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        if isinstance(data, dict) and data.get("month") == month:
            return {
                "month": month,
                "spent_usd": float(data.get("spent_usd", 0.0)),
                "mascots_completed": int(data.get("mascots_completed", 0)),
            }
    fresh = {"month": month, "spent_usd": 0.0, "mascots_completed": 0}
    _write(fresh)
    return fresh


def get_status() -> dict:
    """Retourne {month, spent_usd, cap_usd, mascots_completed}."""
    with _lock:
        data = _read()
        return {
            "month": data["month"],
            "spent_usd": round(data["spent_usd"], 4),
            "cap_usd": settings.monthly_cap_usd(),
            "mascots_completed": data["mascots_completed"],
        }


def can_afford(estimate_usd: float) -> bool:
    """Vrai si l'estimation tient dans le plafond mensuel restant."""
    status = get_status()
    return status["spent_usd"] + estimate_usd <= status["cap_usd"] + 1e-9


def add_spend(amount_usd: float, mascots_completed: int = 0) -> dict:
    """Ajoute une depense reelle au compteur du mois en cours."""
    with _lock:
        data = _read()
        data["spent_usd"] = round(data["spent_usd"] + amount_usd, 4)
        data["mascots_completed"] += mascots_completed
        _write(data)
        return {
            "month": data["month"],
            "spent_usd": data["spent_usd"],
            "cap_usd": settings.monthly_cap_usd(),
            "mascots_completed": data["mascots_completed"],
        }

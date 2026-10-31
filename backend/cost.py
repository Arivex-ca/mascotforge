"""Compteur de depenses mensuel persistant (data/cost.json).

Le compteur se reinitialise automatiquement au changement de mois.
Les ecritures sont atomiques (fichier temporaire + rename).

Un job reserve son estimation avant de partir (reserve), puis rend la
reservation et inscrit la depense reelle a la fin (release + add_spend).
Deux jobs lances en meme temps ne peuvent donc pas depasser le plafond
ensemble.
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
                "reserved_usd": float(data.get("reserved_usd", 0.0)),
                "mascots_completed": int(data.get("mascots_completed", 0)),
            }
    fresh = {"month": month, "spent_usd": 0.0, "reserved_usd": 0.0, "mascots_completed": 0}
    _write(fresh)
    return fresh


def _status(data: dict) -> dict:
    return {
        "month": data["month"],
        "spent_usd": round(data["spent_usd"], 4),
        "reserved_usd": round(data["reserved_usd"], 4),
        "cap_usd": settings.monthly_cap_usd(),
        "mascots_completed": data["mascots_completed"],
    }


def get_status() -> dict:
    """Retourne {month, spent_usd, reserved_usd, cap_usd, mascots_completed}."""
    with _lock:
        return _status(_read())


def reserve(amount_usd: float) -> bool:
    """Reserve un montant s'il tient dans le plafond (depense + reservations)."""
    with _lock:
        data = _read()
        if data["spent_usd"] + data["reserved_usd"] + amount_usd > settings.monthly_cap_usd() + 1e-9:
            return False
        data["reserved_usd"] = round(data["reserved_usd"] + amount_usd, 4)
        _write(data)
        return True


def release(amount_usd: float) -> None:
    """Rend une reservation (jamais en dessous de zero)."""
    with _lock:
        data = _read()
        data["reserved_usd"] = round(max(0.0, data["reserved_usd"] - amount_usd), 4)
        _write(data)


def reset_reservations() -> None:
    """Au demarrage : aucun job ne tourne, les reservations restantes sont orphelines."""
    with _lock:
        data = _read()
        data["reserved_usd"] = 0.0
        _write(data)


def add_spend(amount_usd: float, mascots_completed: int = 0) -> dict:
    """Ajoute une depense reelle au compteur du mois en cours."""
    with _lock:
        data = _read()
        data["spent_usd"] = round(data["spent_usd"] + amount_usd, 4)
        data["mascots_completed"] += mascots_completed
        _write(data)
        return _status(data)

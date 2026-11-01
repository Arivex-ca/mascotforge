"""CLI pour creer et exporter des mascottes sans le studio web."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from mascotforge.client import MascotForgeClient, MascotForgeError

IMAGE3D_MIN_USD = 0.15
IMAGE3D_MAX_USD = 0.60


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mascotforge",
        description="Pilote MascotForge par son API HTTP.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="renvoie un objet JSON au lieu d'un texte humain (accepte aussi apres la commande)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("styles", help="liste les styles, reglages, etats et prix")

    code = commands.add_parser("code", help="exporte une mascotte gratuite en code")
    code.add_argument("--engine", choices=("blob", "3d"), required=True)
    code.add_argument("--set", action="append", default=[], metavar="CLE=VALEUR")
    code.add_argument("--out", required=True, type=Path, metavar="DOSSIER")

    image3d = commands.add_parser("image3d", help="cree un personnage Wobnimo depuis une image")
    image3d.add_argument("image", type=Path, metavar="IMAGE")
    image3d.add_argument("--out", required=True, type=Path, metavar="DOSSIER")
    image3d.add_argument("--yes", action="store_true", help="confirme la depense estimee")

    video = commands.add_parser("video", help="cree une mascotte video payante")
    source = video.add_mutually_exclusive_group(required=True)
    source.add_argument("--image", type=Path, metavar="IMAGE")
    source.add_argument("--prompt", metavar="TEXTE")
    video.add_argument("--usage", choices=("agent", "site", "complet"), default="agent")
    video.add_argument("--out", required=True, type=Path, metavar="DOSSIER")
    video.add_argument("--yes", action="store_true", help="confirme la depense estimee")

    status = commands.add_parser("status", help="affiche le statut d'une creation")
    status.add_argument("id", metavar="ID")

    export = commands.add_parser("export", help="exporte une creation terminee")
    export.add_argument("id", metavar="ID")
    export.add_argument("--out", required=True, type=Path, metavar="DOSSIER")

    commands.add_parser("cost", help="affiche les couts et le plafond du serveur")
    return parser


def _settings(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise MascotForgeError(f"Reglage invalide {value!r} : utilisez cle=valeur.")
        key, setting = value.split("=", 1)
        key = key.strip()
        setting = setting.strip()
        if not key or not setting:
            raise MascotForgeError(f"Reglage invalide {value!r} : la cle et la valeur sont requises.")
        result[key] = setting
    return result


def _money(value: float) -> str:
    return f"{value:.2f}".replace(".", ",") + " $ US"


def _emit(data: dict, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(data, ensure_ascii=False, sort_keys=True))
        return
    kind = data.get("kind")
    if kind == "styles":
        engines = data["engines"]
        presets = data["presets"]
        print("Styles en code gratuits :")
        for name, engine in engines.items():
            print(f"  {name}: {engine['label']}")
            print(f"    Etats: {', '.join(engine['states'])}")
            for key, values in engine["options"].items():
                print(f"    {key}: {', '.join(values)}")
            print(f"    Credit: {engine['credit']}")
        print("Presets video payants :")
        price = float(presets["cost_per_state_usd"])
        for name, preset in presets["presets"].items():
            states = [state["name"] for state in preset["states"]]
            print(
                f"  {name}: {preset['label']}, {len(states)} etats, "
                f"environ {_money(len(states) * price)}"
            )
            print(f"    Etats: {', '.join(states)}")
        print(f"Personnage 3D depuis une image: environ {_money(IMAGE3D_MIN_USD)} a {_money(IMAGE3D_MAX_USD)}")
    elif kind == "confirmation":
        print(data["message"])
    elif kind == "export":
        print(f"Export extrait dans {data['out']}")
        print(f"Fichiers: {len(data.get('files', []))}")
    elif kind == "status":
        print(f"Type: {data.get('type', 'inconnu')}")
        print(f"ID: {data.get('job_id') or data.get('spec_id')}")
        print(f"Statut: {data.get('status', 'inconnu')}")
        if "actual_cost_usd" in data:
            print(f"Cout reel: {_money(float(data['actual_cost_usd']))}")
        elif "cost_usd" in data:
            print(f"Cout reel: {_money(float(data['cost_usd']))}")
    elif kind == "cost":
        print(f"Mois: {data['month']}")
        print(f"Depense: {_money(float(data['spent_usd']))}")
        print(f"Reserve: {_money(float(data['reserved_usd']))}")
        print(f"Plafond: {_money(float(data['cap_usd']))}")
        print(f"Mascottes terminees: {data['mascots_completed']}")


def _confirmation(kind: str, message: str, estimate: dict) -> dict:
    return {
        "ok": False,
        "kind": "confirmation",
        "creation": kind,
        "confirmation_required": True,
        "estimate": estimate,
        "message": message,
    }


def _video_estimate(client: MascotForgeClient, usage: str) -> dict:
    presets = client.styles()["presets"]
    preset = presets["presets"].get(usage)
    if not isinstance(preset, dict):
        raise MascotForgeError(f"Preset video inconnu : {usage}")
    states = preset.get("states", [])
    count = len(states)
    per_state = float(presets["cost_per_state_usd"])
    return {
        "usage": usage,
        "states": count,
        "cost_per_state_usd": per_state,
        "total_usd": round(count * per_state, 4),
    }


def _progress(json_mode: bool):  # type: ignore[no-untyped-def]
    if json_mode:
        return None

    def show(current: dict) -> None:
        creation_id = current.get("job_id") or current.get("spec_id")
        print(f"Creation {creation_id}: {current.get('status', 'inconnu')}")

    return show


def main(
    argv: Sequence[str] | None = None,
    client: MascotForgeClient | None = None,
) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)
    json_mode = "--json" in raw_args
    normalized = [arg for arg in raw_args if arg != "--json"]
    args = build_parser().parse_args(normalized)
    own_client = client is None
    api = client or MascotForgeClient()
    try:
        if args.command == "styles":
            result = {"ok": True, "kind": "styles", **api.styles()}
        elif args.command == "code":
            result = {
                "ok": True,
                "kind": "export",
                "creation": "code",
                **api.export_code(args.engine, _settings(args.set), args.out),
            }
        elif args.command == "image3d":
            if not args.yes:
                result = _confirmation(
                    "image3d",
                    "Creation non lancee. Prix estime: environ 0,15 a 0,60 $ US. Relancez avec --yes pour confirmer.",
                    {"min_usd": IMAGE3D_MIN_USD, "max_usd": IMAGE3D_MAX_USD},
                )
                _emit(result, json_mode)
                return 2
            started = api.start_image3d(args.image)
            api.wait_image3d(started["spec_id"], on_update=_progress(json_mode))
            result = {
                "ok": True,
                "kind": "export",
                "creation": "image3d",
                "id": started["spec_id"],
                **api.export_creation(started["spec_id"], args.out),
            }
        elif args.command == "video":
            estimate = _video_estimate(api, args.usage)
            if not args.yes:
                result = _confirmation(
                    "video",
                    f"Creation non lancee. Prix estime: {_money(estimate['total_usd'])} "
                    f"pour {estimate['states']} etats. Relancez avec --yes pour confirmer.",
                    estimate,
                )
                _emit(result, json_mode)
                return 2
            started = api.start_video(args.usage, image=args.image, prompt=args.prompt)
            api.wait_video(started["job_id"], on_update=_progress(json_mode))
            result = {
                "ok": True,
                "kind": "export",
                "creation": "video",
                "id": started["job_id"],
                **api.export_creation(started["job_id"], args.out),
            }
        elif args.command == "status":
            result = {"ok": True, "kind": "status", **api.status(args.id)}
        elif args.command == "export":
            result = {
                "ok": True,
                "kind": "export",
                "creation": "existante",
                "id": args.id,
                **api.export_creation(args.id, args.out),
            }
        else:
            result = {"ok": True, "kind": "cost", **api.cost()}
        _emit(result, json_mode)
        return 0
    except MascotForgeError as exc:
        if json_mode:
            print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        else:
            print(f"Erreur: {exc}", file=sys.stderr)
        return 1
    finally:
        if own_client:
            api.close()

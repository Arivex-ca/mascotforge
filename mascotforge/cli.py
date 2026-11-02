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
SKILL_SOURCE = Path(__file__).resolve().parents[1] / "skills" / "mascotforge" / "SKILL.md"
SKILL_TARGETS = (
    Path(".claude") / "skills" / "mascotforge" / "SKILL.md",
    Path(".agents") / "skills" / "mascotforge" / "SKILL.md",
)


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

    blob = commands.add_parser("blob", help="dessine et exporte un blob sur mesure")
    blob_commands = blob.add_subparsers(dest="blob_command", required=True)
    blob_guide = blob_commands.add_parser("guide", help="affiche le guide de fiche blob")
    blob_guide.add_argument("--out", type=Path, metavar="FICHIER")
    blob_check = blob_commands.add_parser("check", help="verifie une fiche JSON de blob")
    blob_check.add_argument("file", type=Path, metavar="FICHIER.json")
    blob_preview = blob_commands.add_parser("preview", help="rend les huit etats en PNG")
    blob_preview.add_argument("file", type=Path, metavar="FICHIER.json")
    blob_preview.add_argument("--out", required=True, type=Path, metavar="PLANCHE.png")
    blob_export = blob_commands.add_parser("export", help="exporte un blob sur mesure")
    blob_export.add_argument("file", type=Path, metavar="FICHIER.json")
    blob_export.add_argument("--out", required=True, type=Path, metavar="DOSSIER")

    spec = commands.add_parser("spec", help="ecrit et exporte gratuitement une fiche Wobnimo")
    spec_commands = spec.add_subparsers(dest="spec_command", required=True)
    spec_guide = spec_commands.add_parser("guide", help="affiche le guide complet pour un agent")
    spec_guide.add_argument("--out", type=Path, metavar="FICHIER")
    spec_check = spec_commands.add_parser("check", help="verifie une fiche JSON")
    spec_check.add_argument("file", type=Path, metavar="FICHIER.json")
    spec_preview = spec_commands.add_parser("preview", help="rend la planche PNG d'une fiche")
    spec_preview.add_argument("file", type=Path, metavar="FICHIER.json")
    spec_preview.add_argument("--out", required=True, type=Path, metavar="PLANCHE.png")
    spec_save = spec_commands.add_parser("save", help="enregistre une fiche verifiee")
    spec_save.add_argument("file", type=Path, metavar="FICHIER.json")
    spec_export = spec_commands.add_parser("export", help="enregistre et exporte une fiche")
    spec_export.add_argument("file", type=Path, metavar="FICHIER.json")
    spec_export.add_argument("--out", required=True, type=Path, metavar="DOSSIER")

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

    skill = commands.add_parser("skill", help="installe le skill MascotForge pour les agents")
    skill.add_argument("--dir", type=Path, default=Path("."), metavar="DOSSIER")
    skill.add_argument(
        "--force",
        action="store_true",
        help="remplace un skill local modifie",
    )
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


def _load_spec(path: Path) -> dict:
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MascotForgeError(f"Fiche introuvable : {path}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MascotForgeError(f"La fiche {path} n'est pas un fichier JSON lisible.") from exc
    if not isinstance(spec, dict):
        raise MascotForgeError("La fiche doit etre un objet JSON.")
    return spec


def _install_skill(target: Path, force: bool) -> dict:
    root = target.resolve()
    if not root.is_dir():
        raise MascotForgeError(f"Dossier cible introuvable : {root}")
    try:
        content = SKILL_SOURCE.read_bytes()
    except OSError as exc:
        raise MascotForgeError("Le skill MascotForge source est introuvable.") from exc

    destinations = [root / relative for relative in SKILL_TARGETS]
    conflicts: list[Path] = []
    for destination in destinations:
        if not destination.exists():
            continue
        try:
            current = destination.read_bytes()
        except OSError as exc:
            raise MascotForgeError(f"Impossible de lire le skill local : {destination}") from exc
        if current != content:
            conflicts.append(destination)

    if conflicts and not force:
        paths = ", ".join(str(path) for path in conflicts)
        raise MascotForgeError(
            f"Skill local modifié, aucun fichier remplacé : {paths}. "
            "Relancez avec --force pour confirmer."
        )

    installed = 0
    unchanged = 0
    for destination in destinations:
        if destination.exists() and destination.read_bytes() == content:
            unchanged += 1
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        except OSError as exc:
            raise MascotForgeError(f"Impossible d'installer le skill dans {destination}") from exc
        installed += 1

    return {
        "root": str(root),
        "destinations": [str(path) for path in destinations],
        "installed": installed,
        "unchanged": unchanged,
    }


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
    elif kind == "spec-guide":
        if data.get("out"):
            print(f"Guide enregistre dans {data['out']}")
        else:
            print(data["guide"])
    elif kind == "spec-check":
        print("Fiche valide." if data["ok"] else "Fiche invalide.")
        for issue in data.get("issues", []):
            print(f"  {issue.get('level', 'issue')} {issue.get('where', 'spec')}: {issue.get('message', '')}")
            if issue.get("fix"):
                print(f"    Correction: {issue['fix']}")
    elif kind == "spec-preview":
        print(f"Planche enregistree dans {data['out']}")
    elif kind == "spec-save":
        print(f"Fiche enregistree : {data['spec_id']} ({data['name']})")
        print(f"Avertissements: {len(data.get('warnings', []))}")
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
    elif kind == "skill":
        if data["installed"]:
            print(f"Skill installé dans {data['installed']} emplacement(s) :")
        else:
            print("Skill déjà à jour :")
        for destination in data["destinations"]:
            print(f"  {destination}")


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
        if args.command == "skill":
            result = {
                "ok": True,
                "kind": "skill",
                **_install_skill(args.dir, args.force),
            }
        elif args.command == "styles":
            result = {"ok": True, "kind": "styles", **api.styles()}
        elif args.command == "code":
            result = {
                "ok": True,
                "kind": "export",
                "creation": "code",
                **api.export_code(args.engine, _settings(args.set), args.out),
            }
        elif args.command == "blob":
            if args.blob_command == "guide":
                guide = api.blob_guide()
                out = None
                if args.out is not None:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(guide, encoding="utf-8")
                    out = str(args.out.resolve())
                result = {"ok": True, "kind": "spec-guide", "guide": guide, "out": out}
            elif args.blob_command == "check":
                checked = api.blob_check(_load_spec(args.file))
                result = {"kind": "spec-check", **checked}
                _emit(result, json_mode)
                return 0 if checked.get("ok") else 2
            elif args.blob_command == "preview":
                content = api.blob_preview(_load_spec(args.file))
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_bytes(content)
                result = {"ok": True, "kind": "spec-preview", "out": str(args.out.resolve()), "bytes": len(content)}
            else:
                result = {"ok": True, "kind": "export", "creation": "blob", **api.blob_export(_load_spec(args.file), args.out)}
        elif args.command == "spec":
            if args.spec_command == "guide":
                guide = api.spec_guide()
                out = None
                if args.out is not None:
                    args.out.parent.mkdir(parents=True, exist_ok=True)
                    args.out.write_text(guide, encoding="utf-8")
                    out = str(args.out.resolve())
                result = {"ok": True, "kind": "spec-guide", "guide": guide, "out": out}
            elif args.spec_command == "check":
                checked = api.spec_check(_load_spec(args.file))
                result = {"kind": "spec-check", **checked}
                _emit(result, json_mode)
                return 0 if checked.get("ok") else 2
            elif args.spec_command == "preview":
                content = api.spec_preview(_load_spec(args.file))
                args.out.parent.mkdir(parents=True, exist_ok=True)
                args.out.write_bytes(content)
                result = {
                    "ok": True,
                    "kind": "spec-preview",
                    "out": str(args.out.resolve()),
                    "bytes": len(content),
                }
            elif args.spec_command == "save":
                result = {
                    "ok": True,
                    "kind": "spec-save",
                    **api.spec_save(_load_spec(args.file)),
                }
            else:
                result = {
                    "ok": True,
                    "kind": "export",
                    "creation": "spec",
                    **api.spec_export(_load_spec(args.file), args.out),
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

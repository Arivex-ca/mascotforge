"""Serveur MCP stdio de MascotForge."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

from mascotforge.cli import IMAGE3D_MAX_USD, IMAGE3D_MIN_USD
from mascotforge.client import MascotForgeClient

mcp = MCPServer(
    "MascotForge",
    instructions=(
        "Cree et exporte des mascottes par le serveur MascotForge. "
        "Pour une fiche Wobnimo gratuite, suivez toute la boucle guide, image de reference, "
        "check, preview, correction, puis save ou export. "
        "Demandez toujours l'accord explicite de l'utilisateur avant un outil payant."
    ),
)

SPEC_LOOP = (
    "Boucle gratuite obligatoire : lire le guide, regarder l'image de reference, ecrire la fiche, "
    "lancer le check, regarder la preview, la comparer a l'image, corriger, puis save ou export. "
)

BLOB_LOOP = (
    "Boucle gratuite : lire le guide blob, ecrire la fiche JSON, lancer le check, "
    "regarder les huit etats dans la preview, corriger, puis exporter. "
)


def _video_estimate(
    client: MascotForgeClient, usage: str, states: list[dict] | None = None
) -> dict[str, Any]:
    presets = client.styles()["presets"]
    if states is not None:
        count = len(states)
        usage = "sur-mesure"
    else:
        preset = presets["presets"].get(usage)
        if not isinstance(preset, dict):
            raise ValueError(f"Preset video inconnu : {usage}")
        count = len(preset.get("states", []))
    per_state = float(presets["cost_per_state_usd"])
    return {
        "usage": usage,
        "states": count,
        "cost_per_state_usd": per_state,
        "total_usd": round(count * per_state, 4),
    }


@mcp.tool(description="Liste les styles, reglages, etats et prix du serveur MascotForge.")
def mascotforge_styles() -> dict[str, Any]:
    with MascotForgeClient() as client:
        return client.styles()


@mcp.tool(description="Exporte une mascotte gratuite Blob Atelier ou Wobnimo dans un dossier local.")
def mascotforge_code(
    engine: str,
    out: str,
    config: dict[str, str] | None = None,
) -> dict[str, Any]:
    with MascotForgeClient() as client:
        return client.export_code(engine, config or {}, Path(out))


@mcp.tool(description=BLOB_LOOP + "Renvoie le guide et trois exemples complets.")
def mascotforge_blob_guide() -> dict[str, str]:
    with MascotForgeClient() as client:
        return {"guide": client.blob_guide()}


@mcp.tool(description=BLOB_LOOP + "Verifie le contour et chaque reglage sans rien conserver.")
def mascotforge_blob_check(spec: dict[str, Any]) -> dict[str, Any]:
    with MascotForgeClient() as client:
        return client.blob_check(spec)


@mcp.tool(description=BLOB_LOOP + "Rend la planche des huit etats comme contenu image MCP.")
def mascotforge_blob_preview(spec: dict[str, Any]) -> Image:
    with MascotForgeClient() as client:
        return Image(data=client.blob_preview(spec), format="png")


@mcp.tool(description=BLOB_LOOP + "Verifie et exporte le dossier autonome dans un dossier local.")
def mascotforge_blob_export(spec: dict[str, Any], out: str) -> dict[str, Any]:
    with MascotForgeClient() as client:
        return client.blob_export(spec, Path(out))


@mcp.tool(description=SPEC_LOOP + "Renvoie le guide Wobnimo complet et l'exemple Volt.")
def mascotforge_spec_guide() -> dict[str, str]:
    with MascotForgeClient() as client:
        return {"guide": client.spec_guide()}


@mcp.tool(description=SPEC_LOOP + "Verifie la geometrie de la fiche JSON sans la conserver.")
def mascotforge_spec_check(spec: dict[str, Any]) -> dict[str, Any]:
    with MascotForgeClient() as client:
        return client.spec_check(spec)


@mcp.tool(
    description=(
        SPEC_LOOP
        + "Rend la planche Wobnimo comme contenu image MCP. La vue de face est en haut a gauche."
    )
)
def mascotforge_spec_preview(spec: dict[str, Any]) -> Image:
    with MascotForgeClient() as client:
        return Image(data=client.spec_preview(spec), format="png")


@mcp.tool(description=SPEC_LOOP + "Verifie et conserve la fiche terminee a cout nul.")
def mascotforge_spec_save(spec: dict[str, Any]) -> dict[str, Any]:
    with MascotForgeClient() as client:
        return client.spec_save(spec)


@mcp.tool(description=SPEC_LOOP + "Verifie, conserve et exporte la fiche dans un dossier local.")
def mascotforge_spec_export(spec: dict[str, Any], out: str) -> dict[str, Any]:
    with MascotForgeClient() as client:
        return client.spec_export(spec, Path(out))


@mcp.tool(
    description=(
        "Creation payante d'un personnage 3D depuis une image. Obtenez l'accord explicite "
        "de l'utilisateur apres lui avoir annonce environ 0,15 a 0,60 $ US. "
        "Passez user_confirmed=true uniquement apres cet accord. L'outil demarre la creation "
        "et rend un spec_id sans attendre sa fin."
    )
)
def mascotforge_image3d_start(image: str, user_confirmed: bool = False) -> dict[str, Any]:
    if not user_confirmed:
        return {
            "started": False,
            "confirmation_required": True,
            "estimate": {"min_usd": IMAGE3D_MIN_USD, "max_usd": IMAGE3D_MAX_USD},
            "message": "Demandez l'accord de l'utilisateur avant de lancer cette creation payante.",
        }
    with MascotForgeClient() as client:
        return {"started": True, **client.start_image3d(Path(image))}


@mcp.tool(
    description=(
        "Creation video payante. Obtenez l'accord explicite de l'utilisateur apres lui avoir "
        "annonce le prix estime. Sans accord, laissez user_confirmed=false pour lire ce prix. "
        "L'outil demarre la creation et rend un job_id sans attendre sa fin. "
        "states (facultatif) remplace usage par des etats sur mesure : "
        "[{name, prompt, loop}], prompt en anglais, 300 caracteres max."
    )
)
def mascotforge_video_start(
    usage: str = "agent",
    image: str | None = None,
    prompt: str | None = None,
    states: list[dict[str, Any]] | None = None,
    user_confirmed: bool = False,
) -> dict[str, Any]:
    with MascotForgeClient() as client:
        estimate = _video_estimate(client, usage, states)
        if not user_confirmed:
            return {
                "started": False,
                "confirmation_required": True,
                "estimate": estimate,
                "message": "Demandez l'accord de l'utilisateur avant de lancer cette creation payante.",
            }
        started = client.start_video(
            usage=usage,
            image=Path(image) if image is not None else None,
            prompt=prompt,
            states=states,
        )
        return {"started": True, "estimate": estimate, **started}


@mcp.tool(description="Suit une creation video ou image3d sans bloquer jusqu'a sa fin.")
def mascotforge_status(creation_id: str) -> dict[str, Any]:
    with MascotForgeClient() as client:
        return client.status(creation_id)


@mcp.tool(description="Exporte une creation terminee et decompresse son zip dans un dossier local.")
def mascotforge_export(creation_id: str, out: str) -> dict[str, Any]:
    with MascotForgeClient() as client:
        return client.export_creation(creation_id, Path(out))


@mcp.tool(description="Affiche les depenses, reservations et le plafond du serveur MascotForge.")
def mascotforge_cost() -> dict[str, Any]:
    with MascotForgeClient() as client:
        return client.cost()


def run() -> None:
    """Lance le transport MCP stdio."""
    mcp.run(transport="stdio")

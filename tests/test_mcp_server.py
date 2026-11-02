"""Contrat MCP stdio. Saute seulement si la dependance n'a pas pu etre installee."""
from __future__ import annotations

import importlib.util
import base64
import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mcp") is None,
    reason="paquet mcp indisponible dans l'environnement",
)


@pytest.mark.asyncio
async def test_mcp_stdio_starts_and_lists_tools():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root = Path(__file__).resolve().parent.parent
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mascotforge", "mcp"],
        cwd=str(root),
        env={**os.environ, "PYTHONPATH": str(root)},
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listing = await session.list_tools()

    tools = {tool.name: tool for tool in listing.tools}
    assert {
        "mascotforge_styles",
        "mascotforge_code",
        "mascotforge_blob_guide",
        "mascotforge_blob_check",
        "mascotforge_blob_preview",
        "mascotforge_blob_export",
        "mascotforge_spec_guide",
        "mascotforge_spec_check",
        "mascotforge_spec_preview",
        "mascotforge_spec_save",
        "mascotforge_spec_export",
        "mascotforge_image3d_start",
        "mascotforge_video_start",
        "mascotforge_status",
        "mascotforge_export",
        "mascotforge_cost",
    } <= set(tools)
    assert "accord" in (tools["mascotforge_video_start"].description or "").lower()
    assert "accord" in (tools["mascotforge_image3d_start"].description or "").lower()
    preview_description = (tools["mascotforge_spec_preview"].description or "").lower()
    assert "guide" in preview_description and "preview" in preview_description
    assert "corriger" in preview_description and "image mcp" in preview_description


def test_mcp_spec_preview_returns_exact_image_content(monkeypatch):
    from mcp.server.mcpserver import Image

    from mascotforge.client import MascotForgeClient
    from mascotforge.mcp_server import mascotforge_spec_preview

    png = b"\x89PNG\r\n\x1a\nplanche"
    monkeypatch.setattr(MascotForgeClient, "spec_preview", lambda _self, _spec: png)

    result = mascotforge_spec_preview({"parts": []})

    assert isinstance(result, Image)
    content = result.to_image_content()
    assert content.type == "image" and content.mime_type == "image/png"
    assert base64.b64decode(content.data) == png


def test_mcp_blob_preview_returns_exact_image_content(monkeypatch):
    from mcp.server.mcpserver import Image

    from mascotforge.client import MascotForgeClient
    from mascotforge.mcp_server import mascotforge_blob_preview

    png = b"\x89PNG\r\n\x1a\nblob"
    monkeypatch.setattr(MascotForgeClient, "blob_preview", lambda _self, _spec: png)
    result = mascotforge_blob_preview({"contour": {}})
    assert isinstance(result, Image)
    assert base64.b64decode(result.to_image_content().data) == png


def test_mcp_blob_guide_check_and_export_call_the_client(monkeypatch, tmp_path):
    from mascotforge.client import MascotForgeClient
    from mascotforge.mcp_server import (
        mascotforge_blob_check,
        mascotforge_blob_export,
        mascotforge_blob_guide,
    )

    seen: list[tuple[str, object]] = []
    monkeypatch.setattr(MascotForgeClient, "blob_guide", lambda _self: "guide blob")
    monkeypatch.setattr(
        MascotForgeClient,
        "blob_check",
        lambda _self, spec: seen.append(("check", spec)) or {"ok": True, "issues": []},
    )
    monkeypatch.setattr(
        MascotForgeClient,
        "blob_export",
        lambda _self, spec, out: seen.append(("export", (spec, out))) or {"out": str(out)},
    )
    spec = {"version": 1, "contour": {}}
    out = tmp_path / "blob"

    assert mascotforge_blob_guide() == {"guide": "guide blob"}
    assert mascotforge_blob_check(spec)["ok"]
    assert mascotforge_blob_export(spec, str(out))["out"] == str(out)
    assert seen == [("check", spec), ("export", (spec, out))]

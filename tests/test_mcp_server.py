"""Contrat MCP stdio. Saute seulement si la dependance n'a pas pu etre installee."""
from __future__ import annotations

import importlib.util
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
        "mascotforge_image3d_start",
        "mascotforge_video_start",
        "mascotforge_status",
        "mascotforge_export",
        "mascotforge_cost",
    } <= set(tools)
    assert "accord" in (tools["mascotforge_video_start"].description or "").lower()
    assert "accord" in (tools["mascotforge_image3d_start"].description or "").lower()

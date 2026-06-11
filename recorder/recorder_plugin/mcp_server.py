"""MCP tool register. Exposes 8 tools (per spec §6.3) over the Model Context Protocol."""
from __future__ import annotations
import asyncio
import json
from pathlib import Path
from typing import Any

from recorder_plugin.core import Recorder


class _ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, dict] = {}

    def register(self, name: str, description: str, handler) -> None:
        self._tools[name] = {"description": description, "handler": handler}


_REGISTRY = _ToolRegistry()


def _register_defaults(reg: _ToolRegistry) -> None:
    from recorder_plugin.script import (
        _handle_navigate, _handle_click, _handle_type, _handle_wait,
        _handle_screenshot, _handle_login, _handle_video_start, _handle_video_stop,
    )
    reg.register("recorder_navigate", "Navigate to URL", _handle_navigate)
    reg.register("recorder_click", "Click a selector (with retry)", _handle_click)
    reg.register("recorder_type", "Type into a field", _handle_type)
    reg.register("recorder_wait_for", "Wait for a whitelisted predicate", _handle_wait)
    reg.register(
        "recorder_screenshot",
        "Take a screenshot with optional annotation/mask",
        _handle_screenshot,
    )
    reg.register("recorder_video_start", "Start video recording for a named segment", _handle_video_start)
    reg.register("recorder_video_stop", "Stop recording and slice the segment", _handle_video_stop)

    async def run_script_handler(args: dict) -> dict:
        from recorder_plugin.script import run_script
        return await run_script(Path(args["path"]))
    reg.register("recorder_run_script", "Execute a declarative JSON script", run_script_handler)


_register_defaults(_REGISTRY)


def list_tools() -> list[dict]:
    return [{"name": n, "description": info["description"]} for n, info in _REGISTRY._tools.items()]


async def call_tool(name: str, args: dict, rec: Recorder, output_dir: Path, env: dict | None = None) -> Any:
    if name not in _REGISTRY._tools:
        raise ValueError(f"unknown tool: {name}")
    handler = _REGISTRY._tools[name]["handler"]
    if name in ("recorder_screenshot",):
        return await handler(rec, args, output_dir)
    if name == "recorder_login":
        return await handler(rec, args, env or {})
    if name == "recorder_run_script":
        return await handler(args)
    # Navigate / click / type / wait / video_start / video_stop
    if name in ("recorder_video_start", "recorder_video_stop"):
        # These need an extra name_to_path dict and possibly output_dir
        name_to_path: dict = {}
        if name == "recorder_video_stop":
            return await handler(rec, args, name_to_path, output_dir)
        return await handler(rec, args, name_to_path)
    return await handler(rec, args)


def start_mcp_server() -> None:
    """Start the MCP server over stdio. Blocks until the client disconnects."""
    try:
        from mcp.server import Server
        from mcp.server.stdio import stdio_server
        from mcp.types import Tool, TextContent
    except ImportError as e:
        print(f"mcp SDK not available: {e}", file=__import__("sys").stderr)
        print("Install with: pip install mcp>=1.0", file=__import__("sys").stderr)
        raise SystemExit(1)

    app = Server("recorder")

    @app.list_tools()
    async def _list() -> list[Tool]:
        return [Tool(name=t["name"], description=t["description"], inputSchema={"type": "object"}) for t in list_tools()]

    @app.call_tool()
    async def _call(name: str, arguments: dict) -> list[TextContent]:
        from recorder_plugin.core import Recorder
        async with Recorder(viewport={"width": 1280, "height": 800}, headless=True, output_dir=Path(".")) as rec:
            result = await call_tool(name, arguments, rec, Path("."))
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    async def main():
        async with stdio_server() as (read_stream, write_stream):
            await app.run(read_stream, write_stream, app.create_initialization_options())

    asyncio.run(main())


if __name__ == "__main__":
    start_mcp_server()

"""
The connector seam: anything that turns an existing system into tools.

A connector yields (ToolSpec, handler) pairs, the exact shape ToolRegistry takes,
so the registry and the runtime stay unchanged. Python functions, an OpenAPI spec
and an MCP server all become tools the same way, and an Agent can mix them.

Connectors may hold resources (an HTTP client, an MCP subprocess), so tools() is
async and is where they connect, and aclose() is where they let go. The Agent
calls tools() at the start of each session and aclose() when it ends.
"""

from __future__ import annotations

from typing import Iterable, Protocol, runtime_checkable

from soro.runtime.registry import ToolHandler, ToolRegistry
from soro.tools import ToolSpec

ToolPair = tuple[ToolSpec, ToolHandler]


@runtime_checkable
class Connector(Protocol):
    async def tools(self) -> list[ToolPair]:
        """Connect if needed and return every tool this connector offers."""
        ...

    async def aclose(self) -> None:
        """Release whatever tools() opened. Safe to call when nothing was opened."""
        ...


def registry_from_pairs(pairs: Iterable[ToolPair]) -> ToolRegistry:
    """Register pairs in order. Two connectors offering the same name is an error, not a silent override."""
    registry = ToolRegistry()
    for spec, handler in pairs:
        registry.register(spec, handler)
    return registry


def to_result(value: object) -> dict:
    """
    The port requires a dict tool result. Handlers written for humans return
    whatever is natural (a string, a number, None), so normalise here once.
    """
    if isinstance(value, dict):
        return value
    if value is None:
        return {"success": True}
    return {"success": True, "result": value}

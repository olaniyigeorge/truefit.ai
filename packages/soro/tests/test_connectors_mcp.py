"""
MCP connector. The mapping is tested on a fake session (no SDK needed); one
end-to-end test launches a real stdio server from this interpreter and skips
when the MCP SDK is not installed.
"""

from __future__ import annotations

import sys
import textwrap
from types import SimpleNamespace as NS

import pytest

from soro.connectors import Connector, mcp
from soro.connectors.mcp import to_tool_result

pytestmark = pytest.mark.unit


def _text(t: str):
    return NS(type="text", text=t)


class FakeSession:
    """Anything with async list_tools() and call_tool() will do; mixes 1.x and 2.x field names."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self):
        return NS(
            tools=[
                NS(
                    name="add",
                    description="Add two numbers.",
                    input_schema={"type": "object", "properties": {"a": {"type": "integer"}}},
                ),
                NS(
                    name="delete_file",
                    description=None,
                    inputSchema={"type": "object", "properties": {"path": {"type": "string"}}},
                ),
            ]
        )

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name == "add":
            return NS(content=[_text("5")], structured_content={"result": 5}, is_error=False)
        return NS(content=[_text("permission denied")], isError=True, structuredContent=None)


async def test_tools_and_calls_proxy_through_the_session():
    session = FakeSession()
    conn = mcp(session=session)
    assert isinstance(conn, Connector)
    pairs = await conn.tools()
    specs = {s.name: s for s, _ in pairs}
    assert specs["add"].parameters["properties"] == {"a": {"type": "integer"}}
    assert specs["delete_file"].description == ""
    handlers = {s.name: h for s, h in pairs}
    assert await handlers["add"]({"a": 2}) == {
        "success": True,
        "content": "5",
        "data": {"result": 5},
    }
    assert await handlers["delete_file"]({"path": "/x"}) == {
        "success": False,
        "content": "permission denied",
    }
    assert session.calls == [("add", {"a": 2}), ("delete_file", {"path": "/x"})]
    await conn.aclose()  # a given session is not ours to close


async def test_allowlist_filters_tools():
    pairs = await mcp(session=FakeSession(), tools=["delete_*"]).tools()
    assert [s.name for s, _ in pairs] == ["delete_file"]


def test_result_flattening_counts_non_text_items_and_rejects_unknown_results():
    result = NS(content=[_text("a"), NS(type="image", data="..."), _text("b")], is_error=False)
    assert to_tool_result(result) == {"success": True, "content": "a\nb", "non_text_items": 1}
    assert to_tool_result(NS())["success"] is False


def test_needs_a_target_or_session():
    with pytest.raises(ValueError):
        mcp()


SERVER = textwrap.dedent('''
    try:
        from mcp.server.mcpserver import MCPServer as Server
    except ImportError:
        from mcp.server.fastmcp import FastMCP as Server

    app = Server("demo")

    @app.tool()
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    if __name__ == "__main__":
        app.run()
''')


async def test_real_stdio_server_round_trip(tmp_path):
    pytest.importorskip("mcp")
    script = tmp_path / "server.py"
    script.write_text(SERVER)
    conn = mcp([sys.executable, str(script)])
    try:
        pairs = {s.name: (s, h) for s, h in await conn.tools()}
        spec, handler = pairs["add"]
        assert spec.description == "Add two numbers."
        assert set(spec.parameters["properties"]) == {"a", "b"}
        result = await handler({"a": 2, "b": 3})
        assert result["success"] is True and result["content"] == "5"
    finally:
        await conn.aclose()

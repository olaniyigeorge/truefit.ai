"""
An MCP server as tools.

MCP is how most systems already expose themselves to models, so this connector is
the shortest path from "a server someone else wrote" to "something you can talk
to". It lists the server's tools once per session and proxies each call.

    soro.connectors.mcp("npx -y @modelcontextprotocol/server-filesystem ~/notes")  # stdio
    soro.connectors.mcp("http://localhost:8000/mcp")                              # streamable HTTP

Only tools are bridged. MCP resources and prompts are not, because a voice session
has no natural place to browse them (a follow-up, see docs/build-plan.md).

The MCP client holds anyio task groups, which must be entered and exited from the
same task. The Agent does both inside run(), so that holds; call tools() and
aclose() from one task if you drive the connector yourself.

Needs the MCP SDK: pip install "soro[mcp]". Both the 1.x and 2.x SDKs work.
"""

from __future__ import annotations

import fnmatch
import shlex
from contextlib import AsyncExitStack
from typing import Any, Iterable, Sequence

from soro.connectors.base import ToolPair
from soro.tools import ToolSpec


def _sdk():
    try:
        import mcp
    except ImportError as exc:
        raise ImportError(
            'The MCP connector needs the MCP SDK. Install it with: pip install "soro[mcp]"'
        ) from exc
    return mcp


def _field(obj: Any, snake: str, camel: str, default: Any = None) -> Any:
    # The 2.x SDK renamed fields to snake_case (input_schema, is_error, ...).
    value = getattr(obj, snake, None)
    if value is None:
        value = getattr(obj, camel, None)
    return default if value is None else value


class MCPConnector:
    def __init__(
        self,
        target: str | Sequence[str] | None = None,
        *,
        env: dict[str, str] | None = None,
        tools: Iterable[str] | None = None,
        session: Any = None,
    ) -> None:
        """
        target: an http(s) URL (streamable HTTP), or a command to launch over
            stdio, as a string ("python server.py") or an argv list.
        env: environment for a stdio server.
        tools: allowlist of tool names (fnmatch patterns). None exposes all.
        session: an already-initialised client session (anything with async
            list_tools() and call_tool()). The connector uses it as is and does
            not close it. For tests and for apps that manage their own session.
        """
        if target is None and session is None:
            raise ValueError("mcp() needs a command, a URL or a session")
        self._target = target
        self._env = env
        self._allow = list(tools) if tools is not None else None
        self._given_session = session
        self._session: Any = session
        self._stack: AsyncExitStack | None = None

    async def tools(self) -> list[ToolPair]:
        if self._session is None:
            await self._connect()
        listed = await self._session.list_tools()
        pairs: list[ToolPair] = []
        for t in getattr(listed, "tools", listed):
            if self._allow is not None and not any(
                fnmatch.fnmatchcase(t.name, p) for p in self._allow
            ):
                continue
            schema = _field(t, "input_schema", "inputSchema", {"type": "object", "properties": {}})
            spec = ToolSpec(name=t.name, description=t.description or "", parameters=dict(schema))
            pairs.append((spec, self._handler(t.name)))
        return pairs

    async def aclose(self) -> None:
        if self._stack is not None:
            stack, self._stack = self._stack, None
            self._session = self._given_session
            await stack.aclose()

    async def _connect(self) -> None:
        mcp = _sdk()
        stack = AsyncExitStack()
        try:
            if isinstance(self._target, str) and self._target.startswith(("http://", "https://")):
                read, write = await stack.enter_async_context(_http_client(self._target))
            else:
                from mcp.client.stdio import stdio_client

                argv = (
                    shlex.split(self._target)
                    if isinstance(self._target, str)
                    else list(self._target)
                )
                if not argv:
                    raise ValueError("mcp() was given an empty command")
                params = mcp.StdioServerParameters(command=argv[0], args=argv[1:], env=self._env)
                read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(mcp.ClientSession(read, write))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise
        self._stack, self._session = stack, session

    def _handler(self, name: str):
        async def handle(args: dict[str, Any]) -> dict[str, Any]:
            result = await self._session.call_tool(name, args)
            return to_tool_result(result)

        handle.__name__ = name
        return handle


def _http_client(url: str):
    """Streamable HTTP, named streamable_http_client in SDK 2.x and streamablehttp_client in 1.x."""
    from contextlib import asynccontextmanager

    import mcp.client.streamable_http as transport

    factory = getattr(transport, "streamable_http_client", None) or transport.streamablehttp_client

    @asynccontextmanager
    async def connect():
        async with factory(url) as streams:
            yield streams[0], streams[1]  # 1.x adds a session-id getter as a third item

    return connect()


def to_tool_result(result: Any) -> dict[str, Any]:
    """
    Flatten an MCP CallToolResult into the dict the port expects. Text content is
    joined (it is what the model will speak from); structured content is kept as
    data when the server provides it; an error result stays a result so the model
    can say what went wrong instead of the session failing.
    """
    content = getattr(result, "content", None)
    if content is None:  # 2.x may return a non-tool result, e.g. input required
        return {"success": False, "error": f"Unsupported MCP result: {type(result).__name__}"}
    texts = [
        c.text for c in content if getattr(c, "type", None) == "text" and getattr(c, "text", None)
    ]
    out: dict[str, Any] = {"success": not bool(_field(result, "is_error", "isError", False))}
    if texts:
        out["content"] = "\n".join(texts)
    structured = _field(result, "structured_content", "structuredContent")
    if structured is not None:
        out["data"] = structured
    skipped = len(content) - len(texts)
    if skipped:
        out["non_text_items"] = skipped  # images/resources: the model learns they exist
    return out


def mcp(target: str | Sequence[str] | None = None, **options: Any) -> MCPConnector:
    """A connector over an MCP server. See MCPConnector for the options."""
    return MCPConnector(target, **options)

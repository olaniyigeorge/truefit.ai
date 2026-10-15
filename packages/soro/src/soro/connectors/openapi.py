"""
An OpenAPI 3 spec as tools: point Soro at an existing HTTP API and talk to it.

Each operation becomes one tool. The name is the operationId (or method_path when
there is none), the description is its summary, and the arguments schema merges
the path, query and header parameters with the JSON request body. The handler
maps the model's arguments back onto the request and returns the response.

    soro.connectors.openapi(
        "https://my-os.example/openapi.json",
        headers={"Authorization": f"Bearer {token}"},
        operations=["list_notes", "create_*"],   # allowlist, fnmatch patterns
    )

An allowlist matters more for voice than for text: every tool you expose is one
the model may call from a misheard sentence. Pair write operations with
Agent(confirm=[...]).

Needs httpx (and pyyaml for YAML specs): pip install "soro[openapi]"
"""

from __future__ import annotations

import copy
import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin

from soro.connectors.base import ToolPair
from soro.tools import ToolSpec

_METHODS = ("get", "put", "post", "delete", "patch", "head", "options")
_NAME_OK = re.compile(r"[^a-zA-Z0-9_-]+")
_MAX_NAME = 64  # the strictest provider limit on function names


def _httpx():
    try:
        import httpx
    except ImportError as exc:
        raise ImportError(
            'The OpenAPI connector needs httpx. Install it with: pip install "soro[openapi]"'
        ) from exc
    return httpx


@dataclass(frozen=True)
class Operation:
    """How one tool maps back onto an HTTP request."""

    name: str
    method: str
    path: str
    summary: str
    tags: tuple[str, ...]
    parameters: dict[str, Any]
    locations: dict[str, str] = field(default_factory=dict)  # arg name -> path|query|header|body
    body_whole: bool = False  # the request body is one "body" argument rather than spread fields


class OpenAPIConnector:
    def __init__(
        self,
        spec: str | Path | dict,
        *,
        base_url: str | None = None,
        headers: dict[str, str] | None = None,
        operations: Iterable[str] | None = None,
        tags: Iterable[str] | None = None,
        timeout: float = 15.0,
        transport: Any = None,
    ) -> None:
        """
        spec: a URL, a file path (JSON or YAML), or an already-parsed dict.
        base_url: where to send requests. Defaults to the spec's first server,
            resolved against the spec URL when it is relative.
        headers: sent on every request, the place for auth.
        operations / tags: allowlists (fnmatch patterns for operations). With
            neither, every operation becomes a tool.
        transport: an httpx transport, for tests (httpx.MockTransport) or proxies.
        """
        self._source = spec
        self._base_url = base_url
        self._headers = dict(headers or {})
        self._allow_ops = list(operations) if operations is not None else None
        self._allow_tags = set(tags) if tags is not None else None
        self._timeout = timeout
        self._transport = transport
        self._client = None

    async def tools(self) -> list[ToolPair]:
        httpx = _httpx()
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=self._headers, timeout=self._timeout, transport=self._transport
            )
        doc, spec_url = await self._load()
        base = self._base_url or _server_url(doc, spec_url)
        if not base:
            raise ValueError("The spec has no servers entry; pass base_url=")
        ops = [op for op in parse_operations(doc) if self._allowed(op)]
        return [
            (ToolSpec(op.name, op.summary, op.parameters), self._handler(op, base)) for op in ops
        ]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _allowed(self, op: Operation) -> bool:
        if self._allow_ops is not None and not any(
            fnmatch.fnmatchcase(op.name, p) for p in self._allow_ops
        ):
            return False
        if self._allow_tags is not None and not self._allow_tags.intersection(op.tags):
            return False
        return True

    async def _load(self) -> tuple[dict, str | None]:
        src = self._source
        if isinstance(src, dict):
            return src, None
        text_src = str(src)
        if re.match(r"^https?://", text_src):
            resp = await self._client.get(text_src)
            resp.raise_for_status()
            return _parse_text(resp.text), text_src
        return _parse_text(Path(text_src).read_text(encoding="utf-8")), None

    def _handler(self, op: Operation, base: str):
        async def handle(args: dict[str, Any]) -> dict[str, Any]:
            path = op.path
            query: dict[str, Any] = {}
            headers: dict[str, str] = {}
            body: Any = None
            for key, value in args.items():
                where = op.locations.get(key)
                if where == "path":
                    path = path.replace("{" + key + "}", _quote(value))
                elif where == "query":
                    query[key] = value
                elif where == "header":
                    headers[key] = str(value)
                elif where == "body":
                    if op.body_whole:
                        body = value
                    else:
                        body = body or {}
                        body[key] = value
            missing = re.findall(r"{([^}]+)}", path)
            if missing:
                return {"success": False, "error": f"Missing path arguments: {missing}"}
            url = base.rstrip("/") + "/" + path.lstrip("/")
            resp = await self._client.request(
                op.method.upper(),
                url,
                params=query or None,
                headers=headers or None,
                json=body,
            )
            return _result(resp)

        handle.__name__ = op.name
        return handle


def openapi(spec: str | Path | dict, **options: Any) -> OpenAPIConnector:
    """A connector over an OpenAPI 3 spec. See OpenAPIConnector for the options."""
    return OpenAPIConnector(spec, **options)


# ── Spec parsing (pure, no network: tested directly)


def parse_operations(doc: dict) -> list[Operation]:
    ops: list[Operation] = []
    seen: set[str] = set()
    for path, item in (doc.get("paths") or {}).items():
        item = _deref(doc, item)
        shared = item.get("parameters", [])
        for method in _METHODS:
            raw = item.get(method)
            if raw is None:
                continue
            raw = _deref(doc, raw)
            name = _tool_name(raw.get("operationId") or f"{method}_{path}")
            if name in seen:  # two paths sanitising to one name: keep both, distinctly
                i = 2
                while f"{name}_{i}"[:_MAX_NAME] in seen:
                    i += 1
                name = f"{name}_{i}"[:_MAX_NAME]
            seen.add(name)
            ops.append(_operation(doc, name, method, path, raw, shared))
    return ops


def _operation(doc: dict, name: str, method: str, path: str, raw: dict, shared: list) -> Operation:
    properties: dict[str, Any] = {}
    required: list[str] = []
    locations: dict[str, str] = {}

    # Operation-level parameters override path-level ones with the same (name, in).
    params: dict[tuple[str, str], dict] = {}
    for p in [*shared, *raw.get("parameters", [])]:
        p = _deref(doc, p)
        params[(p["name"], p.get("in", "query"))] = p
    for (pname, where), p in params.items():
        if where == "cookie":
            continue  # cookies are auth plumbing, set them with headers=, not by the model
        schema = _resolve(doc, p.get("schema") or {})
        if p.get("description"):
            schema = {**schema, "description": p["description"]}
        properties[pname] = schema
        locations[pname] = where
        if p.get("required") or where == "path":
            required.append(pname)

    body_whole = False
    body = _deref(doc, raw.get("requestBody") or {})
    content = body.get("content") or {}
    media = content.get("application/json") or next(
        (v for k, v in content.items() if k.endswith("+json")), None
    )
    if media is not None:
        schema = _resolve(doc, media.get("schema") or {})
        fields = schema.get("properties") if schema.get("type", "object") == "object" else None
        if fields and not set(fields) & set(properties):
            # Spread the body's fields so the model fills {"title": ...}, not {"body": {"title": ...}}.
            for fname, fschema in fields.items():
                properties[fname] = fschema
                locations[fname] = "body"
            if body.get("required"):
                required.extend(r for r in schema.get("required", []) if r in fields)
        else:
            body_whole = True
            properties["body"] = schema
            locations["body"] = "body"
            if body.get("required"):
                required.append("body")

    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = sorted(set(required), key=required.index)
    summary = (raw.get("summary") or raw.get("description") or "").strip()
    return Operation(
        name=name,
        method=method,
        path=path,
        summary=summary,
        tags=tuple(raw.get("tags") or ()),
        parameters=parameters,
        locations=locations,
        body_whole=body_whole,
    )


def _deref(doc: dict, node: Any) -> Any:
    """Follow a single local $ref (#/components/...). Remote refs are left alone."""
    seen = set()
    while (
        isinstance(node, dict)
        and isinstance(node.get("$ref"), str)
        and node["$ref"].startswith("#/")
    ):
        ref = node["$ref"]
        if ref in seen:
            return {}
        seen.add(ref)
        target: Any = doc
        for part in ref[2:].split("/"):
            target = (
                target.get(part.replace("~1", "/").replace("~0", "~"), {})
                if isinstance(target, dict)
                else {}
            )
        node = target
    return node


def _resolve(doc: dict, schema: Any, depth: int = 0) -> Any:
    """
    Inline local $refs throughout a schema so providers (which do not resolve
    refs) see the whole shape. Depth-capped: a recursive schema becomes an open
    object past the cap instead of looping forever.
    """
    if depth > 8:
        return {"type": "object"}
    schema = _deref(doc, schema)
    if isinstance(schema, dict):
        return {
            k: _resolve(doc, v, depth + 1)
            for k, v in schema.items()
            if k not in ("$ref", "xml", "example")
        }
    if isinstance(schema, list):
        return [_resolve(doc, v, depth + 1) for v in schema]
    return copy.deepcopy(schema)


def _tool_name(raw: str) -> str:
    name = re.sub(r"_+", "_", _NAME_OK.sub("_", raw)).strip("_") or "operation"
    return name[:_MAX_NAME]


def _server_url(doc: dict, spec_url: str | None) -> str | None:
    servers = doc.get("servers") or []
    url = servers[0].get("url") if servers else None
    if url and spec_url and not re.match(r"^https?://", url):
        return urljoin(spec_url, url)
    if url is None and spec_url:
        return urljoin(spec_url, "/")
    return url


def _parse_text(text: str) -> dict:
    stripped = text.lstrip()
    if stripped.startswith("{"):
        return json.loads(text)
    try:
        import yaml
    except ImportError as exc:
        raise ImportError(
            'YAML OpenAPI specs need pyyaml. Install it with: pip install "soro[openapi]"'
        ) from exc
    return yaml.safe_load(text)


def _quote(value: Any) -> str:
    from urllib.parse import quote

    return quote(str(value), safe="")


def _result(resp: Any) -> dict[str, Any]:
    """
    Errors come back as results, not exceptions: a 404 is information the model
    can act on ("that note does not exist"), and the runtime would otherwise turn
    it into an opaque error string.
    """
    try:
        data: Any = resp.json()
    except ValueError:
        data = resp.text
    return {"success": resp.is_success, "status": resp.status_code, "data": data}

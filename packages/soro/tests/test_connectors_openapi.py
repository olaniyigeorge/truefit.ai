"""
OpenAPI connector: spec parsing is pure and tested directly; the handlers run
against httpx.MockTransport, a local stub server with no network.
"""

from __future__ import annotations

import json

import pytest

httpx = pytest.importorskip("httpx")

from soro.connectors import openapi  # noqa: E402
from soro.connectors.openapi import parse_operations  # noqa: E402

pytestmark = pytest.mark.unit

SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Notes", "version": "1"},
    "servers": [{"url": "https://notes.example/api"}],
    "components": {
        "schemas": {
            "NewNote": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
                "required": ["title"],
            },
            "Tag": {"type": "string", "enum": ["work", "home"]},
        },
        "parameters": {"NoteId": {"name": "note_id", "in": "path", "required": True, "schema": {"type": "string"}}},
    },
    "paths": {
        "/notes": {
            "get": {
                "operationId": "list_notes",
                "summary": "List notes.",
                "tags": ["notes"],
                "parameters": [
                    {"name": "tag", "in": "query", "schema": {"$ref": "#/components/schemas/Tag"}},
                    {"name": "limit", "in": "query", "description": "Max results.", "schema": {"type": "integer"}},
                ],
            },
            "post": {
                "operationId": "create_note",
                "summary": "Create a note.",
                "tags": ["notes"],
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/NewNote"}}},
                },
            },
        },
        "/notes/{note_id}": {
            "parameters": [{"$ref": "#/components/parameters/NoteId"}],
            "delete": {"operationId": "delete_note", "summary": "Delete a note.", "tags": ["admin"]},
            "put": {
                "summary": "Replace tags.",
                "requestBody": {"content": {"application/json": {"schema": {"type": "array", "items": {"type": "string"}}}}},
            },
        },
    },
}


def test_operations_become_tools_with_merged_argument_schemas():
    ops = {op.name: op for op in parse_operations(SPEC)}
    assert set(ops) == {"list_notes", "create_note", "delete_note", "put_notes_note_id"}

    listing = ops["list_notes"].parameters
    assert listing["properties"]["tag"] == {"type": "string", "enum": ["work", "home"]}  # $ref inlined
    assert listing["properties"]["limit"]["description"] == "Max results."
    assert "required" not in listing

    create = ops["create_note"]
    assert create.parameters["properties"]["title"] == {"type": "string"}  # body fields spread
    assert create.parameters["required"] == ["title"]
    assert create.locations == {"title": "body", "body": "body"}

    delete = ops["delete_note"]
    assert delete.parameters["required"] == ["note_id"]  # path-level parameter inherited
    assert delete.locations == {"note_id": "path"}

    replace = ops["put_notes_note_id"]  # no operationId: derived, sanitised name
    assert replace.body_whole and replace.parameters["properties"]["body"]["type"] == "array"


def _stub():
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/api/notes" and request.method == "GET":
            return httpx.Response(200, json=[{"id": "1", "title": "milk"}])
        if request.url.path == "/api/notes" and request.method == "POST":
            return httpx.Response(201, json={"id": "2", **json.loads(request.content)})
        if request.url.path.startswith("/api/notes/") and request.method == "DELETE":
            return httpx.Response(404, json={"detail": "no such note"})
        if request.url.path == "/spec.json":
            return httpx.Response(200, json={**SPEC, "servers": [{"url": "/api"}]})
        return httpx.Response(500, text="unexpected")

    return calls, httpx.MockTransport(respond)


async def _tools(conn):
    return {spec.name: (spec, handler) for spec, handler in await conn.tools()}


async def test_handlers_map_arguments_onto_the_request():
    calls, transport = _stub()
    conn = openapi(SPEC, transport=transport, headers={"Authorization": "Bearer t"})
    tools = await _tools(conn)

    result = await tools["list_notes"][1]({"tag": "work", "limit": 5})
    assert result == {"success": True, "status": 200, "data": [{"id": "1", "title": "milk"}]}
    assert str(calls[-1].url) == "https://notes.example/api/notes?tag=work&limit=5"
    assert calls[-1].headers["authorization"] == "Bearer t"

    result = await tools["create_note"][1]({"title": "eggs"})
    assert result["status"] == 201 and result["data"] == {"id": "2", "title": "eggs"}
    assert json.loads(calls[-1].content) == {"title": "eggs"}
    await conn.aclose()


async def test_http_errors_come_back_as_results_and_path_args_are_escaped():
    calls, transport = _stub()
    conn = openapi(SPEC, transport=transport)
    tools = await _tools(conn)
    result = await tools["delete_note"][1]({"note_id": "a/b"})
    assert result == {"success": False, "status": 404, "data": {"detail": "no such note"}}
    assert calls[-1].url.raw_path == b"/api/notes/a%2Fb"
    assert (await tools["delete_note"][1]({}))["error"].startswith("Missing path arguments")
    await conn.aclose()


async def test_allowlists_by_operation_pattern_and_tag():
    _, transport = _stub()
    assert set(await _tools(openapi(SPEC, transport=transport, operations=["*_note"]))) == {
        "create_note", "delete_note",
    }
    assert set(await _tools(openapi(SPEC, transport=transport, tags=["admin"]))) == {"delete_note"}


async def test_spec_from_url_resolves_a_relative_server():
    calls, transport = _stub()
    conn = openapi("https://notes.example/spec.json", transport=transport)
    tools = await _tools(conn)
    await tools["list_notes"][1]({})
    assert str(calls[-1].url) == "https://notes.example/api/notes"
    await conn.aclose()


async def test_yaml_spec_from_a_file(tmp_path):
    yaml = pytest.importorskip("yaml")
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(SPEC))
    _, transport = _stub()
    tools = await _tools(openapi(path, transport=transport))
    assert "create_note" in tools


async def test_missing_server_needs_base_url():
    _, transport = _stub()
    spec = {k: v for k, v in SPEC.items() if k != "servers"}
    with pytest.raises(ValueError, match="base_url"):
        await openapi(spec, transport=transport).tools()
    tools = await _tools(openapi(spec, transport=transport, base_url="https://notes.example/api"))
    assert (await tools["list_notes"][1]({}))["status"] == 200

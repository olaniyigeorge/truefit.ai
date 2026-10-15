"""Functions connector: signature and docstring to ToolSpec, and the handler wrapper."""

from __future__ import annotations

import enum
import threading
from typing import Annotated, Literal, Optional

import pytest

from soro import SessionComplete, tool
from soro.connectors import Connector, functions, registry_from_pairs, spec_from_function

pytestmark = pytest.mark.unit


class Priority(enum.Enum):
    LOW = "low"
    HIGH = "high"


async def save_note(text: str, pinned: bool = False, tags: list[str] | None = None) -> str:
    """
    Save a note for the user.

    Args:
        text: What to write down.
        pinned: Keep it at the top
            of the list.
        tags: Labels for later search.

    Returns:
        The note id.
    """
    return "n1"


def test_schema_from_signature_and_docstring():
    spec = spec_from_function(save_note)
    assert spec.name == "save_note"
    assert spec.description == "Save a note for the user."
    props = spec.parameters["properties"]
    assert props["text"] == {"type": "string", "description": "What to write down."}
    assert props["pinned"] == {
        "type": "boolean",
        "description": "Keep it at the top of the list.",
        "default": False,
    }
    assert props["tags"] == {
        "type": "array",
        "items": {"type": "string"},
        "description": "Labels for later search.",
    }
    assert spec.parameters["required"] == ["text"]


def test_rich_types_map_to_json_schema():
    def f(
        level: Literal["a", "b"],
        prio: Priority,
        n: Optional[int] = None,
        ratio: float = 0.5,
        meta: dict | None = None,
        note: Annotated[str, "a short note"] = "",
        either: int | str = 1,
    ) -> None:
        """Do it."""

    props = spec_from_function(f).parameters["properties"]
    assert props["level"] == {"enum": ["a", "b"], "type": "string"}
    assert props["prio"] == {"type": "string", "enum": ["low", "high"]}
    assert props["n"] == {"type": "integer"}
    assert props["ratio"] == {"type": "number", "default": 0.5}
    assert props["meta"] == {"type": "object"}
    assert props["note"] == {"type": "string", "description": "a short note", "default": ""}
    assert props["either"]["anyOf"] == [{"type": "integer"}, {"type": "string"}]


def test_no_parameters_gives_an_empty_object_schema():
    def ping():
        pass

    spec = spec_from_function(ping)
    assert spec.parameters == {"type": "object", "properties": {}}
    assert spec.description == ""


def test_decorator_overrides_name_and_description_and_keeps_the_function():
    @tool(name="remember", description="Remember something.")
    def f(x: int) -> int:
        """Ignored."""
        return x * 2

    assert f(3) == 6  # still an ordinary function
    assert f.__soro_tool__.name == "remember"
    assert f.__soro_tool__.description == "Remember something."

    @tool
    def g() -> None:
        """Bare decorator."""

    assert g.__soro_tool__.description == "Bare decorator."


async def test_connector_yields_registerable_pairs_and_handlers_normalise_results():
    def add(a: int, b: int) -> int:
        """Add."""
        return a + b

    def nothing() -> None:
        """Returns None."""

    async def as_dict(x: str) -> dict:
        """Dict passthrough."""
        return {"echo": x}

    conn = functions(add, nothing, as_dict)
    assert isinstance(conn, Connector)
    registry = registry_from_pairs(await conn.tools())
    assert [s.name for s in registry.specs] == ["add", "nothing", "as_dict"]
    assert await registry.dispatch("add", {"a": 2, "b": 3}) == {"success": True, "result": 5}
    assert await registry.dispatch("nothing", {}) == {"success": True}
    assert await registry.dispatch("as_dict", {"x": "hi"}) == {"echo": "hi"}


async def test_unknown_arguments_are_dropped_unless_kwargs_accepted():
    seen = {}

    def strict(a: int) -> None:
        seen["strict"] = a

    def loose(a: int, **rest) -> None:
        seen["loose"] = rest

    (_, h1), (_, h2) = await functions(strict, loose).tools()
    await h1({"a": 1, "invented": True})
    await h2({"a": 1, "invented": True})
    assert seen == {"strict": 1, "loose": {"invented": True}}


async def test_sync_functions_run_off_the_event_loop():
    main = threading.get_ident()
    ran_on = {}

    def blocking() -> None:
        ran_on["thread"] = threading.get_ident()

    [(_, handler)] = await functions(blocking).tools()
    await handler({})
    assert ran_on["thread"] != main


async def test_session_complete_propagates_from_a_function_tool():
    async def end_call() -> None:
        raise SessionComplete("bye")

    [(_, handler)] = await functions(end_call).tools()
    with pytest.raises(SessionComplete):
        await handler({})


def test_functions_requires_at_least_one():
    with pytest.raises(ValueError):
        functions()

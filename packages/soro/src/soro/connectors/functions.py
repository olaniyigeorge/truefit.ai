"""
Plain Python functions as tools.

The smallest connector, and the one most agents start with: write a typed,
documented function and it becomes a tool. The signature becomes the JSON Schema,
the docstring becomes the description, so the two can never drift apart the way
a hand-written ToolSpec and its handler can.

    @soro.tool
    async def save_note(text: str, pinned: bool = False) -> str:
        '''Save a note for the user.

        Args:
            text: What to write down.
            pinned: Keep it at the top of the list.
        '''

    connector = soro.connectors.functions(save_note, end_call)

Sync functions run in a worker thread, so a blocking call (a database driver, a
file read) never stalls the audio loops.
"""

from __future__ import annotations

import asyncio
import enum
import inspect
import re
import types
import typing
from typing import Any, Callable, Literal, Union, get_args, get_origin, get_type_hints

from soro.connectors.base import ToolPair, to_result
from soro.tools import ToolSpec

_SPEC_ATTR = "__soro_tool__"

_SCALARS: dict[Any, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}


def tool(
    fn: Callable | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
):
    """
    Mark a function as a tool, optionally overriding its name or description.
    Usable bare (@tool) or with arguments (@tool(name="x")). The function itself
    is returned unchanged, so it stays callable and testable as ordinary code.
    """

    def mark(f: Callable) -> Callable:
        setattr(f, _SPEC_ATTR, spec_from_function(f, name=name, description=description))
        return f

    return mark(fn) if fn is not None else mark


def spec_from_function(
    fn: Callable, *, name: str | None = None, description: str | None = None
) -> ToolSpec:
    """Build a ToolSpec from a function's signature, type hints and docstring."""
    summary, arg_docs = _parse_docstring(inspect.getdoc(fn) or "")
    try:
        hints = get_type_hints(fn, include_extras=True)
    except Exception:  # unresolvable forward refs: fall back to untyped arguments
        hints = {}

    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in inspect.signature(fn).parameters.values():
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            continue
        schema = _schema_for(hints.get(param.name, Any))
        if param.name in arg_docs:
            schema["description"] = arg_docs[param.name]
        if param.default is inspect.Parameter.empty:
            required.append(param.name)
        elif param.default is not None and _is_json(param.default):
            schema["default"] = param.default
        properties[param.name] = schema

    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        parameters["required"] = required
    return ToolSpec(
        name=name or fn.__name__,
        description=description if description is not None else summary,
        parameters=parameters,
    )


def handler_for(fn: Callable):
    """
    Wrap fn as a ToolHandler: dict of args in, dict out. Arguments the function
    does not declare are dropped (models occasionally invent extras) unless it
    takes **kwargs.
    """
    sig = inspect.signature(fn)
    takes_kwargs = any(p.kind is p.VAR_KEYWORD for p in sig.parameters.values())
    accepted = set(sig.parameters)
    is_async = inspect.iscoroutinefunction(fn)

    async def handle(args: dict[str, Any]) -> dict[str, Any]:
        kwargs = dict(args) if takes_kwargs else {k: v for k, v in args.items() if k in accepted}
        if is_async:
            value = await fn(**kwargs)
        else:
            value = await asyncio.to_thread(fn, **kwargs)
        return to_result(value)

    handle.__name__ = getattr(fn, "__name__", "tool")
    return handle


class FunctionConnector:
    def __init__(self, *fns: Callable) -> None:
        if not fns:
            raise ValueError("functions() needs at least one function")
        self._fns = fns

    async def tools(self) -> list[ToolPair]:
        return [
            (getattr(f, _SPEC_ATTR, None) or spec_from_function(f), handler_for(f))
            for f in self._fns
        ]

    async def aclose(self) -> None:
        return None


def functions(*fns: Callable) -> FunctionConnector:
    """A connector over plain functions. @tool is optional; it only overrides name or description."""
    return FunctionConnector(*fns)


# ── Type hints to JSON Schema


def _schema_for(hint: Any) -> dict[str, Any]:
    if hint is Any or hint is inspect.Parameter.empty:
        return {}
    if hint in _SCALARS:
        return {"type": _SCALARS[hint]}
    if hint is type(None):
        return {"type": "null"}
    if inspect.isclass(hint) and issubclass(hint, enum.Enum):
        return {
            "type": "string" if all(isinstance(m.value, str) for m in hint) else "integer",
            "enum": [m.value for m in hint],
        }

    origin, args = get_origin(hint), get_args(hint)
    if origin is typing.Annotated:
        # Annotated[str, "the user's note"]: a string metadata item is the description.
        schema = _schema_for(args[0])
        text = next((a for a in args[1:] if isinstance(a, str)), None)
        if text:
            schema["description"] = text
        return schema
    if origin in (Union, types.UnionType):
        options = [a for a in args if a is not type(None)]
        # Optional[X] is just X to the model: it may leave the argument out.
        return (
            _schema_for(options[0])
            if len(options) == 1
            else {"anyOf": [_schema_for(a) for a in options]}
        )
    if origin is Literal:
        values = list(args)
        schema: dict[str, Any] = {"enum": values}
        kinds = {_SCALARS.get(type(v)) for v in values}
        if len(kinds) == 1 and None not in kinds:
            schema["type"] = kinds.pop()
        return schema
    if origin in (list, tuple, set, frozenset) or hint in (list, tuple, set, frozenset):
        item = args[0] if args and args[0] is not Ellipsis else Any
        return {"type": "array", "items": _schema_for(item)}
    if origin is dict or hint is dict:
        return {"type": "object"}
    if inspect.isclass(hint) and hasattr(hint, "model_json_schema"):  # pydantic models
        return hint.model_json_schema()
    return {}


def _is_json(value: Any) -> bool:
    return isinstance(value, (str, int, float, bool, list, dict))


# ── Docstrings

_SECTION = re.compile(
    r"^(Args|Arguments|Parameters|Params|Returns|Raises|Yields|Examples?|Notes?):\s*$"
)


def _parse_docstring(doc: str) -> tuple[str, dict[str, str]]:
    """
    Summary = everything before the first section header. Argument descriptions
    come from a Google-style "Args:" section ("name: text" or "name (type): text",
    continuation lines indented further). Other styles still get a summary.
    """
    lines = doc.splitlines()
    summary: list[str] = []
    args: dict[str, str] = {}
    section: str | None = None
    current: str | None = None
    for line in lines:
        header = _SECTION.match(line.strip())
        if header:
            section, current = header.group(1), None
            continue
        if section is None:
            summary.append(line)
        elif section in ("Args", "Arguments", "Parameters", "Params"):
            m = re.match(r"^\s*(\*{0,2}\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$", line)
            if m and (current is None or _indent(line) <= _indent_of_first_arg(lines, section)):
                current = m.group(1).lstrip("*")
                args[current] = m.group(2).strip()
            elif current and line.strip():
                args[current] = f"{args[current]} {line.strip()}".strip()
    return " ".join(" ".join(summary).split()), args


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _indent_of_first_arg(lines: list[str], section: str) -> int:
    for i, line in enumerate(lines):
        if line.strip() == f"{section}:":
            for nxt in lines[i + 1 :]:
                if nxt.strip():
                    return _indent(nxt)
    return 0

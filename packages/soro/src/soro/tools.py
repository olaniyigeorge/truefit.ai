"""
Provider-neutral tool description.

Agents describe tools once as ToolSpec. Each LiveSessionPort adapter translates
specs into its provider's wire format, so no agent code needs to know whether
it is talking to Gemini function_declarations or OpenAI function tools.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

def _empty_schema() -> dict[str, Any]:
    # A fresh nested dict every time: a shared default would let one spec's
    # mutation leak into every other spec.
    return {"type": "object", "properties": {}}


@dataclass(frozen=True)
class ToolSpec:
    """name, human description and a JSON Schema object for the arguments."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=_empty_schema)

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("ToolSpec.name cannot be empty")


def _schema_to_dict(parameters: Any) -> dict[str, Any]:
    if parameters is None:
        return _empty_schema()
    if isinstance(parameters, dict):
        return parameters
    if hasattr(parameters, "model_dump"):  # pydantic-style schema objects
        return parameters.model_dump(exclude_none=True)
    raise TypeError(f"Cannot convert schema of type {type(parameters).__name__}")


def _one(item: Any) -> ToolSpec:
    if isinstance(item, ToolSpec):
        return item
    if isinstance(item, dict):
        if "name" not in item:
            raise ValueError(f"Tool declaration has no name: {item!r}")
        # Covers a bare Gemini declaration and an OpenAI {"type": "function", ...} tool.
        return ToolSpec(
            name=item["name"],
            description=item.get("description", ""),
            parameters=_schema_to_dict(item.get("parameters")),
        )
    if hasattr(item, "name"):  # SDK-style object with .name/.description/.parameters
        return ToolSpec(
            name=item.name,
            description=getattr(item, "description", "") or "",
            parameters=_schema_to_dict(getattr(item, "parameters", None)),
        )
    raise TypeError(f"Cannot interpret {type(item).__name__} as a tool")


def normalize_tools(tools: Iterable[Any] | None) -> list[ToolSpec]:
    """
    Accepts ToolSpec objects, bare declaration dicts, OpenAI-style function
    dicts, and the legacy Gemini group shape [{"function_declarations": [...]}].
    Returns a flat list of ToolSpec. Raises on names declared twice.
    """
    specs: list[ToolSpec] = []
    for item in tools or []:
        if isinstance(item, dict) and "function_declarations" in item:
            specs.extend(_one(d) for d in item["function_declarations"])
        else:
            specs.append(_one(item))
    names = [s.name for s in specs]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ValueError(f"Duplicate tool names: {dupes}")
    return specs

"""
ToolRegistry - tool declarations and their handlers in one place.

A consumer registers each tool once (declaration + handler); the runtime asks
the registry for the declarations to hand to the LiveSessionPort and for
dispatching calls back to handlers. This is what lets tools be an *input* to
the runtime instead of being baked into it.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from src.truefit_core.application.tools import ToolSpec, normalize_tools

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: list[ToolSpec] = []
        self._handlers: dict[str, ToolHandler] = {}

    def register(
        self, spec: ToolSpec | dict[str, Any], handler: ToolHandler
    ) -> "ToolRegistry":
        """
        spec: a ToolSpec, or a bare declaration dict {"name", "description", "parameters"}.
        Returns self so registrations can be chained.
        """
        (spec,) = normalize_tools([spec])
        if spec.name in self._handlers:
            raise ValueError(f"Tool {spec.name!r} is already registered")
        self._specs.append(spec)
        self._handlers[spec.name] = handler
        return self

    @classmethod
    def from_declarations(
        cls,
        tools: list[dict[str, Any]],
        handlers: dict[str, ToolHandler],
    ) -> "ToolRegistry":
        """
        Build a registry from an existing declaration list (ToolSpecs, or the
        legacy [{"function_declarations": [...]}] shape) plus a name -> handler map.
        Every declared tool needs a handler and vice versa, so a mismatch
        fails at construction instead of mid-session.
        """
        declared = normalize_tools(tools)
        names = {d.name for d in declared}
        if names != set(handlers):
            missing = sorted(names - set(handlers))
            extra = sorted(set(handlers) - names)
            raise ValueError(
                f"Tool declarations and handlers do not match "
                f"(no handler for: {missing}; no declaration for: {extra})"
            )
        registry = cls()
        for d in declared:
            registry.register(d, handlers[d.name])
        return registry

    @property
    def specs(self) -> list[ToolSpec]:
        """The tools list to pass to LiveSessionPort.open_session()."""
        return list(self._specs)

    def __contains__(self, name: str) -> bool:
        return name in self._handlers

    async def dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = self._handlers.get(name)
        if handler is None:
            return {"error": f"Unknown tool: {name}", "success": False}
        return await handler(args)

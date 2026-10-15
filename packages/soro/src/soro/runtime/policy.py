"""
Response policy: the voice-specific rules a text agent does not need.

Applied around tool handlers by the Agent facade, so VoiceAgentRuntime stays a
plain dispatcher and code that drives the runtime directly is unaffected.

- Confirm before execute. A misheard sentence must not delete anything. Matching
  tools gain a `confirmed` argument; called without confirmed=true they do not
  run and instead tell the model to read the action back and ask. This is
  model-mediated, not a hard guarantee: the guard stops a call the model did not
  confirm, but it cannot hear whether the user really said yes. The system prompt
  convention (CONFIRM_INSTRUCTIONS) is what makes the model ask.

- Non-blocking tools. A realtime model waits in silence for a tool response, and
  dead air of more than a second or two sounds broken. A background tool returns
  an acknowledgement at once so the model can say "give me a moment", runs on,
  and its real result is injected into the session with send_client_content when
  it finishes.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
from typing import Any, Awaitable, Callable, Iterable, Optional

from soro.runtime.registry import ToolHandler
from soro.tools import ToolSpec

logger = logging.getLogger("soro.policy")

Notify = Callable[[str], Awaitable[None]]
ToolPair = tuple[ToolSpec, ToolHandler]

CONFIRM_ARG = "confirmed"

CONFIRM_INSTRUCTIONS = (
    "Some tools change things and need the user's explicit spoken confirmation. "
    "Before calling one, say exactly what you are about to do and ask the user to "
    f"confirm. Only after they clearly agree, call it with {CONFIRM_ARG}=true. "
    "If they hesitate or say no, do not call it."
)

BACKGROUND_INSTRUCTIONS = (
    "Some tools run in the background. When one returns status 'started', tell the "
    "user you are working on it and keep the conversation going. Its result arrives "
    "later as a message starting with [tool result]; share it when it does."
)


def matches(name: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(name, p) for p in patterns)


# ── Confirm before execute


def require_confirmation(spec: ToolSpec, handler: ToolHandler) -> ToolPair:
    """Add a required `confirmed` flag; refuse to run until the model sets it."""
    params = dict(spec.parameters)
    properties = dict(params.get("properties") or {})
    properties[CONFIRM_ARG] = {
        "type": "boolean",
        "description": "Set true only after the user explicitly confirmed this action aloud.",
    }
    params["properties"] = properties
    params["required"] = [*(params.get("required") or []), CONFIRM_ARG]
    guarded_spec = ToolSpec(
        name=spec.name,
        description=f"{spec.description} Requires spoken confirmation first.".strip(),
        parameters=params,
    )

    async def guarded(args: dict[str, Any]) -> dict[str, Any]:
        args = dict(args)
        confirmed = args.pop(CONFIRM_ARG, False)
        if confirmed is not True and str(confirmed).lower() != "true":
            return {
                "success": False,
                "needs_confirmation": True,
                "message": (
                    "Not done. Read this action back to the user and ask them to confirm. "
                    f"Call again with {CONFIRM_ARG}=true only if they agree."
                ),
            }
        return await handler(args)

    return guarded_spec, guarded


# ── Non-blocking tools


class BackgroundTools:
    """
    Runs wrapped handlers as tasks and reports each result into the session.

    The session does not exist yet when tools are wrapped, so the sink is attached
    later (attach()). Results that finish after the session closed are logged and
    dropped. aclose() cancels whatever is still running.
    """

    def __init__(self) -> None:
        self._notify: Optional[Notify] = None
        self._tasks: set[asyncio.Task] = set()
        self._lock = asyncio.Lock()

    def attach(self, notify: Notify) -> None:
        self._notify = notify

    @property
    def pending(self) -> int:
        return len(self._tasks)

    def wrap(self, spec: ToolSpec, handler: ToolHandler) -> ToolPair:
        async def start(args: dict[str, Any]) -> dict[str, Any]:
            task = asyncio.create_task(
                self._run(spec.name, handler, args), name=f"bg-tool-{spec.name}"
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            return {
                "success": True,
                "status": "started",
                "message": "Running in the background. Tell the user, keep talking; the result follows.",
            }

        return spec, start

    async def _run(self, name: str, handler: ToolHandler, args: dict[str, Any]) -> None:
        try:
            result = await handler(args)
            text = f"[tool result] {name} finished: {json.dumps(result, default=str)}"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"[Policy] Background tool {name} failed: {exc}")
            text = f"[tool result] {name} failed: {exc}"
        await self._deliver(name, text)

    async def _deliver(self, name: str, text: str) -> None:
        if self._notify is None:
            logger.warning(f"[Policy] No session to deliver {name}'s result to")
            return
        async with self._lock:  # one injected message at a time, in completion order
            try:
                await self._notify(text)
            except Exception as exc:  # the session may have closed meanwhile
                logger.warning(f"[Policy] Could not deliver {name}'s result: {exc}")

    async def wait(self) -> None:
        """Wait for everything in flight (tests, and graceful shutdown)."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def aclose(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)
        self._tasks.clear()


# ── Applying both


def apply_policy(
    pairs: Iterable[ToolPair],
    *,
    confirm: Iterable[str] = (),
    background: Iterable[str] = (),
    runner: Optional[BackgroundTools] = None,
) -> list[ToolPair]:
    """
    Wrap matching tools. Confirmation is the outer layer, so an unconfirmed call
    is refused before any background work starts.
    """
    confirm, background = list(confirm), list(background)
    if background and runner is None:
        raise ValueError("background tools need a BackgroundTools runner")
    out: list[ToolPair] = []
    for spec, handler in pairs:
        if matches(spec.name, background):
            spec, handler = runner.wrap(spec, handler)
        if matches(spec.name, confirm):
            spec, handler = require_confirmation(spec, handler)
        out.append((spec, handler))
    return out


def policy_instructions(
    pairs: Iterable[ToolPair], confirm: Iterable[str], background: Iterable[str]
) -> str:
    """The system-prompt conventions the active policy relies on, or "" when none apply."""
    names = [s.name for s, _ in pairs]
    parts = []
    if any(matches(n, confirm) for n in names):
        parts.append(CONFIRM_INSTRUCTIONS)
    if any(matches(n, background) for n in names):
        parts.append(BACKGROUND_INSTRUCTIONS)
    return "\n\n".join(parts)

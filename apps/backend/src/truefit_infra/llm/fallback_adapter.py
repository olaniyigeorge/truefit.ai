"""
FallbackLiveAdapter - transparent primary/fallback switching for live LLM sessions.

─────────────────────
WHAT THIS MODULE DOES
─────────────────────
Wraps two LiveSessionPort implementations (e.g. GeminiLiveAdapter + OpenAIRealtimeAdapter)
behind a single adapter that the rest of the system never has to think about.

When open_session() is called it tries the primary adapter first. If the primary
fails to open within the timeout window, it falls back to the secondary. Once a
session is open all subsequent method calls are delegated through to whichever
adapter is active - the agent layer, the interview connection, and the audio
bridge are completely unaware of which provider is running.

─────────────────
FAILURE DETECTION
─────────────────
"Failure" is defined broadly here: any exception raised during __aenter__ of the
primary's open_session() context manager, including:
  - Network errors (cannot reach the API)
  - Auth errors (bad API key)
  - Model-not-found errors
  - asyncio.TimeoutError if the session takes > _SESSION_OPEN_TIMEOUT seconds

We do NOT attempt mid-session recovery. If the primary session dies mid-interview
(connection drop, quota exceeded, server error), the exception propagates normally
up through the agent's run() and is treated as an interview error. Transparent
recovery mid-session would require replaying conversation state which is out of
scope here.

─────────────────────
HEALTH CHECK
─────────────────────
health_check() returns the current liveness of both configured adapters. It is
intended to be called from a background monitoring task or a /health endpoint,
not on the hot path. Use it to detect degraded primary before a session starts
and to inform alerting.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator, Optional

from src.truefit_core.application.ports import LiveSessionPort
from src.truefit_core.common.utils import logger


# How long (seconds) to wait for a session to open before treating it as
# a failure and trying the fallback. 10s is generous - a healthy Gemini or
# OpenAI session opens in under 2s. This guards against slow-network hangs.
_SESSION_OPEN_TIMEOUT = 10.0


def _require_active(active: Optional[LiveSessionPort]) -> None:
    """
    Guard called at the top of every delegating method.
    Raises RuntimeError with a clear message if called outside open_session().
    """
    if active is None:
        raise RuntimeError(
            "FallbackLiveAdapter: no active session. "
            "All calls must be made inside an open_session() context manager."
        )


# ───────────────────────
# SESSION CONTEXT MANAGER
# ───────────────────────

class _FallbackSessionContext:
    """
    Internal async context manager returned by FallbackLiveAdapter.open_session().

    __aenter__:
      1. Tries to open the primary adapter's session (with timeout).
      2. On any failure, logs a warning and tries the fallback adapter.
      3. If both fail, raises RuntimeError with both error messages.
      4. Returns the FallbackLiveAdapter itself so that `as session` in the
         caller's `async with` block gives them the FallbackLiveAdapter, and
         all subsequent send/receive calls route through it to the active adapter.

    __aexit__:
      Clears the active adapter reference, then delegates to whichever underlying
      CM was successfully entered. Any exception from CM teardown is logged but
      not re-raised - teardown errors shouldn't mask the original exception.
    """

    def __init__(
        self,
        *,
        owner: "FallbackLiveAdapter",
        system_prompt: str,
        tools: list,
    ) -> None:
        self._owner = owner
        self._system_prompt = system_prompt
        self._tools = tools
        self._active_cm = None  # the CM we entered, kept for __aexit__

    async def __aenter__(self) -> "FallbackLiveAdapter":
        primary_cm = self._owner._primary.open_session(
            self._system_prompt, self._tools
        )
        primary_exc: Optional[Exception] = None

        try:
            await asyncio.wait_for(primary_cm.__aenter__(), timeout=_SESSION_OPEN_TIMEOUT)
            self._active_cm = primary_cm
            self._owner._active = self._owner._primary
            logger.info(
                f"[FallbackAdapter] Primary ({type(self._owner._primary).__name__}) session opened"
            )
            return self._owner

        except Exception as exc:
            primary_exc = exc
            logger.warning(
                f"[FallbackAdapter] Primary ({type(self._owner._primary).__name__}) "
                f"failed to open: {exc!r}"
            )

        # Primary failed - try fallback
        if self._owner._fallback is None:
            logger.error("[FallbackAdapter] Primary failed and no fallback is configured")
            raise primary_exc

        logger.warning(
            f"[FallbackAdapter] Falling back to "
            f"{type(self._owner._fallback).__name__}"
        )

        fallback_cm = self._owner._fallback.open_session(
            self._system_prompt, self._tools
        )
        try:
            await asyncio.wait_for(fallback_cm.__aenter__(), timeout=_SESSION_OPEN_TIMEOUT)
            self._active_cm = fallback_cm
            self._owner._active = self._owner._fallback
            logger.warning(
                f"[FallbackAdapter] Using fallback "
                f"({type(self._owner._fallback).__name__}) — primary unavailable"
            )
            return self._owner

        except Exception as fallback_exc:
            logger.error(
                f"[FallbackAdapter] Both adapters failed. "
                f"Primary: {primary_exc!r} | Fallback: {fallback_exc!r}"
            )
            raise RuntimeError(
                f"All LLM adapters failed to open a session.\n"
                f"  Primary ({type(self._owner._primary).__name__}): {primary_exc}\n"
                f"  Fallback ({type(self._owner._fallback).__name__}): {fallback_exc}"
            ) from fallback_exc

    async def __aexit__(self, *exc_info: Any) -> None:
        self._owner._active = None
        if self._active_cm is not None:
            try:
                await self._active_cm.__aexit__(*exc_info)
            except Exception as teardown_exc:
                # Log but don't mask - if the body raised, that's the error we care about
                logger.warning(
                    f"[FallbackAdapter] Error during session CM teardown: {teardown_exc}"
                )


# ──────────────────────
# FALLBACK LIVE ADAPTER
# ──────────────────────

class FallbackLiveAdapter(LiveSessionPort):
    """
    A LiveSessionPort implementation that wraps a primary and optional fallback
    adapter and delegates all calls through to whichever one is active.

    Instantiated once per WebSocket connection by get_live_adapter() via the
    factory. Never reused across sessions.

    Usage is identical to using GeminiLiveAdapter or OpenAIRealtimeAdapter
    directly - the caller never needs to know this wrapper exists.

    async with adapter.open_session(prompt, tools=TOOLS) as session:
        # session IS this FallbackLiveAdapter, with _active pointing to
        # whichever underlying adapter successfully opened
        await session.send_client_content("context...")
        async for event_type, data in session.receive():
            ...
    """

    def __init__(
        self,
        *,
        primary: LiveSessionPort,
        fallback: Optional[LiveSessionPort] = None,
    ) -> None:
        """
        primary:  The preferred adapter. Tried first on every open_session() call.
        fallback: The backup adapter. Used only when primary fails to open.
                  Pass None to disable fallback (open_session will raise on primary failure).
        """
        self._primary = primary
        self._fallback = fallback
        # Set during open_session().__aenter__, cleared on __aexit__.
        # None outside of an active session - guards all delegating methods.
        self._active: Optional[LiveSessionPort] = None

    # ─────────────────────────────
    # LiveSessionPort: session open
    # ─────────────────────────────

    def open_session(
        self,
        system_prompt: str,
        tools: list | None = None,
    ) -> "_FallbackSessionContext":
        """
        Returns an async context manager that opens a session on the
        primary adapter (or falls back to secondary on failure).

        The `as session` variable in the caller's `async with` block will
        be this FallbackLiveAdapter instance, so all subsequent calls on
        `session` route through the delegating methods below.
        """
        return _FallbackSessionContext(
            owner=self,
            system_prompt=system_prompt,
            tools=tools or [],
        )

    async def connect(self, system_prompt: str) -> None:
        raise NotImplementedError(
            "Use FallbackLiveAdapter.open_session() context manager."
        )

    # ─────────────────────────────
    # LiveSessionPort: send methods
    # ─────────────────────────────

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """Forward 16kHz mono s16 PCM to whichever provider is active."""
        _require_active(self._active)
        await self._active.send_audio(pcm_bytes)

    async def send_audio_stream_end(self) -> None:
        """Signal end of audio stream (manual VAD mode)."""
        _require_active(self._active)
        await self._active.send_audio_stream_end()

    async def send_image(self, jpeg_bytes: bytes, source: str = "camera") -> None:
        """Forward a camera or screen-share JPEG frame."""
        _require_active(self._active)
        await self._active.send_image(jpeg_bytes, source)

    async def send_client_content(self, text: str) -> None:
        """Inject structured text context as a user turn (used for context injection at session start)."""
        _require_active(self._active)
        await self._active.send_client_content(text)

    async def send_tool_response(
        self, *, call_id: str, name: str, result: dict
    ) -> None:
        """
        Respond to a tool call. Unblocks the model so it can continue.
        Provider-specific wire format differences are handled inside each
        concrete adapter - the caller just passes the normalized args.
        """
        _require_active(self._active)
        await self._active.send_tool_response(call_id=call_id, name=name, result=result)

    # ──────────────────────────────
    # LiveSessionPort: receive stream
    # ──────────────────────────────

    async def receive(self) -> AsyncGenerator[tuple[str, Any], None]:
        """
        Yields normalized (event_type, data) tuples from whichever provider
        is active. Event types are identical regardless of provider:
          ("audio", bytes), ("text", str), ("input_text", str),
          ("tool_call", dict), ("turn_complete", None),
          ("interrupted", None), ("go_away", None)
        """
        _require_active(self._active)
        async for event in self._active.receive():
            yield event

    # ────────────────────────
    # LiveSessionPort: teardown
    # ────────────────────────

    async def close(self) -> None:
        """Clears the active adapter. Actual session close happens in __aexit__."""
        if self._active is not None:
            await self._active.close()
        self._active = None

    async def is_healthy(self) -> bool:
        """True if there is currently an active open session."""
        if self._active is not None:
            return await self._active.is_healthy()
        return False

    # ─────────────────────────────────────
    # EXTRA: health check (not on the port)
    # ─────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        """
        Returns the liveness status of both configured adapters.

        Intended for monitoring endpoints and background health probes,
        NOT for the interview hot path. Use this to detect a degraded
        primary before sessions are opened, and to drive alerting.

        Returns a dict like:
          {
            "primary":  {"provider": "GeminiLiveAdapter",      "session_open": False},
            "fallback": {"provider": "OpenAIRealtimeAdapter",  "session_open": False},
            "active_provider": None,   # or "GeminiLiveAdapter" during a live session
          }
        """
        primary_healthy = await self._primary.is_healthy()
        fallback_healthy = (
            await self._fallback.is_healthy()
            if self._fallback is not None
            else None
        )
        return {
            "primary": {
                "provider": type(self._primary).__name__,
                "session_open": primary_healthy,
            },
            "fallback": {
                "provider": type(self._fallback).__name__ if self._fallback else None,
                "session_open": fallback_healthy,
            },
            "active_provider": type(self._active).__name__ if self._active else None,
        }
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

Early failure is also recovered. If the primary opens but fails before it has
produced any event (bad request shape, auth or quota error reported on the first
receive, an immediate disconnect), the wrapper closes it, opens the fallback,
and replays the client content (the opening message) so the fallback starts the
conversation from the same point. Audio sent in that window is dropped.

We do NOT attempt recovery once the primary has produced output. If the session
dies mid-interview (connection drop, quota exceeded, server error), the exception
propagates normally up through the agent's run() and is treated as an interview
error. Recovering there would mean replaying the whole conversation, which is out
of scope.

─────────────────────
HEALTH CHECK
─────────────────────
health_check() returns the current liveness of both configured adapters. It is
intended to be called from a background monitoring task or a /health endpoint,
not on the hot path. Use it to detect degraded primary before a session starts
and to inform alerting.
"""

from __future__ import annotations

import logging

import asyncio
from typing import Any, AsyncGenerator, Optional

from soro.ports import AdapterCapabilities, LiveSessionPort
from soro.tools import ToolSpec


logger = logging.getLogger("soro.fallback")

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


def _merge_capabilities(
    primary: LiveSessionPort, fallback: Optional[LiveSessionPort]
) -> AdapterCapabilities:
    """
    Common denominator of the two adapters. Audio sample rates must match:
    the audio path is sized before a session opens, so a fallback that speaks
    a different rate would corrupt audio. Fail at construction instead.
    """
    p = primary.capabilities
    if fallback is None:
        return p
    f = fallback.capabilities
    if (p.input_sample_rate, p.output_sample_rate) != (
        f.input_sample_rate,
        f.output_sample_rate,
    ):
        raise ValueError(
            "Primary and fallback adapters use different audio sample rates "
            f"(primary in/out {p.input_sample_rate}/{p.output_sample_rate}, "
            f"fallback {f.input_sample_rate}/{f.output_sample_rate}). "
            "Pick providers with matching rates or resample inside one adapter."
        )
    if p.native_vad != f.native_vad:
        raise ValueError(
            "Primary and fallback adapters disagree on native_vad, so callers "
            "cannot know whether to signal turn boundaries."
        )
    return AdapterCapabilities(
        input_sample_rate=p.input_sample_rate,
        output_sample_rate=p.output_sample_rate,
        supports_images=p.supports_images and f.supports_images,
        native_vad=p.native_vad,
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
        tools: list[ToolSpec],
    ) -> None:
        self._owner = owner
        self._system_prompt = system_prompt
        self._tools = tools
        self._active_cm = None  # the CM we entered, kept for __aexit__
        self._failed_over = False

    async def __aenter__(self) -> "FallbackLiveAdapter":
        primary_cm = self._owner._primary.open_session(
            self._system_prompt, self._tools
        )
        primary_exc: Optional[Exception] = None

        try:
            await asyncio.wait_for(primary_cm.__aenter__(), timeout=_SESSION_OPEN_TIMEOUT)
            self._active_cm = primary_cm
            self._owner._active = self._owner._primary
            self._owner._session_ctx = self
            self._owner._sent_content = []
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
            self._owner._session_ctx = self
            self._owner._sent_content = []
            self._failed_over = True  # opened on the fallback already; nothing left to fail over to
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

    @property
    def can_fail_over(self) -> bool:
        return self._owner._fallback is not None and not self._failed_over

    async def fail_over(self) -> None:
        """
        Swap a session that failed early onto the fallback adapter: close the
        primary, open the fallback, replay the client content. Callers that send
        while this runs wait on owner._switching instead of hitting a dead session.
        """
        owner = self._owner
        if not self.can_fail_over:
            raise RuntimeError("FallbackLiveAdapter: no fallback available to fail over to")
        self._failed_over = True
        owner._switching.clear()
        try:
            failed = type(owner._active).__name__ if owner._active else "primary"
            if self._active_cm is not None:
                try:
                    await self._active_cm.__aexit__(None, None, None)
                except Exception as teardown_exc:
                    logger.warning(
                        f"[FallbackAdapter] Error closing failed primary: {teardown_exc}"
                    )
            fallback_cm = owner._fallback.open_session(self._system_prompt, self._tools)
            try:
                await asyncio.wait_for(
                    fallback_cm.__aenter__(), timeout=_SESSION_OPEN_TIMEOUT
                )
            except Exception as exc:
                self._active_cm = None
                owner._active = None
                raise RuntimeError(
                    f"Primary ({failed}) failed early and fallback "
                    f"({type(owner._fallback).__name__}) could not open: {exc}"
                ) from exc
            self._active_cm = fallback_cm
            owner._active = owner._fallback
            logger.warning(
                f"[FallbackAdapter] {failed} failed before producing output, "
                f"continuing on {type(owner._fallback).__name__}"
            )
            for text in owner._sent_content:
                await owner._fallback.send_client_content(text)
        finally:
            owner._switching.set()

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
        self._capabilities = _merge_capabilities(primary, fallback)
        # Set during open_session().__aenter__, cleared on __aexit__.
        # None outside of an active session - guards all delegating methods.
        self._active: Optional[LiveSessionPort] = None
        # Client content sent this session, replayed onto the fallback on early failover.
        self._sent_content: list[str] = []
        self._session_ctx: Optional[_FallbackSessionContext] = None
        # Cleared while an early failover swaps providers; senders wait on it.
        self._switching = asyncio.Event()
        self._switching.set()

    async def _current(self) -> LiveSessionPort:
        """The active adapter, waiting first if an early failover is swapping providers."""
        await self._switching.wait()
        _require_active(self._active)
        return self._active

    @property
    def capabilities(self) -> AdapterCapabilities:
        """
        Capabilities that hold whichever provider ends up active. Callers read
        this before a session opens (for example to size the audio path), so it
        is the common denominator of primary and fallback.
        """
        return self._capabilities

    # ─────────────────────────────
    # LiveSessionPort: session open
    # ─────────────────────────────

    def open_session(
        self,
        system_prompt: str,
        tools: list[ToolSpec] | None = None,
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
        active = await self._current()
        await active.send_audio(pcm_bytes)

    async def send_activity_start(self) -> None:
        """Manual turn signalling: forward to whichever provider is active."""
        active = await self._current()
        await active.send_activity_start()

    async def send_activity_end(self) -> None:
        """Manual turn signalling: forward to whichever provider is active."""
        active = await self._current()
        await active.send_activity_end()

    async def send_audio_stream_end(self) -> None:
        """Signal end of audio stream (manual VAD mode)."""
        active = await self._current()
        await active.send_audio_stream_end()

    async def send_image(self, jpeg_bytes: bytes, source: str = "camera") -> None:
        """Forward a camera or screen-share JPEG frame."""
        active = await self._current()
        await active.send_image(jpeg_bytes, source)

    async def send_client_content(self, text: str) -> None:
        """Inject structured text context as a user turn (used for context injection at session start)."""
        active = await self._current()
        self._sent_content.append(text)
        await active.send_client_content(text)

    async def send_tool_response(
        self, *, call_id: str, name: str, result: dict
    ) -> None:
        """
        Respond to a tool call. Unblocks the model so it can continue.
        Provider-specific wire format differences are handled inside each
        concrete adapter - the caller just passes the normalized args.
        """
        active = await self._current()
        await active.send_tool_response(call_id=call_id, name=name, result=result)

    # ──────────────────────────────
    # LiveSessionPort: receive stream
    # ──────────────────────────────

    async def receive(self) -> AsyncGenerator[tuple[str, Any], None]:
        """
        Yields normalized (event_type, data) tuples from whichever provider
        is active. Event types are identical regardless of provider:
          ("audio", bytes), ("text", str), ("input_text", str),
          ("tool_call", dict), ("turn_complete", None),
          ("interrupted", None), ("session_ending", dict | None)
        """
        active = await self._current()
        yielded = False
        try:
            async for event in active.receive():
                yielded = True
                yield event
            return
        except Exception as exc:
            ctx = self._session_ctx
            if yielded or ctx is None or not ctx.can_fail_over:
                raise
            logger.warning(
                f"[FallbackAdapter] {type(active).__name__} failed before producing "
                f"any output: {exc!r}"
            )
        # Early failure: move the session to the fallback and keep streaming.
        await ctx.fail_over()
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
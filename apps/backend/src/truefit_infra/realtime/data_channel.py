"""
DataChannelManager — bidirectional structured event channel.

Outbound (backend → frontend):
  agent_thinking, question_start, interview_ended, evaluation_scores, interrupt

Inbound (frontend → backend):
  clarification_request, screen_share_start, screen_share_stop, candidate_ready

All messages are newline-delimited JSON.
Domain logic must NOT live here — use on_inbound_event callback to dispatch upstream.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Awaitable, Callable, Optional

from aiortc.rtcdatachannel import RTCDataChannel

from src.truefit_core.common.utils import logger
from src.truefit_infra.realtime.session_context import SessionContext

# Type alias for inbound event handler
InboundHandler = Callable[[dict[str, Any]], Awaitable[None]]


class DataChannelManager:
    """
    Wraps an RTCDataChannel with typed send/receive helpers.

    Usage:
        # Attach the channel when aiortc fires the datachannel event
        manager.attach(channel)

        # Register handler for inbound events (wired up by your agent layer)
        manager.on_inbound_event = my_handler

        # Send outbound events
        await manager.send_event("question_start", {"question_id": "...", "number": 1})
    """

    # Known outbound event types (for documentation; not enforced at runtime)
    OUTBOUND_EVENTS = frozenset({
        "agent_thinking",
        "question_start",
        "question_end",
        "interview_ended",
        "evaluation_scores",
        "interrupt",
        "transcript",
        "error",
        "pong",
    })

    def __init__(self, *, context: SessionContext) -> None:
        self._ctx = context
        self._channel: Optional[RTCDataChannel] = None
        self._send_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
        self._sender_task: Optional[asyncio.Task] = None

        # Wire this up from outside (agent layer) to receive inbound events
        self.on_inbound_event: Optional[InboundHandler] = None

    # ── Attach ───

    def attach(self, channel: RTCDataChannel) -> None:
        """Called by WebRTCClient when the datachannel event fires."""
        self._channel = channel

        @channel.on("open")
        def on_open() -> None:
            logger.info(f"[{self._ctx.session_id}] DataChannel open: {channel.label}")
            self._sender_task = asyncio.create_task(
                self._sender_loop(),
                name=f"dc-sender-{self._ctx.session_id}",
            )

        @channel.on("message")
        def on_message(raw: str) -> None:
            asyncio.create_task(self._handle_inbound(raw))

        @channel.on("close")
        def on_close() -> None:
            logger.info(f"[{self._ctx.session_id}] DataChannel closed")
            if self._sender_task:
                self._sender_task.cancel()

    # ── Outbound ───

    async def send_event(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        """
        Enqueue an outbound event. Non-blocking — returns immediately.
        The sender loop drains the queue and writes to the DataChannel.
        """
        message = json.dumps({"type": event_type, **(payload or {})})
        try:
            self._send_queue.put_nowait(message)
        except asyncio.QueueFull:
            logger.warning(
                f"[{self._ctx.session_id}] DataChannel send queue full, dropping: {event_type}"
            )

    async def _sender_loop(self) -> None:
        """Drain the send queue and write to the channel."""
        try:
            while True:
                message = await self._send_queue.get()
                if self._channel and self._channel.readyState == "open":
                    self._channel.send(message)
                else:
                    logger.warning(
                        f"[{self._ctx.session_id}] DataChannel not open, dropping message"
                    )
        except asyncio.CancelledError:
            pass

    # ── Inbound ──

    async def _handle_inbound(self, raw: str) -> None:
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(f"[{self._ctx.session_id}] Bad DataChannel message: {raw!r}")
            return

        event_type = event.get("type", "unknown")
        logger.debug(f"[{self._ctx.session_id}] DataChannel inbound: {event_type}")

        # Built-in handling: ping/pong keepalive
        if event_type == "ping":
            await self.send_event("pong")
            return

        # Delegate everything else to the registered handler (agent layer)
        if self.on_inbound_event:
            try:
                await self.on_inbound_event(event)
            except Exception as e:
                logger.error(
                    f"[{self._ctx.session_id}] Inbound event handler error: {e}"
                )
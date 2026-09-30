"""
VoiceAgentRuntime - the two-loop engine behind every voice agent.

Owns the send loop (mic -> session), the receive loop (session events ->
callbacks / tool handlers), tool dispatch and lifecycle. It depends only on
LiveSessionPort; system prompt, tools, opening message and I/O callbacks are
all inputs. The interview agent is just the first consumer.

Turn-taking, VAD and audio transport stay outside: the runtime reports
"interrupted" and "turn_complete" through callbacks and the consumer decides
what to do (gate the mic, flush playback, ...).
"""

from __future__ import annotations

import logging

import asyncio
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable, Optional

from soro.runtime.registry import ToolRegistry
from soro.ports import LiveSessionPort

AsyncCallback = Callable[..., Awaitable[None]]


logger = logging.getLogger("soro.runtime")

class SessionComplete(Exception):
    """
    Raised (usually by a tool handler) to end the session normally.
    Not an error: run() catches it and returns.
    """

    def __init__(self, reason: str = "complete") -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class RuntimeCallbacks:
    """Consumer-side I/O. Only audio output is required."""

    on_audio_output: Callable[[bytes], Awaitable[None]]
    on_text_output: Optional[Callable[[str], Awaitable[None]]] = None
    on_input_text_output: Optional[Callable[[str], Awaitable[None]]] = None
    on_interrupt: Optional[Callable[[], Awaitable[None]]] = None
    on_turn_complete: Optional[Callable[[], Awaitable[None]]] = None


class VoiceAgentRuntime:
    """One runtime = one session. Do not reuse."""

    def __init__(
        self,
        *,
        adapter: LiveSessionPort,
        system_prompt: str,
        tools: ToolRegistry,
        audio_input_stream: AsyncIterator[bytes],
        callbacks: RuntimeCallbacks,
        opening_message: Optional[str] = None,
        resume_message: Optional[str] = None,
        on_error: Optional[Callable[[Exception], Awaitable[None]]] = None,
    ) -> None:
        """
        opening_message: sent as the first user turn once the session is open.
            Typically carries per-session context and triggers the greeting.
            None means the model waits for the user to speak first.
        resume_message: sent as a user turn when the adapter reports it reconnected
            ("session_resumed"). The provider keeps the conversation but the user's
            last turn may have been lost, so this is where the agent is told to
            recover. None means resumption is silent.
        on_error: awaited with the exception when the session dies unexpectedly
            (not on SessionComplete), before the exception is re-raised. Use it
            for cleanup such as marking a record abandoned.
        """
        self._adapter = adapter
        self._system_prompt = system_prompt
        self._tools = tools
        self._audio_input = audio_input_stream
        self._cb = callbacks
        self._opening_message = opening_message
        self._resume_message = resume_message
        self._on_error = on_error

        self._complete = asyncio.Event()
        self.end_reason: Optional[str] = None

    # ── Public

    def stop(self, reason: str = "stopped") -> None:
        """
        Ask both loops to exit at their next iteration. Handlers use this when
        the session should end but they still want to return a tool response.
        """
        if self.end_reason is None:
            self.end_reason = reason
        self._complete.set()

    @property
    def is_complete(self) -> bool:
        return self._complete.is_set()

    async def run(self) -> None:
        async with self._adapter.open_session(
            system_prompt=self._system_prompt,
            tools=self._tools.specs,
        ) as session:
            try:
                if self._opening_message is not None:
                    await session.send_client_content(text=self._opening_message)
                await self._run_loops(session)
            except SessionComplete as done:
                self.stop(done.reason)
                logger.info(f"[Runtime] Session complete: {done.reason}")
            except Exception as exc:
                logger.error(f"[Runtime] Session error: {exc}")
                if self._on_error:
                    await self._on_error(exc)
                raise

    # ── Loops

    async def _run_loops(self, session: LiveSessionPort) -> None:
        """
        Run both loops until either finishes, then cancel the other. If one
        loop ends (model closed the stream, mic closed, session completed) the
        other has nothing left to do and must not be left hanging.
        """
        tasks = [
            asyncio.create_task(self._send_audio_loop(session), name="runtime-send"),
            asyncio.create_task(self._receive_loop(session), name="runtime-receive"),
        ]
        try:
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        for t in pending:
            t.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for t in done:
            t.result()  # re-raise SessionComplete / real errors

    async def _send_audio_loop(self, session: LiveSessionPort) -> None:
        async for chunk in self._audio_input:
            if self._complete.is_set():
                break
            if chunk:  # the audio bridge can emit empty chunks during transitions
                await session.send_audio(chunk)
                await asyncio.sleep(0.001)  # yield so the receive loop is never starved

    async def _receive_loop(self, session: LiveSessionPort) -> None:
        async for event_type, data in session.receive():
            if self._complete.is_set():
                break

            match event_type:
                case "audio":
                    await self._cb.on_audio_output(data)
                case "text":
                    if self._cb.on_text_output:
                        await self._cb.on_text_output(data)
                case "input_text":
                    if self._cb.on_input_text_output:
                        await self._cb.on_input_text_output(data)
                case "interrupted":
                    if self._cb.on_interrupt:
                        await self._cb.on_interrupt()
                case "turn_complete":
                    if self._cb.on_turn_complete:
                        await self._cb.on_turn_complete()
                case "tool_call":
                    # The model blocks until it gets a response, so handling
                    # inline can't miss events.
                    result = await self._handle_tool_call(
                        name=data["name"], args=data["args"], call_id=data["id"]
                    )
                    await session.send_tool_response(
                        call_id=data["id"], name=data["name"], result=result
                    )
                case "session_resumed":
                    logger.warning(f"[Runtime] Provider session resumed: {data}")
                    # Audio queued from the dead connection is stale (a half-spoken
                    # sentence), so drop it before anything new plays.
                    if self._cb.on_interrupt:
                        await self._cb.on_interrupt()
                    # restarted=True means the adapter already replayed the opening
                    # content and the conversation begins again, so a "sorry, please
                    # repeat your last answer" nudge would contradict it.
                    restarted = bool((data or {}).get("restarted"))
                    if not restarted and self._resume_message is not None:
                        await session.send_client_content(text=self._resume_message)
                case "session_ending":
                    logger.warning(f"[Runtime] Provider is ending the session: {data}")
                    break

    async def _handle_tool_call(
        self, *, name: str, args: dict[str, Any], call_id: str
    ) -> dict[str, Any]:
        """
        SessionComplete propagates (normal end). Any other handler exception is
        returned to the model as an error result so it can recover.
        """
        logger.info(f"[Runtime] Tool {name} (call {call_id})")
        try:
            return await self._tools.dispatch(name, args)
        except SessionComplete:
            raise
        except Exception as exc:
            logger.error(f"[Runtime] Tool {name} failed: {exc}")
            return {"error": str(exc), "success": False}

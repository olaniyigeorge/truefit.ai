"""
ScriptedAdapter: a deterministic stand-in model for cheap, repeatable eval runs.

FakeLiveAdapter replays a fixed event list regardless of what it is sent, which
is right for unit tests but cannot show latency or barge-in. ScriptedAdapter
behaves like a realtime model instead:

- It waits for a user turn: a send_client_content() message, or audio followed
  by `end_of_turn_s` of silence (its own trivial end-of-turn detection).
- Then it plays the next scripted response after `response_delay_s`, pacing
  audio chunks in real time and blocking on each tool call until the runtime
  answers it, as real providers do.
- Audio arriving while it is responding is a barge-in: it stops, emits
  "interrupted", and treats that audio as the next user turn.

So the metrics measured against it are the harness's own overheads plus the
configured delays, which is what makes it a baseline for real providers.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, AsyncGenerator, Optional, Sequence

from soro.ports import AdapterCapabilities, LiveSessionPort

Event = tuple[str, Any]
_CLOSE = object()


class _Ctx:
    def __init__(self, owner: "ScriptedAdapter") -> None:
        self._owner = owner

    async def __aenter__(self) -> "ScriptedAdapter":
        await self._owner._start()
        return self._owner

    async def __aexit__(self, *exc_info) -> None:
        await self._owner.close()


class ScriptedAdapter(LiveSessionPort):
    def __init__(
        self,
        responses: Sequence[Sequence[Event]],
        *,
        response_delay_s: float = 0.05,
        audio_interval_s: float = 0.02,
        end_of_turn_s: float = 0.12,
        capabilities: Optional[AdapterCapabilities] = None,
    ) -> None:
        """
        responses: one event list per user turn, in order. Events use the port's
            vocabulary; "turn_complete" is appended when a response omits it.
        """
        self.responses = [list(r) for r in responses]
        self.response_delay_s = response_delay_s
        self.audio_interval_s = audio_interval_s
        self.end_of_turn_s = end_of_turn_s
        self._capabilities = capabilities or AdapterCapabilities()
        self.open_args: tuple | None = None
        self.tool_responses: list[dict] = []
        self.user_turns = 0
        self._queue: asyncio.Queue = asyncio.Queue()
        self._pending_tools: dict[str, asyncio.Future] = {}
        self._responder: Optional[asyncio.Task] = None
        self._watcher: Optional[asyncio.Task] = None
        self._spoke = False
        self._heard_audio = False
        self._last_audio = 0.0
        self._next = 0
        self._open = False

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    # ── Lifecycle

    def open_session(self, system_prompt: str, tools: list | None = None) -> Any:
        self.open_args = (system_prompt, tools)
        return _Ctx(self)

    async def _start(self) -> None:
        self._open = True
        self._watcher = asyncio.create_task(self._watch_silence(), name="scripted-eot")

    async def close(self) -> None:
        if not self._open:
            return
        self._open = False
        for task in (self._responder, self._watcher):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(t for t in (self._responder, self._watcher) if t), return_exceptions=True
        )
        self._queue.put_nowait(_CLOSE)

    async def is_healthy(self) -> bool:
        return self._open

    # ── Input

    async def send_audio(self, pcm_bytes: bytes) -> None:
        if self._responding():
            await self._interrupt()
        self._heard_audio = True
        self._last_audio = time.monotonic()

    async def send_client_content(self, text: str) -> None:
        if self._responding():
            await self._interrupt()
        self._user_turn_ended()

    async def send_tool_response(self, *, call_id: str, name: str, result: dict) -> None:
        self.tool_responses.append({"call_id": call_id, "name": name, "result": result})
        future = self._pending_tools.pop(call_id, None)
        if future is not None and not future.done():
            future.set_result(result)

    # ── Output

    async def receive(self) -> AsyncGenerator[tuple[str, Any], None]:
        while True:
            item = await self._queue.get()
            if item is _CLOSE:
                return
            yield item

    # ── Internals

    def _responding(self) -> bool:
        return self._responder is not None and not self._responder.done()

    async def _interrupt(self) -> None:
        self._responder.cancel()
        await asyncio.gather(self._responder, return_exceptions=True)
        if self._spoke:
            await self._queue.put(("interrupted", None))
        self._spoke = False

    def _user_turn_ended(self) -> None:
        self.user_turns += 1
        self._heard_audio = False
        if self._next >= len(self.responses):
            return  # script exhausted: stay silent, like a model with nothing to add
        events = self.responses[self._next]
        self._next += 1
        self._responder = asyncio.create_task(self._respond(events), name="scripted-response")

    async def _watch_silence(self) -> None:
        while True:
            await asyncio.sleep(0.01)
            if self._heard_audio and time.monotonic() - self._last_audio >= self.end_of_turn_s:
                self._user_turn_ended()

    async def _respond(self, events: list[Event]) -> None:
        await asyncio.sleep(self.response_delay_s)
        for kind, data in events:
            if kind == "audio":
                self._spoke = True
                await self._queue.put((kind, data))
                await asyncio.sleep(self.audio_interval_s)
            elif kind == "tool_call":
                future = asyncio.get_running_loop().create_future()
                self._pending_tools[data["id"]] = future
                await self._queue.put((kind, data))
                await future
            else:
                await self._queue.put((kind, data))
        if not events or events[-1][0] != "turn_complete":
            await self._queue.put(("turn_complete", None))
        self._spoke = False


def speech(seconds: float, rate: int = 24_000, chunk_ms: int = 20) -> list[Event]:
    """Scripted agent audio: `seconds` of silent PCM chunks at the output rate."""
    chunk = b"\x00\x00" * (rate * chunk_ms // 1000)
    return [("audio", chunk) for _ in range(max(1, round(seconds * 1000 / chunk_ms)))]

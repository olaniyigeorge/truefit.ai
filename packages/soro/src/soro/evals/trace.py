"""
A timestamped record of one session, captured by wrapping the adapter.

TracingAdapter sits between the runtime and any LiveSessionPort and notes every
event in both directions, so the metrics are computed the same way whichever
provider ran: they read the trace, never the provider.

Times are seconds since the session opened (time.monotonic based).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, AsyncGenerator, Callable, Optional

from soro.ports import AdapterCapabilities, LiveSessionPort


@dataclass(frozen=True)
class TraceEvent:
    t: float
    direction: str  # "in" (model to agent), "out" (agent to model), "mark" (the runner's notes)
    kind: str
    data: Any = None
    i: int = 0  # position in the trace, the tie-free ordering


class Trace:
    def __init__(self) -> None:
        self.events: list[TraceEvent] = []
        self._t0: Optional[float] = None
        self._changed = asyncio.Condition()

    def start(self) -> None:
        self._t0 = time.monotonic()

    def now(self) -> float:
        return 0.0 if self._t0 is None else time.monotonic() - self._t0

    async def add(self, direction: str, kind: str, data: Any = None) -> TraceEvent:
        event = TraceEvent(round(self.now(), 4), direction, kind, data, len(self.events))
        self.events.append(event)
        async with self._changed:
            self._changed.notify_all()
        return event

    def select(
        self, direction: str | None = None, kind: str | None = None, since: int = 0
    ) -> list[TraceEvent]:
        """
        Events matching direction/kind from index `since` on. Ordering is by index,
        not time: two events can share a rounded timestamp but never a position.
        """
        return [
            e
            for e in self.events[since:]
            if (direction is None or e.direction == direction) and (kind is None or e.kind == kind)
        ]

    def first(self, direction: str, kind: str, since: int = 0) -> Optional[TraceEvent]:
        found = self.select(direction, kind, since)
        return found[0] if found else None

    async def wait_for(self, predicate: Callable[[], bool], timeout: float) -> bool:
        """Wait until predicate() is true, re-checking on every new event. False on timeout."""

        async def until() -> None:
            async with self._changed:
                await self._changed.wait_for(predicate)

        try:
            await asyncio.wait_for(until(), timeout)
            return True
        except asyncio.TimeoutError:
            return False


def _summarise(kind: str, data: Any) -> Any:
    # Keep sizes, not payloads: a trace of raw PCM would be megabytes.
    if kind == "audio" and isinstance(data, (bytes, bytearray)):
        return len(data)
    return data


class _Ctx:
    def __init__(self, owner: "TracingAdapter", inner_ctx: Any) -> None:
        self._owner = owner
        self._inner = inner_ctx

    async def __aenter__(self) -> "TracingAdapter":
        self._owner.trace.start()
        await self._inner.__aenter__()
        await self._owner.trace.add("mark", "session_open")
        return self._owner

    async def __aexit__(self, *exc_info) -> Any:
        await self._owner.trace.add("mark", "session_close")
        return await self._inner.__aexit__(*exc_info)


class TracingAdapter(LiveSessionPort):
    """Forwards everything to `inner` and records it in `trace`."""

    def __init__(self, inner: LiveSessionPort, trace: Optional[Trace] = None) -> None:
        self.inner = inner
        self.trace = trace or Trace()

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self.inner.capabilities

    def open_session(self, system_prompt: str, tools: list | None = None) -> Any:
        return _Ctx(self, self.inner.open_session(system_prompt=system_prompt, tools=tools))

    async def close(self) -> None:
        await self.inner.close()

    async def send_audio(self, pcm_bytes: bytes) -> None:
        await self.trace.add("out", "audio", len(pcm_bytes))
        await self.inner.send_audio(pcm_bytes)

    async def send_activity_start(self) -> None:
        await self.trace.add("out", "activity_start")
        await self.inner.send_activity_start()

    async def send_activity_end(self) -> None:
        await self.trace.add("out", "activity_end")
        await self.inner.send_activity_end()

    async def send_audio_stream_end(self) -> None:
        await self.inner.send_audio_stream_end()

    async def send_image(self, jpeg_bytes: bytes, source: str = "camera") -> None:
        await self.inner.send_image(jpeg_bytes, source)

    async def send_client_content(self, text: str) -> None:
        await self.trace.add("out", "content", text)
        await self.inner.send_client_content(text=text)

    async def send_tool_response(self, *, call_id: str, name: str, result: dict) -> None:
        await self.trace.add(
            "out", "tool_response", {"id": call_id, "name": name, "result": result}
        )
        await self.inner.send_tool_response(call_id=call_id, name=name, result=result)

    async def receive(self) -> AsyncGenerator[tuple[str, Any], None]:
        async for kind, data in self.inner.receive():
            await self.trace.add("in", kind, _summarise(kind, data))
            yield kind, data

    async def is_healthy(self) -> bool:
        return await self.inner.is_healthy()

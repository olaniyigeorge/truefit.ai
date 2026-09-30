"""
Test doubles for code built on Soro.

FakeLiveAdapter is an in-memory LiveSessionPort. Script the events it should emit
and it records everything your agent sends, so agents can be tested with no
network, provider or API key.

    adapter = FakeLiveAdapter(events=[("audio", b"..."), ("turn_complete", None)])
    async with adapter.open_session("prompt") as session:
        ...
    assert adapter.tool_responses == [...]

An Exception placed in `events` is raised at that point in the stream.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator

from soro.ports import AdapterCapabilities, LiveSessionPort


class _Ctx:
    def __init__(self, owner: "FakeLiveAdapter") -> None:
        self._owner = owner

    async def __aenter__(self):
        if self._owner.fail_open is not None:
            raise self._owner.fail_open
        self._owner.opened = True
        return self._owner

    async def __aexit__(self, *exc_info) -> None:
        self._owner.opened = False
        self._owner.closed_count += 1


class FakeLiveAdapter(LiveSessionPort):
    def __init__(
        self,
        events=(),
        fail_open: Exception | None = None,
        hold_open_until_audio: int = 0,
        capabilities: AdapterCapabilities | None = None,
    ) -> None:
        """hold_open_until_audio: keep receive() open until that many audio chunks were sent."""
        self.events = list(events)
        self._capabilities = capabilities or AdapterCapabilities()
        self.activity: list[str] = []
        self.hold_open_until_audio = hold_open_until_audio
        self.fail_open = fail_open
        self.opened = False
        self.closed_count = 0
        self.audio: list[bytes] = []
        self.content: list[str] = []
        self.tool_responses: list[dict] = []
        self.open_args: tuple | None = None

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def send_activity_start(self) -> None:
        self.activity.append("start")

    async def send_activity_end(self) -> None:
        self.activity.append("end")

    def open_session(self, system_prompt: str, tools: list | None = None):
        self.open_args = (system_prompt, tools)
        return _Ctx(self)

    async def close(self) -> None:
        self.opened = False

    async def send_audio(self, pcm_bytes: bytes) -> None:
        self.audio.append(pcm_bytes)

    async def send_image(self, jpeg_bytes: bytes, source: str = "camera") -> None:
        if not self._capabilities.supports_images:
            await super().send_image(jpeg_bytes, source)

    async def send_client_content(self, text: str) -> None:
        self.content.append(text)

    async def send_tool_response(self, *, call_id: str, name: str, result: dict) -> None:
        self.tool_responses.append({"call_id": call_id, "name": name, "result": result})

    async def receive(self) -> AsyncGenerator[tuple[str, Any], None]:
        for event in self.events:
            if isinstance(event, Exception):  # lets a test fail the stream at a chosen point
                raise event
            yield event
        while len(self.audio) < self.hold_open_until_audio:
            await asyncio.sleep(0.005)

    async def is_healthy(self) -> bool:
        return self.opened

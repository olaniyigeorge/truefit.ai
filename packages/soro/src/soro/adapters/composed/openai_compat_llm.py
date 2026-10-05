"""
LanguageModel over any OpenAI-compatible chat completions endpoint.

Ollama, llama.cpp's server, vLLM and LM Studio all expose /v1/chat/completions
with streaming and tool calls, so one client covers the local options. No key
is needed for a local server; pass api_key for a hosted one.

    OpenAICompatibleLLM(base_url="http://localhost:11434/v1", model="llama3.2")  # Ollama

Tool support depends on the model: pick one trained for function calling
(llama3.1+, qwen2.5, mistral-nemo, ...) or tool calls will come back as text.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Optional

from soro.adapters.composed.components import LLMChunk, TextDelta, ToolCallRequest
from soro.tools import ToolSpec


def _httpx():
    try:
        import httpx
    except ImportError as exc:
        raise ImportError(
            'The composed adapter\'s LLM client needs httpx. Install it with: pip install "soro[composed]"'
        ) from exc
    return httpx


def to_chat_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"type": "function", "function": {"name": s.name, "description": s.description, "parameters": s.parameters}}
        for s in specs
    ]


class OpenAICompatibleLLM:
    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434/v1",
        model: str = "llama3.2",
        api_key: Optional[str] = None,
        temperature: float = 0.6,
        timeout: float = 60.0,
        transport: Any = None,
    ) -> None:
        """transport: an httpx transport, for tests (httpx.MockTransport)."""
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self._transport = transport
        self._client = None

    def _http(self):
        if self._client is None:
            httpx = _httpx()
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            self._client = httpx.AsyncClient(headers=headers, timeout=self.timeout, transport=self._transport)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def stream(self, messages: list[dict[str, Any]], tools: list[ToolSpec]) -> AsyncIterator[LLMChunk]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "temperature": self.temperature,
        }
        if tools:
            body["tools"] = to_chat_tools(tools)

        # Tool calls stream as fragments keyed by index: the id and name arrive
        # first, the JSON arguments in pieces. Assemble, then yield each whole.
        pending: dict[int, dict[str, Any]] = {}
        async with self._http().stream("POST", f"{self.base_url}/chat/completions", json=body) as resp:
            if resp.status_code >= 400:
                detail = (await resp.aread()).decode(errors="replace")[:500]
                raise RuntimeError(f"LLM server returned {resp.status_code}: {detail}")
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                event = json.loads(data)
                for choice in event.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        yield TextDelta(delta["content"])
                    for position, fragment in enumerate(delta.get("tool_calls") or []):
                        slot = pending.setdefault(fragment.get("index", position), {"id": None, "name": "", "args": ""})
                        slot["id"] = fragment.get("id") or slot["id"]
                        fn = fragment.get("function") or {}
                        slot["name"] += fn.get("name") or ""
                        args = fn.get("arguments")
                        # Some servers send arguments as an object rather than a JSON string.
                        slot["args"] += json.dumps(args) if isinstance(args, dict) else (args or "")

        for index in sorted(pending):
            slot = pending[index]
            yield ToolCallRequest(id=slot["id"] or f"call_{index}", name=slot["name"], args=_parse_args(slot["args"]))


def _parse_args(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        # Small local models sometimes emit broken JSON. Hand the raw text through
        # so the tool can return a useful error rather than the session failing.
        return {"_raw_arguments": raw}
    return value if isinstance(value, dict) else {"value": value}

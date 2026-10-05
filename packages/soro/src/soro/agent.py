"""
Agent: a prompt, some connectors and a policy, run on any realtime model.

The facade most people should start with. It does the wiring that every
VoiceAgentRuntime consumer otherwise repeats: collect tools from connectors,
apply the voice response policy, extend the prompt with the conventions that
policy relies on, open and close the connectors around the session.

    agent = soro.Agent(
        prompt="You are my assistant. You can read my notes and manage my calendar.",
        connectors=[soro.connectors.openapi("https://my-os.example/openapi.json"),
                    soro.connectors.mcp("python calendar_server.py")],
        confirm=["schedule_meet", "delete_*"],
        background=["search_*"],
        provider="gemini",
    )
    await agent.run(audio_input_stream=mic(), on_audio_output=play)

One Agent can run many sessions (one at a time per run() call); each run builds a
fresh runtime and reconnects its connectors. Drop down to VoiceAgentRuntime when
you need control the facade does not give.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncIterator, Awaitable, Callable, Iterable, Optional

from soro.connectors.base import Connector, ToolPair, registry_from_pairs
from soro.connectors.functions import functions as functions_connector
from soro.ports import LiveSessionPort
from soro.runtime.policy import BackgroundTools, apply_policy, policy_instructions
from soro.runtime.runtime import RuntimeCallbacks, VoiceAgentRuntime

logger = logging.getLogger("soro.agent")


class Agent:
    def __init__(
        self,
        *,
        prompt: str,
        connectors: Iterable[Connector] = (),
        tools: Iterable[Callable] = (),
        confirm: Iterable[str] = (),
        background: Iterable[str] = (),
        adapter: Optional[LiveSessionPort] = None,
        provider: Optional[str] = None,
        fallback: Optional[str] = None,
        opening_message: Optional[str] = None,
        resume_message: Optional[str] = None,
        **provider_options: Any,
    ) -> None:
        """
        prompt: the system prompt. Policy conventions are appended to it.
        connectors: where tools come from (functions, openapi, mcp, your own).
        tools: shorthand for connectors.functions(*tools).
        confirm / background: fnmatch patterns over tool names, see runtime.policy.
        adapter: a ready LiveSessionPort. Otherwise one is built per run with
            create_live_adapter(provider, fallback, **provider_options).
        opening_message / resume_message: as for VoiceAgentRuntime.
        """
        if adapter is not None and (provider or fallback or provider_options):
            raise ValueError("Pass either adapter= or provider= options, not both")
        self.prompt = prompt
        self.connectors: list[Connector] = list(connectors)
        tools = list(tools)
        if tools:
            self.connectors.append(functions_connector(*tools))
        self.confirm = list(confirm)
        self.background = list(background)
        self._adapter = adapter
        self._provider = provider
        self._fallback = fallback
        self._provider_options = provider_options
        self.opening_message = opening_message
        self.resume_message = resume_message
        self.runtime: Optional[VoiceAgentRuntime] = None

    def _build_adapter(self) -> LiveSessionPort:
        if self._adapter is not None:
            return self._adapter
        from soro.adapters.factory import create_live_adapter

        return create_live_adapter(self._provider, self._fallback, **self._provider_options)

    async def tools(self) -> list[ToolPair]:
        """
        Every tool the agent would expose, policy applied, without opening a
        session. Connectors are opened and closed again: use it to inspect what a
        spec or server turns into.
        """
        try:
            pairs = await self._collect()
            return apply_policy(pairs, confirm=self.confirm, background=self.background,
                                runner=BackgroundTools())
        finally:
            await self._close_connectors()

    async def run(
        self,
        *,
        audio_input_stream: AsyncIterator[bytes],
        on_audio_output: Callable[[bytes], Awaitable[None]],
        on_text_output: Optional[Callable[[str], Awaitable[None]]] = None,
        on_input_text_output: Optional[Callable[[str], Awaitable[None]]] = None,
        on_interrupt: Optional[Callable[[], Awaitable[None]]] = None,
        on_turn_complete: Optional[Callable[[], Awaitable[None]]] = None,
        on_error: Optional[Callable[[Exception], Awaitable[None]]] = None,
    ) -> Optional[str]:
        """Run one session to completion. Returns the end reason, if a tool or stop() gave one."""
        adapter = self._build_adapter()
        background = BackgroundTools()
        try:
            pairs = apply_policy(
                await self._collect(), confirm=self.confirm,
                background=self.background, runner=background,
            )
            prompt = self.prompt
            extra = policy_instructions(pairs, self.confirm, self.background)
            if extra:
                prompt = f"{prompt}\n\n{extra}"
            # open_session yields the adapter itself, so results can be injected
            # through it once the session is open (and fail softly once it is not).
            background.attach(lambda text: adapter.send_client_content(text=text))
            self.runtime = VoiceAgentRuntime(
                adapter=adapter,
                system_prompt=prompt,
                tools=registry_from_pairs(pairs),
                audio_input_stream=audio_input_stream,
                callbacks=RuntimeCallbacks(
                    on_audio_output=on_audio_output,
                    on_text_output=on_text_output,
                    on_input_text_output=on_input_text_output,
                    on_interrupt=on_interrupt,
                    on_turn_complete=on_turn_complete,
                ),
                opening_message=self.opening_message,
                resume_message=self.resume_message,
                on_error=on_error,
            )
            await self.runtime.run()
            return self.runtime.end_reason
        finally:
            await background.aclose()
            await self._close_connectors()

    def stop(self, reason: str = "stopped") -> None:
        """End the running session from outside (a hang-up button, a timeout)."""
        if self.runtime is not None:
            self.runtime.stop(reason)

    async def _collect(self) -> list[ToolPair]:
        pairs: list[ToolPair] = []
        for connector in self.connectors:
            pairs.extend(await connector.tools())
        return pairs

    async def _close_connectors(self) -> None:
        # Close every connector even if one fails. A failed close is logged, not
        # raised: it must not mask the session's own outcome or error.
        for connector in reversed(self.connectors):
            try:
                await connector.aclose()
            except Exception as exc:
                logger.warning(f"[Agent] Closing {type(connector).__name__} failed: {exc}")

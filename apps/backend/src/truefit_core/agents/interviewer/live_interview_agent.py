"""
LiveInterviewAgent - the interview consumer of VoiceAgentRuntime.

All the generic machinery (send/receive loops, event routing, tool dispatch,
lifecycle) lives in truefit_core.agents.runtime. This class only supplies what
is interview-specific: the system prompt, the interview tools and their
handlers, the opening message that carries the interview context, and the
"abandon the interview if the session dies" policy.

One agent = one interview. Do not reuse across sessions.
"""

from __future__ import annotations

import json
from typing import AsyncIterator, Callable, Coroutine, Optional

from src.truefit_core.agents.interviewer.context import InterviewContext
from src.truefit_core.agents.interviewer.handlers import (
    INTERRUPT_CACHE_TTL,  # noqa: F401  (re-exported for existing importers)
    InterviewCompleteSignal,  # noqa: F401  (re-exported for existing importers)
    InterviewToolHandlers,
)
from src.truefit_core.agents.interviewer.prompts import build_system_prompt
from src.truefit_core.agents.interviewer.tools import INTERVIEW_TOOLS
from src.truefit_core.agents.runtime import (
    RuntimeCallbacks,
    ToolRegistry,
    VoiceAgentRuntime,
)
from src.truefit_core.application.ports import CachePort, LiveSessionPort, QueuePort
from src.truefit_core.application.services.interview_orchestration import (
    InterviewOrchestrationService,
)
from src.truefit_core.common.utils import logger


class LiveInterviewAgent:
    def __init__(
        self,
        *,
        live_adapter: LiveSessionPort,
        orchestration: InterviewOrchestrationService,
        queue: QueuePort,
        cache: CachePort,
        audio_input_stream: AsyncIterator[bytes],
        on_audio_output: Callable[[bytes], Coroutine],
        on_text_output: Optional[Callable[[str], Coroutine]] = None,
        on_input_text_output: Optional[Callable[[str], Coroutine]] = None,
        on_interrupt: Optional[Callable[[], Coroutine]] = None,
        on_turn_complete: Optional[Callable[[], Coroutine]] = None,
    ) -> None:
        """
        live_adapter:       any LiveSessionPort (Gemini, OpenAI, fallback wrapper, ...).
        orchestration:      persists questions, answers and state transitions.
        queue / cache:      domain events and interrupt signals.
        audio_input_stream: 16kHz mono s16 PCM from the browser mic.
        on_*:               I/O callbacks, see RuntimeCallbacks.
        """
        self._adapter = live_adapter
        self._orchestration = orchestration
        self._queue = queue
        self._cache = cache
        self._audio_input = audio_input_stream
        self._callbacks = RuntimeCallbacks(
            on_audio_output=on_audio_output,
            on_text_output=on_text_output,
            on_input_text_output=on_input_text_output,
            on_interrupt=on_interrupt,
            on_turn_complete=on_turn_complete,
        )
        self.runtime: Optional[VoiceAgentRuntime] = None
        self.handlers: Optional[InterviewToolHandlers] = None

    async def run(self, context: InterviewContext) -> None:
        """
        Runs the interview to completion. Normal completion returns; any
        unexpected error marks the interview abandoned and is re-raised.
        """
        # The handlers need runtime.stop and the runtime needs the handlers, so
        # stop goes through a late-bound lambda.
        self.handlers = InterviewToolHandlers(
            interview_id=context.interview_id,
            orchestration=self._orchestration,
            queue=self._queue,
            cache=self._cache,
            stop_session=lambda reason: self.runtime.stop(reason),
        )
        self.runtime = VoiceAgentRuntime(
            adapter=self._adapter,
            system_prompt=build_system_prompt(context),
            tools=ToolRegistry.from_declarations(INTERVIEW_TOOLS, self.handlers.as_map()),
            audio_input_stream=self._audio_input,
            callbacks=self._callbacks,
            opening_message=self._opening_message(context),
            on_error=lambda exc: self._orchestration.abandon_interview(
                context.interview_id, reason="agent_error"
            ),
        )
        logger.info(f"[Agent] Starting interview {context.interview_id}")
        await self.runtime.run()
        logger.info(
            f"[Agent] Interview {context.interview_id} ended: {self.runtime.end_reason}"
        )

    @staticmethod
    def _opening_message(ctx: InterviewContext) -> str:
        """
        Per-interview data, sent as the first user turn (the system prompt holds
        the persona and rules). Ending with the greeting instruction makes the
        model speak first.
        """
        context_json = json.dumps(
            {
                "interview_id": str(ctx.interview_id),
                "job_title": ctx.job_title,
                "required_skills": ctx.required_skills,
                "max_questions": ctx.max_questions,
                "topics": ctx.topics,
            },
            indent=2,
        )
        return (
            f"Interview session is starting now.\n"
            f"Context: {context_json}\n\n"
            f"Please greet {ctx.candidate_name} warmly and ask your first question."
        )

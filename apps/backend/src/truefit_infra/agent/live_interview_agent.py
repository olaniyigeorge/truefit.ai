from __future__ import annotations

import asyncio
import json
import random
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Coroutine, Optional

from src.truefit_core.application.services.interview_orchestration import (
    InterviewOrchestrationService,
)
from src.truefit_core.application.ports import CachePort, DomainEvent, QueuePort
from src.truefit_core.common.utils import logger
from src.truefit_core.agents.interviewer.context import InterviewContext
from src.truefit_core.agents.interviewer.prompts import build_system_prompt
from src.truefit_core.agents.interviewer.tools import INTERVIEW_TOOLS
from src.truefit_infra.llm.gemini_live import GeminiLiveAdapter
from src.truefit_infra.realtime.audio_bridge import SILENCE_CHUNK

# ─────────
# CONSTANTS
# ─────────

# How long (seconds) an interrupt signal survives in Redis before auto-expiring.
# In practice the interrupt monitor reads and deletes it within ~50ms -
# the 30s TTL is purely a safety net so stale signals don't persist across
# server restarts or missed deletes.
INTERRUPT_CACHE_TTL = 30


def _utcnow_iso() -> str:
    """
    Returns the current UTC time as an ISO 8601 string.
    Used for 'occurred_at' timestamps on every DomainEvent we publish,
    so downstream consumers always have a consistent, timezone-aware timestamp.
    """
    return datetime.now(timezone.utc).isoformat()


# ────────────────────
# LIVE INTERVIEW AGENT
# ────────────────────
# This is the "brain" of a live interview session. It sits between Gemini
# (via GeminiLiveAdapter) and the rest of the system (orchestration, cache,
# queue) and drives the interview from the first greeting through to completion.
#
# WHAT IT KNOWS ABOUT:
#   - GeminiLiveAdapter       -> the AI it's having a real-time session with
#   - InterviewOrchestrationService -> domain logic: questions, answers, state
#   - CachePort               -> write interrupt signals for the WS layer to pick up
#   - QueuePort               -> publish domain events (interview.completed, etc.)
#   - A set of I/O callbacks  -> the ONLY coupling point back to InterviewConnection
#
# WHAT IT DOES NOT KNOW ABOUT:
#   - WebSockets              -> it calls on_text_output(), not ws.send_text()
#   - WebRTC / AudioBridge    -> it calls on_audio_output(), not bridge.push_audio()
#   - HTTP / FastAPI          -> completely unaware of the transport layer
#
# WHY CALLBACKS INSTEAD OF DIRECT REFERENCES?
#   This keeps the agent independently testable. In tests we can pass mock
#   callbacks without spinning up WebSockets or WebRTC. In production,
#   InterviewConnection passes its own methods as callbacks so the agent can
#   push data back without importing the WS layer.
#
# CONCURRENCY MODEL:
#   run() opens a Gemini session then gather()s exactly two coroutines:
#     _send_audio_loop  - pulls PCM from audio_input_stream, pushes to Gemini
#     _receive_loop     - pulls events from Gemini, dispatches to handlers
#
#   These two loops run simultaneously for the full interview. Tool calls
#   are handled synchronously inside _receive_loop (blocking until we have
#   a response) because Gemini blocks its own output until it gets one.


class LiveInterviewAgent:
    """
    Drives a single live AI interview session end-to-end.

    Instantiated once per interview by InterviewConnection.run() after the
    WebRTC peer connection is established. It:
      1. Opens a Gemini Live session (via adapter.open_session())
      2. Injects job + candidate context as the first user turn
      3. Runs two concurrent loops (send audio, receive events) until done
      4. Raises InterviewCompleteSignal when the interview ends naturally

    One agent = one interview. Do not reuse across sessions.
    """

    def __init__(
        self,
        *,
        live_adapter: GeminiLiveAdapter,
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
        All dependencies are constructor-injected - the agent never imports
        or instantiates infrastructure directly.

        live_adapter:
            The GeminiLiveAdapter. Used to open the session, send audio,
            and receive the event stream. The ONLY way to talk to Gemini.

        orchestration:
            The InterviewOrchestrationService. Called from tool handlers to
            persist questions, answers, and state transitions to the DB.

        queue:
            Publishes domain events (interview.agent_ending, interview.interrupted)
            for downstream consumers like the evaluation pipeline.

        cache:
            Writes interrupt signals to Redis so the interrupt monitor loop
            in InterviewConnection can forward them to the frontend within ~50ms.

        audio_input_stream:
            Async generator of 16kHz mono s16 PCM chunks from the browser mic.
            Provided by InterviewConnection via AudioBridge.audio_input_stream().
            The agent iterates this and forwards chunks to Gemini.

        on_audio_output:
            Called for every 24kHz PCM audio chunk Gemini sends back.
            In production: InterviewConnection._on_audio_output()
            -> pushes to AudioBridge.outbound_queue -> WebRTC track -> browser speaker.

        on_text_output:
            Called when Gemini emits a complete agent speech transcript (what the
            AI interviewer said). Forwarded to the frontend as captions.

        on_input_text_output:
            Called when Gemini transcribes what the candidate said.
            Forwarded to the frontend as candidate captions.

        on_interrupt:
            Called when Gemini signals the agent was interrupted mid-speech.
            In production: clears the audio queue and suppresses output briefly.

        on_turn_complete:
            Called when Gemini signals the agent finished its response turn.
            In production: drains remaining audio, resets the resampler,
            then opens the mic so the candidate can speak.
        """
        self._adapter = live_adapter
        self._orchestration = orchestration
        self._queue = queue
        self._cache = cache
        self._audio_input = audio_input_stream
        self._on_audio_output = on_audio_output
        self._on_text_output = on_text_output
        self._on_interrupt = on_interrupt
        self._on_input_text_output = on_input_text_output
        self._on_turn_complete = on_turn_complete

        # Tracks the most recently recorded question so persist_answer can
        # reference it without Gemini needing to echo the question_id back.
        # Set by _tool_record_question, read by _tool_persist_answer.
        self._current_question_id: Optional[uuid.UUID] = None

        # Set in run() from context - needed by all tool handlers for DB calls
        # and cache keys. None until run() is called.
        self._interview_id: Optional[uuid.UUID] = None

        # Set by _tool_complete_interview to signal both loops to exit cleanly
        # on the next iteration. Using an Event (not a boolean) because
        # asyncio.Event is safe to check/set from concurrent coroutines.
        self._session_complete = asyncio.Event()

        # Set in run() after context is injected - unblocks _send_audio_loop.
        # The AudioBridge mic gate (mic_open Event) is the real gatekeeper for
        # actual audio flow; this is a second layer at the agent level.
        self._session_ready = asyncio.Event()

    # ───────────
    # ENTRY POINT
    # ───────────

    async def run(self, context: InterviewContext) -> None:
        """
        Opens the Gemini session and drives the full interview lifecycle.

        Called by InterviewConnection as an asyncio Task after WebRTC is ready.
        Runs until the interview completes, the candidate disconnects, or an
        unhandled error occurs.

        Sequence:
          1. Open Gemini Live session (establishes the WebSocket to Gemini,
             configures audio format, voice, system prompt, and tools)
          2. Inject interview-specific context as the first user turn -
             this triggers Gemini to generate its opening greeting
          3. Set _session_ready to unblock _send_audio_loop
             (AudioBridge mic gate still controls actual audio flow)
          4. gather() _send_audio_loop and _receive_loop - they run concurrently
             for the entire interview
          5. On InterviewCompleteSignal: log and return (normal exit)
          6. On any other exception: mark interview abandoned and re-raise

        The `async with adapter.open_session()` block ensures the Gemini
        session is always closed, even if an exception escapes gather().
        """
        self._interview_id = context.interview_id

        async with self._adapter.open_session(
            system_prompt=build_system_prompt(context),
            tools=INTERVIEW_TOOLS,
        ) as session:
            logger.info(f"[Agent] Session opened for interview {context.interview_id}")
            await self._inject_context(session, context)

            # _send_audio_loop can now proceed, but AudioBridge still gates mic
            # until _on_turn_complete fires after Gemini's opening greeting.
            # This dual-gate pattern means:
            #   - _send_audio_loop is running (ready to stream audio as soon as mic opens)
            #   - No candidate audio reaches Gemini until it's done greeting
            self._session_ready.set()

            try:
                await asyncio.gather(
                    self._send_audio_loop(session),
                    self._receive_loop(session),
                )
            except InterviewCompleteSignal as sig:
                # Normal interview completion - not an error
                logger.info(
                    f"[Agent] Interview {context.interview_id} completed: {sig.reason}"
                )
            except Exception as e:
                # Unexpected error - mark the interview abandoned so it doesn't
                # sit as 'in_progress' in the DB forever
                logger.error(f"[Agent] Interview {context.interview_id} error: {e}")
                await self._orchestration.abandon_interview(
                    context.interview_id, reason="agent_error"
                )
                raise

    # ─────────────────
    # CONTEXT INJECTION
    # ─────────────────

    async def _inject_context(
        self, session: GeminiLiveAdapter, ctx: InterviewContext
    ) -> None:
        """
        Sends the interview-specific context to Gemini as the first user turn.

        This is distinct from the system prompt. The system prompt (built by
        build_system_prompt()) sets Gemini's persona, tone, and behavioural rules
        for all interviews. This injection gives it the data for THIS specific
        interview: job details, candidate name, topic list, question count.

        Sent as structured JSON so there's no ambiguity in parsing.

        Ending with "Please greet {candidate_name} warmly and ask your first question."
        immediately triggers Gemini's first response - it will generate the
        opening greeting as audio before any candidate audio has been sent.

        turn_complete=True (set internally in send_client_content) tells Gemini
        to treat this as a complete turn and respond right away.
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
        await session.send_client_content(
            text=(
                f"Interview session is starting now.\n"
                f"Context: {context_json}\n\n"
                f"Please greet {ctx.candidate_name} warmly and ask your first question."
            )
        )

    # ─────────────────────────────────────
    # AUDIO SEND LOOP (candidate -> Gemini)
    # ─────────────────────────────────────

    async def _send_audio_loop(self, session):
        """
        Continuously pulls PCM chunks from the browser mic and sends them
        to Gemini in real-time.

        This is one half of the two concurrent loops that run for the full
        interview. It runs alongside _receive_loop via asyncio.gather().

        FLOW:
          AudioBridge.audio_input_stream()
            -> this loop
              -> GeminiLiveAdapter.send_audio()
                -> Gemini Live API (16kHz PCM)

        GATING:
          Waits for _session_ready before starting - context must be injected
          and Gemini must be ready before we start streaming audio.
          The AudioBridge mic gate (_mic_open Event) provides the inner gate:
          even though this loop is running, no audio flows until open_mic()
          is called from _on_turn_complete after Gemini's opening greeting.

        EXIT:
          Checks _session_complete on every iteration. When the interview
          ends (complete_interview tool called), this flag breaks the loop
          cleanly without waiting for the next chunk from the queue.

        Empty chunks are silently skipped - the AudioBridge can occasionally
        emit zero-length bytes during transitions.
        """
        await self._session_ready.wait()
        async for chunk in self._audio_input:
            if self._session_complete.is_set():
                break
            if chunk:
                await session.send_audio(chunk)
                await asyncio.sleep(0.001)
                if random.random() < 0.01:  # log 1% of chunks
                    logger.info(f"""
                    \n[LiveAgent SEND AUDIO LOOP]
                    size={len(chunk)}
                    mod2={len(chunk) % 2}
                    first10={chunk[:10]}
                    \n""")

    # ─────────────────────────────────────────────────
    # RESPONSE RECEIVE LOOP (Gemini -> everything else)
    # ─────────────────────────────────────────────────

    async def _receive_loop(self, session: GeminiLiveAdapter) -> None:
        """
        Continuously receives events from Gemini and dispatches them to
        the appropriate handler or callback.

        This is the other half of the two concurrent loops. It runs for the
        full interview alongside _send_audio_loop.

        EVENT ROUTING:
          "audio"         -> on_audio_output callback
                            -> AudioBridge.outbound_queue -> WebRTC -> browser speaker

          "text"          -> on_text_output callback
                            -> WebSocket -> frontend (agent speech captions)

          "input_text"    -> on_input_text_output callback
                            -> WebSocket -> frontend (candidate speech captions)

          "interrupted"   -> on_interrupt callback
                            -> clear audio queue + suppress audio for 300ms

          "tool_call"     -> _handle_tool_call() (synchronous, blocks until done)
                            -> session.send_tool_response() (unblocks Gemini)

          "turn_complete" -> on_turn_complete callback
                            -> drain audio, reset resampler, open mic

          "go_away"       -> log and break (Gemini is shutting down the connection)

        TOOL CALL BLOCKING:
          Tool calls block this loop while being handled. That's correct -
          Gemini won't send more events until it gets a tool response, so
          there's nothing to miss while we're processing the tool call.

        EXIT:
          Checks _session_complete at the top of every iteration. This allows
          a clean exit after _tool_complete_interview sets the flag, even if
          more events arrive before Gemini closes the session.
        """
        async for event_type, data in session.receive():
            if self._session_complete.is_set():
                break

            match event_type:
                case "audio":
                    # 24kHz PCM chunk from Gemini - forward to browser immediately
                    logger.debug(f"[Agent] Received audio chunk of size {len(data)}")
                    await self._on_audio_output(data)

                case "text":
                    # Agent speech transcript - forward to frontend as captions
                    logger.debug(f"[Agent] Received text chunk: {data}")
                    if self._on_text_output:
                        await self._on_text_output(data)

                case "input_text":
                    # Candidate speech transcript - forward to frontend as captions
                    logger.info(f"[Agent] Candidate said: {data}")
                    if self._on_input_text_output:
                        await self._on_input_text_output(data)

                case "interrupted":
                    # Candidate started talking while agent was speaking -
                    # clear buffered audio and suppress further output briefly
                    logger.info("[Agent] Candidate interrupted - clearing audio queue")
                    if self._on_interrupt:
                        await self._on_interrupt()

                case "tool_call":
                    # Gemini wants to call one of our registered functions.
                    # We MUST respond - Gemini blocks until we do.
                    result = await self._handle_tool_call(
                        name=data["name"],
                        args=data["args"],
                        call_id=data["id"],
                    )
                    await session.send_tool_response(
                        call_id=data["id"],
                        name=data["name"],
                        result=result,
                    )

                case "turn_complete":
                    # Agent finished its response - hand control back to candidate
                    logger.debug("[Agent] Turn complete")
                    if self._on_turn_complete:
                        await self._on_turn_complete()

                case "go_away":
                    # Gemini is closing the session (e.g. session time limit hit)
                    logger.warning("[Agent] Server closing connection")
                    break

    # ───────────────
    # TOOL DISPATCHER
    # ───────────────

    async def _handle_tool_call(
        self, *, name: str, args: dict[str, Any], call_id: str
    ) -> dict[str, Any]:
        """
        Routes a Gemini tool call to the correct handler and returns the result.

        Gemini is configured with four tools (defined in INTERVIEW_TOOLS):
          record_question    - Gemini is about to ask a question; register it in DB
          persist_answer     - Gemini has received and evaluated an answer; save it
          complete_interview - Gemini decides the interview is done
          flag_interrupt     - Gemini detects the candidate is interrupting

        The return value is sent back to Gemini as the tool response. All handlers
        return {"success": True/False, ...} so Gemini can make decisions based on
        the outcome (e.g., if record_question fails, Gemini waits instead of advancing).

        ERROR HANDLING:
          InterviewCompleteSignal is intentionally re-raised here - it's not
          an error, it's the normal completion path. All other exceptions are
          caught, logged, and returned as {"error": ..., "success": False}
          so Gemini gets a response and can attempt to recover.

        call_id is accepted as a parameter for logging/tracing but not used
        directly here - it's passed back to send_tool_response() by the caller.
        """
        logger.info(f"[Agent] Tool: {name}({args})")
        try:
            match name:
                case "record_question":
                    return await self._tool_record_question(args)
                case "persist_answer":
                    return await self._tool_persist_answer(args)
                case "complete_interview":
                    return await self._tool_complete_interview(args)
                case "flag_interrupt":
                    return await self._tool_flag_interrupt(args)
                case _:
                    logger.warning(f"[Agent] Unknown tool: {name}")
                    return {"error": f"Unknown tool: {name}", "success": False}
        except InterviewCompleteSignal:
            raise  # Normal completion path - propagate up through gather() to run()
        except Exception as e:
            logger.error(f"[Agent] Tool {name} failed: {e}")
            return {"error": str(e), "success": False}

    # ────────────────────
    # TOOL IMPLEMENTATIONS
    # ────────────────────

    async def _tool_record_question(self, args: dict) -> dict:
        """
        Called by Gemini when it's about to ask the candidate a question.

        Delegates to orchestration.ask_next_question() which:
          - Validates that another question is allowed (checks max_questions limit)
          - Ensures no other question is currently active (prevents double-recording)
          - Creates a Question record in the DB with the topic and text
          - Returns the new question_id, question number, and total count

        We store the question_id in _current_question_id so that
        _tool_persist_answer can reference it later without Gemini needing
        to remember and echo it back.

        ON FAILURE (question already active, max reached, etc.):
          Returns a directive telling Gemini to wait. Gemini is instructed
          via the system prompt to respect this directive and not proceed
          to the next question until the current one is answered.

        Args from Gemini:
          topic         (str, optional)  - override the auto-selected topic
          question_text (str, optional)  - provide a custom question text
          is_follow_up  (bool, optional) - flag this as a follow-up question
        """
        try:
            result = await self._orchestration.ask_next_question(
                self._interview_id,
                topic_override=args.get("topic"),
                question_text_override=args.get("question_text"),
                is_follow_up=args.get("is_follow_up", False),
            )
            self._current_question_id = uuid.UUID(result["question_id"])
            return {
                "success": True,
                "question_id": result["question_id"],
                "question_number": result["question_number"],
                # questions_remaining helps Gemini decide if it should wrap up
                "questions_remaining": result["total_questions"]
                - result["question_number"],
            }
        except Exception as e:
            logger.warning(f"[Agent] record_question rejected: {e}")
            return {
                "success": False,
                "directive": "wait_for_candidate_answer",
                "message": "A question is already active. Please wait for the candidate to respond before recording a new question.",
            }

    async def _tool_persist_answer(self, args: dict) -> dict:
        """
        Called by Gemini after the candidate finishes answering a question
        and Gemini has evaluated/summarised the response.

        QUESTION ID RESOLUTION (in priority order):
          1. args["question_id"] - if Gemini explicitly passes it back
          2. self._current_question_id - the ID we stored in record_question
          3. Error - shouldn't happen in normal flow, but we guard against it

        Delegates to orchestration.submit_answer() which:
          - Saves the answer text and duration to the DB
          - Advances the interview state
          - Returns status="completed" if this was the last question

        If the interview is now complete (all questions answered), we set
        _session_complete so both loops exit on their next iteration.
        This gives Gemini time to deliver its closing remarks before the
        session actually tears down.

        Args from Gemini:
          answer_transcript (str)           - Gemini's summary of the candidate's answer
          question_id       (str, optional) - explicit question ID reference
          duration_seconds  (int, optional) - how long the candidate took to answer
        """
        question_id_str = args.get("question_id") or (
            str(self._current_question_id) if self._current_question_id else None
        )
        if not question_id_str:
            return {"error": "No active question", "success": False}

        result = await self._orchestration.submit_answer(
            interview_id=self._interview_id,
            question_id=uuid.UUID(question_id_str),
            answer_text=args["answer_transcript"],
            duration_seconds=args.get("duration_seconds"),
        )
        if result.get("status") == "completed":
            # All questions answered - signal loops to exit after current processing
            self._session_complete.set()

        return {
            "success": True,
            "answered_count": result.get("answered_count", 0),
            "interview_complete": result.get("status") == "completed",
            "remaining_questions": result.get("remaining_questions", 0),
        }

    async def _tool_complete_interview(self, args: dict) -> dict:
        """
        Called by Gemini when it has decided the interview is finished.

        This happens when:
          - All questions have been asked and answered
          - Time is up (Gemini tracks duration via system prompt instructions)
          - The candidate explicitly asks to end early

        WHAT WE DO:
          1. Publish an "interview.agent_ending" domain event to the queue.
             Downstream consumers (evaluation service, notification service)
             react to this to kick off post-interview processing.
          2. Set _session_complete so both loops exit on next iteration.
          3. Raise InterviewCompleteSignal - this propagates through:
               _handle_tool_call -> _receive_loop -> gather() -> run()
             where it's caught and treated as a normal (non-error) exit.

        NOTE: We raise instead of return here. The exception propagates before
        we even reach `return` - Gemini never gets a tool response for this call.
        That's intentional: the session is ending, Gemini doesn't need one.

        Args from Gemini:
          reason          (str) - why the interview is ending (e.g. "questions_exhausted")
          closing_remarks (str) - what Gemini said as its final statement
        """
        reason = args.get("reason", "questions_exhausted")
        await self._queue.publish(
            DomainEvent(
                event_type="interview.agent_ending",
                aggregate_id=str(self._interview_id),
                aggregate_type="Interview",
                occurred_at=_utcnow_iso(),
                payload={
                    "interview_id": str(self._interview_id),
                    "reason": reason,
                    "closing_remarks": args.get("closing_remarks", ""),
                },
            )
        )
        self._session_complete.set()
        raise InterviewCompleteSignal(reason)

    async def _tool_flag_interrupt(self, args: dict) -> dict:
        """
        Called by Gemini when it detects the candidate is interrupting -
        either providing an answer, asking for clarification, reacting to
        background noise, or reporting a technical issue.

        This is a two-part signal that bridges three layers of the system:

        PART 1 - Cache (near-real-time signal to the WebSocket layer):
          Writes interrupt data to Redis under "interrupt:{interview_id}".
          The interrupt monitor loop in InterviewConnection reads this key
          every 50ms and forwards it to the frontend as a WebSocket message.
          The frontend uses the directive to update its UI (e.g., show a
          "listening..." indicator, mute the agent's audio track, etc.).
          Key TTL = 30s as a safety net (monitor deletes it in ~50ms normally).

        PART 2 - Queue (async signal to downstream services):
          Publishes "interview.interrupted" as a domain event. Downstream
          consumers (analytics, review tools) can react asynchronously.

        INTERRUPT TYPES AND THEIR DIRECTIVES:
          "clarification" -> "acknowledge_and_continue"
            Candidate asked a clarifying question. Note it, then continue.
          "answer"        -> "stop_and_listen"
            Candidate is answering. Stop speaking, listen actively.
          "noise"         -> "resume"
            Background noise detected, not the candidate. Keep going.
          "technical"     -> "stop_and_listen"
            Technical issue (mic cutout, connection drop). Pause and check in.

        The directive is also used by InterviewConnection._interrupt_monitor_loop()
        to decide whether to set _suppress_audio (for "stop_and_listen") or not.

        Args from Gemini:
          interrupt_type     (str)           - one of: clarification, answer, noise, technical
          partial_transcript (str, optional) - what Gemini heard before interrupting
        """
        interrupt_id = uuid.uuid4()
        interrupt_type = args.get("interrupt_type", "answer")
        directive = {
            "clarification": "acknowledge_and_continue",
            "answer": "stop_and_listen",
            "noise": "resume",
            "technical": "stop_and_listen",
        }.get(
            interrupt_type, "stop_and_listen"
        )  # default to stop_and_listen if unknown type

        # Write to cache (picked up by interrupt monitor in ~50ms)
        await self._cache.set(
            f"interrupt:{self._interview_id}",
            {
                "interrupt_id": str(interrupt_id),
                "type": interrupt_type,
                "directive": directive,
                "partial_transcript": args.get("partial_transcript"),
                "timestamp": _utcnow_iso(),
            },
            ttl_seconds=INTERRUPT_CACHE_TTL,
        )

        # Publish to queue (for analytics and downstream processing)
        await self._queue.publish(
            DomainEvent(
                event_type="interview.interrupted",
                aggregate_id=str(self._interview_id),
                aggregate_type="Interview",
                occurred_at=_utcnow_iso(),
                payload={
                    "interview_id": str(self._interview_id),
                    "interrupt_id": str(interrupt_id),
                    "type": interrupt_type,
                    "directive": directive,
                    "partial_transcript": args.get("partial_transcript"),
                },
            )
        )
        return {
            "success": True,
            "interrupt_id": str(interrupt_id),
            "directive": directive,
        }


# ─────────────────────────
# INTERVIEW COMPLETE SIGNAL
# ─────────────────────────


class InterviewCompleteSignal(Exception):
    """
    Raised by _tool_complete_interview to signal that the interview is done.

    WHY AN EXCEPTION INSTEAD OF A FLAG + BREAK?
      Using an exception lets the completion signal propagate cleanly through
      asyncio.gather() without needing to explicitly check a flag at the end
      of every tool call in _receive_loop. It also separates the "normal
      completion" path from the "unhandled error" path at the gather() level -
      run() catches this specifically and logs it as a successful completion,
      while other exceptions are treated as errors and trigger abandon_interview().

    WHY NOT SystemExit OR BaseException?
      We want this caught by the `except InterviewCompleteSignal` in run()
      and by the `except InterviewCompleteSignal: raise` re-raise in
      _handle_tool_call(). Using a plain Exception subclass makes it easy
      to be explicit about where it should and shouldn't be caught.

    Propagation path:
      _tool_complete_interview()
        -> _handle_tool_call()   (re-raises, not caught here)
          -> _receive_loop()     (raised through, exits the async for)
            -> asyncio.gather()  (one of the tasks raises -> gather() propagates)
              -> run()           (caught here, logged as normal completion)
    """

    def __init__(self, reason: str) -> None:
        self.reason = (
            reason  # e.g. "questions_exhausted", "time_limit", "candidate_ended"
        )
        super().__init__(reason)

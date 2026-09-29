"""
LiveInterviewAgent driven by a fake LiveSessionPort: event routing, tool
dispatch, completion and error paths. No network, DB or Redis.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.truefit_core.agents.interviewer.context import InterviewContext
from src.truefit_core.agents.interviewer.live_interview_agent import (
    LiveInterviewAgent,
)
from tests.unit.llm.fakes import FakeLiveAdapter

pytestmark = pytest.mark.unit


def _context() -> InterviewContext:
    return InterviewContext(
        interview_id=uuid.uuid4(),
        job_title="Backend Engineer",
        job_description="Build APIs",
        required_skills=["python"],
        experience_level="mid",
        max_questions=3,
        max_duration_minutes=20,
        topics=["apis"],
        custom_instructions=None,
        candidate_name="Ada",
        candidate_resume_text=None,
    )


async def _mic(chunks=()):
    for c in chunks:
        yield c


def _agent(adapter, *, mic=(), **callbacks):
    orchestration = MagicMock()
    orchestration.ask_next_question = AsyncMock()
    orchestration.submit_answer = AsyncMock()
    orchestration.abandon_interview = AsyncMock()
    agent = LiveInterviewAgent(
        live_adapter=adapter,
        orchestration=orchestration,
        queue=MagicMock(publish=AsyncMock()),
        cache=MagicMock(set=AsyncMock()),
        audio_input_stream=_mic(mic),
        on_audio_output=callbacks.pop("on_audio_output", AsyncMock()),
        **callbacks,
    )
    return agent, orchestration


async def test_run_opens_session_with_prompt_tools_and_greets():
    adapter = FakeLiveAdapter()
    agent, _ = _agent(adapter)
    ctx = _context()

    await agent.run(ctx)

    prompt, tools = adapter.open_args
    assert isinstance(prompt, str) and prompt.strip()
    assert tools  # interview tools registered
    assert len(adapter.content) == 1
    assert "Ada" in adapter.content[0] and str(ctx.interview_id) in adapter.content[0]
    assert adapter.closed_count == 1


async def test_audio_from_mic_is_forwarded_and_empty_chunks_skipped():
    adapter = FakeLiveAdapter(hold_open_until_audio=2)
    agent, _ = _agent(adapter, mic=[b"\x01\x02", b"", b"\x03\x04"])
    await agent.run(_context())
    assert adapter.audio == [b"\x01\x02", b"\x03\x04"]


async def test_receive_events_routed_to_callbacks():
    on_audio, on_text, on_input = AsyncMock(), AsyncMock(), AsyncMock()
    on_interrupt, on_turn = AsyncMock(), AsyncMock()
    adapter = FakeLiveAdapter(
        events=[
            ("audio", b"pcm"),
            ("text", "hello"),
            ("input_text", "hi there"),
            ("interrupted", None),
            ("turn_complete", None),
        ]
    )
    agent, _ = _agent(
        adapter,
        on_audio_output=on_audio,
        on_text_output=on_text,
        on_input_text_output=on_input,
        on_interrupt=on_interrupt,
        on_turn_complete=on_turn,
    )

    await agent.run(_context())

    on_audio.assert_awaited_once_with(b"pcm")
    on_text.assert_awaited_once_with("hello")
    on_input.assert_awaited_once_with("hi there")
    on_interrupt.assert_awaited_once()
    on_turn.assert_awaited_once()


async def test_missing_optional_callbacks_do_not_crash():
    adapter = FakeLiveAdapter(
        events=[("text", "x"), ("input_text", "y"), ("interrupted", None), ("turn_complete", None)]
    )
    agent, _ = _agent(adapter)
    await agent.run(_context())


async def test_go_away_stops_processing_further_events():
    on_audio = AsyncMock()
    adapter = FakeLiveAdapter(events=[("go_away", None), ("audio", b"late")])
    agent, _ = _agent(adapter, on_audio_output=on_audio)
    await agent.run(_context())
    on_audio.assert_not_awaited()


async def test_record_question_tool_success_returns_remaining_and_stores_id():
    qid = uuid.uuid4()
    adapter = FakeLiveAdapter(
        events=[("tool_call", {"id": "c1", "name": "record_question", "args": {"topic": "apis"}})]
    )
    agent, orch = _agent(adapter)
    orch.ask_next_question.return_value = {
        "question_id": str(qid),
        "question_number": 1,
        "total_questions": 3,
    }

    await agent.run(_context())

    resp = adapter.tool_responses[0]
    assert resp["call_id"] == "c1" and resp["name"] == "record_question"
    assert resp["result"] == {
        "success": True,
        "question_id": str(qid),
        "question_number": 1,
        "questions_remaining": 2,
    }
    assert agent.handlers.current_question_id == qid


async def test_record_question_rejection_tells_model_to_wait():
    adapter = FakeLiveAdapter(events=[("tool_call", {"id": "c1", "name": "record_question", "args": {}})])
    agent, orch = _agent(adapter)
    orch.ask_next_question.side_effect = ValueError("question already active")

    await agent.run(_context())

    result = adapter.tool_responses[0]["result"]
    assert result["success"] is False
    assert result["directive"] == "wait_for_candidate_answer"


async def test_persist_answer_without_active_question_errors():
    adapter = FakeLiveAdapter(
        events=[("tool_call", {"id": "c1", "name": "persist_answer", "args": {"answer_transcript": "a"}})]
    )
    agent, orch = _agent(adapter)
    await agent.run(_context())
    assert adapter.tool_responses[0]["result"] == {"error": "No active question", "success": False}
    orch.submit_answer.assert_not_awaited()


async def test_persist_answer_uses_stored_question_and_flags_completion():
    qid = uuid.uuid4()
    adapter = FakeLiveAdapter(
        events=[
            ("tool_call", {"id": "c0", "name": "record_question", "args": {}}),
            ("tool_call", {"id": "c1", "name": "persist_answer",
                           "args": {"answer_transcript": "my answer", "duration_seconds": 12}}),
            ("audio", b"after-complete"),
        ]
    )
    on_audio = AsyncMock()
    agent, orch = _agent(adapter, on_audio_output=on_audio)
    orch.ask_next_question.return_value = {
        "question_id": str(qid), "question_number": 1, "total_questions": 1,
    }
    orch.submit_answer.return_value = {"status": "completed", "answered_count": 1, "remaining_questions": 0}
    ctx = _context()

    await agent.run(ctx)

    orch.submit_answer.assert_awaited_once_with(
        interview_id=ctx.interview_id, question_id=qid, answer_text="my answer", duration_seconds=12
    )
    assert adapter.tool_responses[1]["result"]["interview_complete"] is True
    assert agent.runtime.end_reason == "questions_exhausted"
    on_audio.assert_not_awaited()  # loop exits once the interview is complete


async def test_unknown_tool_returns_error_instead_of_raising():
    adapter = FakeLiveAdapter(events=[("tool_call", {"id": "c1", "name": "nope", "args": {}})])
    agent, _ = _agent(adapter)
    await agent.run(_context())
    assert adapter.tool_responses[0]["result"]["success"] is False


async def test_tool_exception_is_returned_to_model_not_raised():
    adapter = FakeLiveAdapter(
        events=[("tool_call", {"id": "c1", "name": "persist_answer",
                               "args": {"answer_transcript": "a", "question_id": str(uuid.uuid4())}})]
    )
    agent, orch = _agent(adapter)
    orch.submit_answer.side_effect = RuntimeError("db down")

    await agent.run(_context())

    assert adapter.tool_responses[0]["result"]["success"] is False
    orch.abandon_interview.assert_not_awaited()


async def test_complete_interview_publishes_event_and_ends_without_tool_response():
    adapter = FakeLiveAdapter(
        events=[("tool_call", {"id": "c1", "name": "complete_interview",
                               "args": {"reason": "time_up", "closing_remarks": "bye"}})]
    )
    agent, orch = _agent(adapter)
    ctx = _context()

    await agent.run(ctx)  # InterviewCompleteSignal must not escape

    event = agent._queue.publish.await_args.args[0]
    assert event.event_type == "interview.agent_ending"
    assert event.payload["reason"] == "time_up"
    assert adapter.tool_responses == []
    orch.abandon_interview.assert_not_awaited()


@pytest.mark.parametrize(
    "itype,directive",
    [
        ("clarification", "acknowledge_and_continue"),
        ("answer", "stop_and_listen"),
        ("noise", "resume"),
        ("technical", "stop_and_listen"),
        ("bogus", "stop_and_listen"),
    ],
)
async def test_flag_interrupt_directive_mapping(itype, directive):
    adapter = FakeLiveAdapter(
        events=[("tool_call", {"id": "c1", "name": "flag_interrupt", "args": {"interrupt_type": itype}})]
    )
    agent, _ = _agent(adapter)
    ctx = _context()

    await agent.run(ctx)

    key, value = agent._cache.set.await_args.args[:2]
    assert key == f"interrupt:{ctx.interview_id}"
    assert value["directive"] == directive
    agent._queue.publish.assert_awaited()


async def test_unexpected_receive_error_abandons_interview_and_reraises():
    class Boom(FakeLiveAdapter):
        async def receive(self):
            raise ConnectionError("socket died")
            yield  # pragma: no cover

    agent, orch = _agent(Boom())
    ctx = _context()

    with pytest.raises(ConnectionError):
        await agent.run(ctx)

    orch.abandon_interview.assert_awaited_once_with(ctx.interview_id, reason="agent_error")

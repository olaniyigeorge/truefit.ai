"""
GeminiLiveAdapter.receive() against a fake SDK session that behaves like the
real one: each session.receive() call covers ONE turn and stops at turn_complete.
"""

from types import SimpleNamespace

import pytest

from soro.adapters.gemini import GeminiLiveAdapter

pytestmark = pytest.mark.unit


def msg(*, data=None, out_text=None, in_text=None, turn_complete=False, interrupted=False, tool_call=None, go_away=None):
    sc = SimpleNamespace(
        output_transcription=SimpleNamespace(text=out_text) if out_text else None,
        input_transcription=SimpleNamespace(text=in_text) if in_text else None,
        interrupted=interrupted,
        turn_complete=turn_complete,
    )
    return SimpleNamespace(data=data, server_content=sc, tool_call=tool_call, go_away=go_away)


class FakeSdkSession:
    """turns: list of turns, each a list of messages. receive() serves one turn per call,
    like google.genai's AsyncSession.receive(), then raises when the connection is gone."""

    def __init__(self, turns, on_exhausted=None):
        self._turns = list(turns)
        self.receive_calls = 0
        self._on_exhausted = on_exhausted or ConnectionError("connection closed")

    async def receive(self):
        self.receive_calls += 1
        if not self._turns:
            raise self._on_exhausted
        for m in self._turns.pop(0):
            yield m


async def collect(session, stop_after=None):
    adapter = GeminiLiveAdapter(api_key="k")
    adapter._session = session
    events = []
    with pytest.raises(ConnectionError):
        async for ev in adapter.receive():
            events.append(ev)
    return events, adapter


async def test_keeps_reading_across_turns():
    """Regression: the adapter used to stop after the first turn, so the agent
    greeted the candidate and then never answered again."""
    session = FakeSdkSession(
        [
            [msg(data=b"hello", out_text="Hi, welcome.", turn_complete=True)],
            [msg(in_text="I built a queue", data=b"answer", out_text="Interesting.", turn_complete=True)],
            [msg(data=b"third", out_text="Next question.", turn_complete=True)],
        ]
    )
    events, _ = await collect(session)

    assert [e for e in events if e[0] == "turn_complete"] == [("turn_complete", None)] * 3
    assert [e[1] for e in events if e[0] == "audio"] == [b"hello", b"answer", b"third"]
    assert [e[1] for e in events if e[0] == "text"] == ["Hi, welcome.", "Interesting.", "Next question."]
    assert ("input_text", "I built a queue") in events
    assert session.receive_calls == 4  # three turns, then the closed connection surfaced


async def test_transcript_buffers_do_not_leak_between_turns():
    session = FakeSdkSession(
        [
            [msg(out_text="First ", turn_complete=False), msg(out_text="turn.", turn_complete=True)],
            [msg(out_text="Second.", turn_complete=True)],
        ]
    )
    events, _ = await collect(session)
    assert [e[1] for e in events if e[0] == "text"] == ["First turn.", "Second."]


async def test_tool_calls_and_interruptions_survive_later_turns():
    call = SimpleNamespace(function_calls=[SimpleNamespace(id="c1", name="record_question", args={"topic": "apis"})])
    session = FakeSdkSession(
        [
            [msg(turn_complete=True)],
            [msg(tool_call=call), msg(interrupted=True), msg(turn_complete=True)],
        ]
    )
    events, _ = await collect(session)
    assert ("tool_call", {"id": "c1", "name": "record_question", "args": {"topic": "apis"}}) in events
    assert ("interrupted", None) in events


async def test_go_away_is_reported_as_session_ending():
    session = FakeSdkSession([[msg(go_away=SimpleNamespace(time_left="30s"), turn_complete=True)]])
    events, _ = await collect(session)
    assert ("session_ending", {"reason": "provider_go_away", "time_left": "30s"}) in events


async def test_ends_quietly_when_the_session_is_closed_locally():
    """Closing the session (adapter._session = None) must end receive() cleanly, not raise."""
    adapter = GeminiLiveAdapter(api_key="k")

    class ClosingSession(FakeSdkSession):
        async def receive(self):
            async for m in super().receive():
                yield m
            adapter._session = None  # what __aexit__ does

    adapter._session = ClosingSession([[msg(data=b"x", turn_complete=True)]])
    events = [e async for e in adapter.receive()]
    assert events == [("audio", b"x"), ("turn_complete", None)]


async def test_a_session_that_only_returns_empty_passes_cannot_spin_forever():
    class EmptySession:
        calls = 0

        async def receive(self):
            EmptySession.calls += 1
            return
            yield  # pragma: no cover

    adapter = GeminiLiveAdapter(api_key="k")
    adapter._session = EmptySession()
    assert [e async for e in adapter.receive()] == []
    assert EmptySession.calls == 3


# ── Reconnect and session resumption (1011 "Internal error", go_away)

import asyncio

from google.genai import errors as genai_errors

from soro.tools import ToolSpec


def resumption(handle, resumable=True):
    return SimpleNamespace(new_handle=handle, resumable=resumable)


def rmsg(**kw):
    """msg() plus an optional resumption update."""
    handle = kw.pop("handle", None)
    resumable = kw.pop("resumable", True)
    m = msg(**kw)
    m.session_resumption_update = resumption(handle, resumable) if handle else None
    return m


class ScriptedSession(FakeSdkSession):
    """Like FakeSdkSession but records what is sent, and can fail after its turns."""

    def __init__(self, turns, then=None):
        super().__init__(turns, on_exhausted=then)
        self.content: list[str] = []
        self.audio: list[bytes] = []
        self.activity: list[str] = []

    async def send_client_content(self, *, turns, turn_complete):
        self.content.append(turns.parts[0].text)

    async def send_realtime_input(self, **kw):
        if "media" in kw:
            self.audio.append(kw["media"].data)
        if "activity_start" in kw:
            self.activity.append("start")
        if "activity_end" in kw:
            self.activity.append("end")


class FakeLive:
    """client.aio.live: hands out scripted sessions and records each connect()."""

    def __init__(self, sessions, gate: asyncio.Event | None = None):
        self._sessions = list(sessions)
        self.connects: list[dict] = []
        self.closed: list[ScriptedSession] = []
        self._gate = gate

    def connect(self, *, model, config):
        self.connects.append({"model": model, "config": config})
        live = self
        session = self._sessions.pop(0)

        class CM:
            async def __aenter__(self_):
                if live._gate is not None and len(live.connects) > 1:
                    await live._gate.wait()
                return session

            async def __aexit__(self_, *a):
                live.closed.append(session)

        return CM()


def make_adapter(sessions, gate=None, **kwargs):
    adapter = GeminiLiveAdapter(api_key="k", **kwargs)
    live = FakeLive(sessions, gate)
    adapter._client = SimpleNamespace(aio=SimpleNamespace(live=live))
    return adapter, live


def err(code):
    return genai_errors.APIError(code, {"message": "Internal error occurred."})


async def run_events(adapter, tools=None, opening=None):
    events = []
    async with adapter.open_session("prompt", tools=tools or []) as session:
        if opening:
            await session.send_client_content(opening)
        try:
            async for ev in session.receive():
                events.append(ev)
        except Exception as exc:  # the test asserts on events and on what was raised
            events.append(("raised", exc))
    return events


async def test_transient_error_resumes_with_the_handle_and_reports_it():
    first = ScriptedSession([[rmsg(handle="h1", data=b"a", turn_complete=True)]], then=err(1011))
    second = ScriptedSession([[msg(data=b"b", out_text="Back again.", turn_complete=True)]], then=ConnectionError("end"))
    adapter, live = make_adapter([first, second])

    events = await run_events(adapter)

    kinds = [e[0] for e in events]
    assert kinds.index("session_resumed") < kinds.index("text")
    assert ("session_resumed", {"reason": "connection_error", "restarted": False}) in events
    assert ("text", "Back again.") in events
    assert len(live.connects) == 2
    assert live.connects[1]["config"].session_resumption.handle == "h1"  # continued, not restarted
    assert first in live.closed  # the dead connection was torn down


async def test_early_failure_without_a_handle_restarts_and_replays_the_opening_message():
    """The first log: 1011 four seconds in, before any resumption handle existed."""
    first = ScriptedSession([], then=err(1011))
    second = ScriptedSession([[msg(data=b"hi", out_text="Hello!", turn_complete=True)]], then=ConnectionError("end"))
    adapter, live = make_adapter([first, second])

    events = await run_events(adapter, opening="Interview context")

    assert ("text", "Hello!") in events
    assert ("session_resumed", {"reason": "connection_error", "restarted": True}) in events  # state was lost
    assert live.connects[1]["config"].session_resumption.handle is None
    assert second.content == ["Interview context"]  # replayed onto the fresh session


async def test_handle_is_only_kept_when_resumable():
    first = ScriptedSession([[rmsg(handle="not-yet", resumable=False, turn_complete=True)]], then=err(1011))
    second = ScriptedSession([], then=ConnectionError("end"))
    adapter, live = make_adapter([first, second])
    await run_events(adapter, opening="ctx")
    assert live.connects[1]["config"].session_resumption.handle is None


async def test_the_latest_handle_wins():
    first = ScriptedSession(
        [[rmsg(handle="h1", turn_complete=True)], [rmsg(handle="h2", turn_complete=True)]], then=err(1011)
    )
    second = ScriptedSession([], then=ConnectionError("end"))
    adapter, live = make_adapter([first, second])
    await run_events(adapter)
    assert live.connects[1]["config"].session_resumption.handle == "h2"


@pytest.mark.parametrize("code", [1006, 1011, 1012, 1013, 1001])
async def test_each_transient_close_code_is_retried(code):
    first = ScriptedSession([[rmsg(handle="h", turn_complete=True)]], then=err(code))
    second = ScriptedSession([[msg(turn_complete=True)]], then=ConnectionError("end"))
    adapter, live = make_adapter([first, second])
    events = await run_events(adapter)
    assert len(live.connects) == 2 and any(e[0] == "session_resumed" for e in events)


@pytest.mark.parametrize("bad", [err(1007), err(1008), err(400), ValueError("bug")])
async def test_non_transient_errors_are_not_retried(bad):
    first = ScriptedSession([[rmsg(handle="h", turn_complete=True)]], then=bad)
    adapter, live = make_adapter([first])
    events = await run_events(adapter)
    assert events[-1][0] == "raised" and events[-1][1] is bad
    assert len(live.connects) == 1


async def test_gives_up_after_three_reconnects_in_a_row():
    def dead():
        return ScriptedSession([], then=err(1011))

    adapter, live = make_adapter([dead(), dead(), dead(), dead(), dead()])
    events = await run_events(adapter)
    assert events[-1][0] == "raised" and isinstance(events[-1][1], genai_errors.APIError)
    assert len(live.connects) == 1 + 3  # the original plus three attempts, then it stops


async def test_the_retry_budget_resets_whenever_the_connection_delivers():
    """A long session can be recycled many times as long as each connection works."""
    sessions = [ScriptedSession([[rmsg(handle=f"h{i}", turn_complete=True)]], then=err(1011)) for i in range(6)]
    sessions.append(ScriptedSession([[msg(turn_complete=True)]], then=ConnectionError("end")))
    adapter, live = make_adapter(sessions)
    events = await run_events(adapter)
    assert sum(1 for e in events if e[0] == "session_resumed") == 6
    assert len(live.connects) == 7


async def test_go_away_with_a_handle_resumes_instead_of_ending_the_session():
    """Gemini recycles connections periodically; that must not end a 45 minute session."""
    first = ScriptedSession(
        [[rmsg(handle="h1", turn_complete=True)], [msg(go_away=SimpleNamespace(time_left="30s"))]], then=err(1011)
    )
    second = ScriptedSession([[msg(out_text="Still here.", turn_complete=True)]], then=ConnectionError("end"))
    adapter, live = make_adapter([first, second])
    events = await run_events(adapter)
    assert ("session_resumed", {"reason": "go_away", "restarted": False}) in events
    assert not any(e[0] == "session_ending" for e in events)
    assert ("text", "Still here.") in events
    assert live.connects[1]["config"].session_resumption.handle == "h1"


async def test_go_away_without_a_handle_still_reports_session_ending():
    first = ScriptedSession([[msg(go_away=SimpleNamespace(time_left="30s"), turn_complete=True)]], then=ConnectionError("end"))
    adapter, live = make_adapter([first])
    events = await run_events(adapter)
    assert ("session_ending", {"reason": "provider_go_away", "time_left": "30s"}) in events
    assert len(live.connects) == 1


async def test_audio_is_held_until_the_next_activity_start_after_a_reconnect():
    first = ScriptedSession([[rmsg(handle="h", turn_complete=True)]], then=err(1011))
    second = ScriptedSession([[msg(turn_complete=True)]], then=ConnectionError("end"))
    adapter, live = make_adapter([first, second])
    async with adapter.open_session("p") as session:
        try:
            [e async for e in session.receive()]
        except Exception:
            pass
        await session.send_audio(b"mid-turn")  # the new session has no open activity
        assert second.audio == []
        await session.send_activity_start()
        await session.send_audio(b"new-turn")
    assert second.audio == [b"new-turn"] and second.activity == ["start"]


async def test_senders_wait_for_the_reconnect_instead_of_hitting_a_dead_session():
    gate = asyncio.Event()
    first = ScriptedSession([[rmsg(handle="h", turn_complete=True)]], then=err(1011))
    second = ScriptedSession([[msg(turn_complete=True)]], then=ConnectionError("end"))
    adapter, live = make_adapter([first, second], gate=gate)

    async with adapter.open_session("p") as session:
        async def drain():
            try:
                return [e async for e in session.receive()]
            except Exception:
                return None

        receiver = asyncio.create_task(drain())
        await asyncio.sleep(0.1)  # reconnect is now blocked in connect()
        sender = asyncio.create_task(session.send_client_content("hello after drop"))
        await asyncio.sleep(0.05)
        assert not sender.done()  # waiting, not raising "no active session"
        gate.set()
        await asyncio.wait_for(asyncio.gather(receiver, sender), timeout=3)
    assert second.content == ["hello after drop"]


async def test_connection_config_enables_resumption_and_compression():
    first = ScriptedSession([], then=ConnectionError("end"))
    adapter, live = make_adapter([first])
    await run_events(adapter, tools=[ToolSpec(name="ping")])
    cfg = live.connects[0]["config"]
    assert cfg.session_resumption is not None and cfg.session_resumption.handle is None
    assert cfg.context_window_compression is not None
    assert cfg.tools is not None


async def test_model_can_be_set_with_an_argument():
    adapter, live = make_adapter([ScriptedSession([], then=ConnectionError("end"))], model="gemini-live-2.5-flash-native-audio")
    await run_events(adapter)
    assert live.connects[0]["model"] == "gemini-live-2.5-flash-native-audio"


async def test_model_can_be_set_with_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_LIVE_MODEL", "from-env")
    adapter, live = make_adapter([ScriptedSession([], then=ConnectionError("end"))])
    await run_events(adapter)
    assert live.connects[0]["model"] == "from-env"


async def test_the_argument_beats_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_LIVE_MODEL", "from-env")
    adapter, live = make_adapter([ScriptedSession([], then=ConnectionError("end"))], model="from-arg")
    await run_events(adapter)
    assert live.connects[0]["model"] == "from-arg"


async def test_voice_is_configurable_and_reaches_the_session_config():
    adapter, live = make_adapter([ScriptedSession([], then=ConnectionError("end"))], voice="Puck")
    await run_events(adapter)
    cfg = live.connects[0]["config"]
    assert cfg.speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"


def test_missing_api_key_fails_at_construction(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        GeminiLiveAdapter()


def test_api_key_falls_back_to_the_environment(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "env-key")
    GeminiLiveAdapter()  # does not raise


async def test_default_model_when_not_overridden():
    adapter, live = make_adapter([ScriptedSession([], then=ConnectionError("end"))])
    await run_events(adapter)
    assert live.connects[0]["model"].startswith("gemini-2.5-flash-native-audio")


async def test_a_session_that_keeps_dying_mid_greeting_gives_up_instead_of_looping():
    """Regression: 1011 six seconds in, every time, with greeting audio arriving first.
    Any message used to reset the retry budget, so the greeting was replayed forever."""
    def dies_mid_greeting():
        return ScriptedSession([[msg(data=b"hel", out_text="Hel")]], then=err(1011))  # audio, never turn_complete

    adapter, live = make_adapter([dies_mid_greeting() for _ in range(8)])
    events = await run_events(adapter, opening="Greet the candidate")

    assert events[-1][0] == "raised"
    assert len(live.connects) == 1 + 3  # the original plus three attempts, then it stops
    assert sum(1 for e in events if e[0] == "session_resumed") == 3


async def test_only_a_completed_turn_restores_the_retry_budget():
    """Two completed turns in a row prove the connection works, so later failures may retry again."""
    sessions = [
        ScriptedSession([[msg(data=b"a")]], then=err(1011)),  # fails mid-turn
        ScriptedSession([[msg(data=b"b")]], then=err(1011)),  # fails mid-turn
        ScriptedSession([[msg(data=b"c", turn_complete=True)]], then=err(1011)),  # completes, budget restored
        ScriptedSession([[msg(data=b"d")]], then=err(1011)),
        ScriptedSession([[msg(data=b"e")]], then=err(1011)),
        ScriptedSession([[msg(turn_complete=True)]], then=ConnectionError("end")),
    ]
    adapter, live = make_adapter(sessions)
    events = await run_events(adapter, opening="hi")
    assert events[-1] == ("raised", events[-1][1]) and isinstance(events[-1][1], ConnectionError)
    assert len(live.connects) == 6

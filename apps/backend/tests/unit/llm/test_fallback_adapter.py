import pytest

from src.truefit_infra.llm import fallback_adapter
from src.truefit_infra.llm.fallback_adapter import FallbackLiveAdapter
from tests.unit.llm.fakes import FakeLiveAdapter

pytestmark = pytest.mark.unit


async def test_uses_primary_when_it_opens():
    primary, backup = FakeLiveAdapter(), FakeLiveAdapter()
    adapter = FallbackLiveAdapter(primary=primary, fallback=backup)

    async with adapter.open_session("prompt", tools=[{"t": 1}]) as session:
        await session.send_audio(b"\x00\x01")

    assert primary.audio == [b"\x00\x01"]
    assert backup.audio == []
    assert primary.open_args == ("prompt", [{"t": 1}])
    assert backup.open_args is None


async def test_falls_back_when_primary_fails_to_open():
    primary = FakeLiveAdapter(fail_open=ConnectionError("down"))
    backup = FakeLiveAdapter()
    adapter = FallbackLiveAdapter(primary=primary, fallback=backup)

    async with adapter.open_session("p") as session:
        await session.send_client_content("hi")

    assert backup.content == ["hi"]
    assert primary.content == []


async def test_falls_back_when_primary_times_out(monkeypatch):
    import asyncio

    class Hanging(FakeLiveAdapter):
        def open_session(self, system_prompt, tools=None):
            class C:
                async def __aenter__(self_):
                    await asyncio.sleep(5)

                async def __aexit__(self_, *a):
                    pass

            return C()

    monkeypatch.setattr(fallback_adapter, "_SESSION_OPEN_TIMEOUT", 0.05)
    backup = FakeLiveAdapter()
    adapter = FallbackLiveAdapter(primary=Hanging(), fallback=backup)

    async with adapter.open_session("p") as session:
        await session.send_audio(b"x")

    assert backup.audio == [b"x"]


async def test_primary_error_propagates_without_fallback():
    adapter = FallbackLiveAdapter(primary=FakeLiveAdapter(fail_open=ValueError("bad key")))
    with pytest.raises(ValueError, match="bad key"):
        async with adapter.open_session("p"):
            pass


async def test_raises_when_both_fail_and_mentions_both():
    adapter = FallbackLiveAdapter(
        primary=FakeLiveAdapter(fail_open=ValueError("primary boom")),
        fallback=FakeLiveAdapter(fail_open=ValueError("backup boom")),
    )
    with pytest.raises(RuntimeError) as exc:
        async with adapter.open_session("p"):
            pass
    assert "primary boom" in str(exc.value) and "backup boom" in str(exc.value)


async def test_calls_outside_session_raise():
    adapter = FallbackLiveAdapter(primary=FakeLiveAdapter())
    with pytest.raises(RuntimeError, match="no active session"):
        await adapter.send_audio(b"x")


async def test_receive_and_tool_response_delegate_to_active():
    events = [("audio", b"a"), ("tool_call", {"id": "1", "name": "n", "args": {}}), ("turn_complete", None)]
    primary = FakeLiveAdapter(events=events)
    adapter = FallbackLiveAdapter(primary=primary)

    async with adapter.open_session("p") as session:
        got = [e async for e in session.receive()]
        await session.send_tool_response(call_id="1", name="n", result={"ok": True})

    assert got == events
    assert primary.tool_responses == [{"call_id": "1", "name": "n", "result": {"ok": True}}]


async def test_active_cleared_and_session_closed_on_exit():
    primary = FakeLiveAdapter()
    adapter = FallbackLiveAdapter(primary=primary)
    async with adapter.open_session("p") as session:
        assert await session.is_healthy()
    assert primary.closed_count == 1
    assert not await adapter.is_healthy()


async def test_body_exception_is_not_masked_by_teardown():
    adapter = FallbackLiveAdapter(primary=FakeLiveAdapter())
    with pytest.raises(KeyError):
        async with adapter.open_session("p"):
            raise KeyError("body")


async def test_health_check_reports_both_providers():
    adapter = FallbackLiveAdapter(primary=FakeLiveAdapter(), fallback=FakeLiveAdapter())
    report = await adapter.health_check()
    assert report["primary"]["provider"] == "FakeLiveAdapter"
    assert report["fallback"]["provider"] == "FakeLiveAdapter"
    assert report["active_provider"] is None

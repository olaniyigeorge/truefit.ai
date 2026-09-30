import pytest

from soro.ports import AdapterCapabilities
from soro.tools import ToolSpec
from soro.errors import CapabilityNotSupported
from soro.adapters import fallback as fallback_adapter
from soro.adapters.fallback import FallbackLiveAdapter
from soro.testing import FakeLiveAdapter

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


# ── Capabilities and manual turn signalling


def test_capabilities_are_the_common_denominator():
    primary = FakeLiveAdapter(capabilities=AdapterCapabilities(supports_images=True, native_vad=False))
    backup = FakeLiveAdapter(capabilities=AdapterCapabilities(supports_images=False, native_vad=False))
    caps = FallbackLiveAdapter(primary=primary, fallback=backup).capabilities
    assert caps.supports_images is False
    assert (caps.input_sample_rate, caps.output_sample_rate) == (16_000, 24_000)


def test_capabilities_without_fallback_are_the_primary_s():
    caps = AdapterCapabilities(supports_images=True)
    assert FallbackLiveAdapter(primary=FakeLiveAdapter(capabilities=caps)).capabilities == caps


def test_mismatched_sample_rates_fail_at_construction():
    primary = FakeLiveAdapter(capabilities=AdapterCapabilities(output_sample_rate=24_000))
    backup = FakeLiveAdapter(capabilities=AdapterCapabilities(output_sample_rate=16_000))
    with pytest.raises(ValueError, match="different audio sample rates"):
        FallbackLiveAdapter(primary=primary, fallback=backup)


def test_mismatched_native_vad_fails_at_construction():
    primary = FakeLiveAdapter(capabilities=AdapterCapabilities(native_vad=True))
    backup = FakeLiveAdapter(capabilities=AdapterCapabilities(native_vad=False))
    with pytest.raises(ValueError, match="native_vad"):
        FallbackLiveAdapter(primary=primary, fallback=backup)


async def test_activity_signals_reach_the_active_provider():
    """Regression: these were called on the fallback wrapper, which did not have them."""
    primary = FakeLiveAdapter()
    adapter = FallbackLiveAdapter(primary=primary)
    async with adapter.open_session("p") as session:
        await session.send_activity_start()
        await session.send_activity_end()
    assert primary.activity == ["start", "end"]


async def test_activity_signals_outside_a_session_raise():
    with pytest.raises(RuntimeError, match="no active session"):
        await FallbackLiveAdapter(primary=FakeLiveAdapter()).send_activity_start()


async def test_send_image_to_provider_without_support_raises_capability_error():
    adapter = FallbackLiveAdapter(primary=FakeLiveAdapter())
    async with adapter.open_session("p") as session:
        with pytest.raises(CapabilityNotSupported):
            await session.send_image(b"\xff\xd8")


async def test_session_ending_event_passes_through():
    event = ("session_ending", {"reason": "provider_go_away"})
    primary = FakeLiveAdapter(events=[event])
    adapter = FallbackLiveAdapter(primary=primary)
    async with adapter.open_session("p") as session:
        assert [e async for e in session.receive()] == [event]


# ── Early failover (primary opens, then fails before producing any output)


async def test_early_receive_failure_fails_over_and_replays_opening_message():
    """Regression: an API error on the first receive() used to end the session."""
    primary = FakeLiveAdapter(events=[RuntimeError("beta_api_shape_disabled")])
    backup = FakeLiveAdapter(events=[("audio", b"hello"), ("turn_complete", None)])
    adapter = FallbackLiveAdapter(primary=primary, fallback=backup)

    async with adapter.open_session("prompt", tools=[ToolSpec(name="t")]) as session:
        await session.send_client_content("opening context")
        got = [e async for e in session.receive()]

    assert got == [("audio", b"hello"), ("turn_complete", None)]
    assert backup.open_args == ("prompt", [ToolSpec(name="t")])
    assert backup.content == ["opening context"]  # replayed
    assert primary.closed_count == 1  # failed primary was torn down
    assert backup.closed_count == 1


async def test_sends_after_failover_go_to_the_fallback():
    primary = FakeLiveAdapter(events=[ConnectionError("dropped")])
    backup = FakeLiveAdapter()
    adapter = FallbackLiveAdapter(primary=primary, fallback=backup)
    async with adapter.open_session("p") as session:
        [e async for e in session.receive()]
        await session.send_audio(b"x")
        await session.send_activity_end()
    assert backup.audio == [b"x"] and backup.activity == ["end"]
    assert primary.audio == []


async def test_failure_after_output_is_not_failed_over():
    primary = FakeLiveAdapter(events=[("audio", b"a"), RuntimeError("mid-call")])
    backup = FakeLiveAdapter(events=[("audio", b"never")])
    adapter = FallbackLiveAdapter(primary=primary, fallback=backup)
    async with adapter.open_session("p") as session:
        got = []
        with pytest.raises(RuntimeError, match="mid-call"):
            async for event in session.receive():
                got.append(event)
    assert got == [("audio", b"a")]
    assert backup.open_args is None  # fallback never opened


async def test_early_failure_without_fallback_propagates():
    adapter = FallbackLiveAdapter(primary=FakeLiveAdapter(events=[RuntimeError("boom")]))
    async with adapter.open_session("p") as session:
        with pytest.raises(RuntimeError, match="boom"):
            [e async for e in session.receive()]


async def test_no_second_failover_when_session_already_opened_on_fallback():
    primary = FakeLiveAdapter(fail_open=ValueError("down"))
    backup = FakeLiveAdapter(events=[RuntimeError("also broken")])
    adapter = FallbackLiveAdapter(primary=primary, fallback=backup)
    async with adapter.open_session("p") as session:
        with pytest.raises(RuntimeError, match="also broken"):
            [e async for e in session.receive()]


async def test_failover_failure_reports_both_errors_and_leaves_no_active_session():
    primary = FakeLiveAdapter(events=[RuntimeError("primary broke")])
    backup = FakeLiveAdapter()
    adapter = FallbackLiveAdapter(primary=primary, fallback=backup)
    async with adapter.open_session("p") as session:
        backup.fail_open = ValueError("backup down")  # the backup is only opened during failover
        with pytest.raises(RuntimeError, match="could not open: backup down"):
            [e async for e in session.receive()]
    assert adapter._active is None


async def test_senders_wait_while_the_failover_is_in_progress():
    import asyncio

    gate = asyncio.Event()

    class SlowBackup(FakeLiveAdapter):
        def open_session(self, system_prompt, tools=None):
            outer = super().open_session(system_prompt, tools)

            class C:
                async def __aenter__(self_):
                    await gate.wait()
                    return await outer.__aenter__()

                async def __aexit__(self_, *a):
                    await outer.__aexit__(*a)

            return C()

    primary = FakeLiveAdapter(events=[RuntimeError("early")])
    backup = SlowBackup(events=[("turn_complete", None)])
    adapter = FallbackLiveAdapter(primary=primary, fallback=backup)
    async with adapter.open_session("p") as session:
        receiver = asyncio.create_task(_drain(session))
        await asyncio.sleep(0.05)  # failover now blocked opening the backup
        sender = asyncio.create_task(session.send_audio(b"queued"))
        await asyncio.sleep(0.05)
        assert not sender.done()  # waiting, not crashing on a dead primary
        gate.set()
        await asyncio.wait_for(asyncio.gather(receiver, sender), timeout=2)
    assert backup.audio == [b"queued"]


async def _drain(session):
    return [e async for e in session.receive()]

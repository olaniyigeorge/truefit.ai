"""Response policy: confirm-before-execute guards and non-blocking tools."""

from __future__ import annotations

import asyncio

import pytest

from soro import ToolSpec
from soro.runtime.policy import (
    CONFIRM_INSTRUCTIONS,
    BackgroundTools,
    apply_policy,
    policy_instructions,
    require_confirmation,
)

pytestmark = pytest.mark.unit


def _spec(name, **props):
    return ToolSpec(name=name, description="Do it.",
                    parameters={"type": "object", "properties": props, "required": list(props)})


async def test_confirmation_guard_refuses_until_confirmed_and_strips_the_flag():
    ran = []

    async def delete(args):
        ran.append(args)
        return {"success": True}

    spec, guarded = require_confirmation(_spec("delete_note", id={"type": "string"}), delete)
    assert spec.parameters["properties"]["confirmed"]["type"] == "boolean"
    assert spec.parameters["required"] == ["id", "confirmed"]
    assert "confirmation" in spec.description

    refused = await guarded({"id": "1"})
    assert refused["needs_confirmation"] is True and ran == []
    assert (await guarded({"id": "1", "confirmed": False}))["success"] is False
    assert await guarded({"id": "1", "confirmed": True}) == {"success": True}
    assert await guarded({"id": "2", "confirmed": "true"}) == {"success": True}
    assert ran == [{"id": "1"}, {"id": "2"}]


async def test_background_tool_acks_at_once_and_reports_the_result_later():
    release = asyncio.Event()
    delivered: list[str] = []

    async def slow_search(args):
        await release.wait()
        return {"hits": 3}

    async def boom(args):
        raise RuntimeError("index offline")

    runner = BackgroundTools()
    runner.attach(lambda text: _append(delivered, text))
    _, start = runner.wrap(_spec("search"), slow_search)
    _, start_boom = runner.wrap(_spec("reindex"), boom)

    ack = await asyncio.wait_for(start({"q": "milk"}), 0.5)
    assert ack["status"] == "started" and runner.pending == 1
    assert delivered == []
    release.set()
    await start_boom({})
    await runner.wait()
    # Both arrive; their order is completion order, which the test does not fix.
    assert sorted(delivered) == [
        "[tool result] reindex failed: index offline",
        '[tool result] search finished: {"hits": 3}',
    ]


async def _append(out, text):
    out.append(text)


async def test_background_delivery_failure_is_swallowed_and_aclose_cancels():
    async def closed_session(text):
        raise RuntimeError("session closed")

    runner = BackgroundTools()
    runner.attach(closed_session)
    _, start = runner.wrap(_spec("quick"), _ok)
    await start({})
    await runner.wait()  # no exception escapes

    never = asyncio.Event()

    async def hang(args):
        await never.wait()

    _, start_hang = runner.wrap(_spec("hang"), hang)
    await start_hang({})
    assert runner.pending == 1
    await runner.aclose()
    assert runner.pending == 0


async def _ok(args):
    return {"success": True}


async def test_apply_policy_matches_patterns_and_layers_confirm_outside_background():
    runner = BackgroundTools()
    delivered: list[str] = []
    runner.attach(lambda t: _append(delivered, t))
    pairs = [(_spec("delete_note"), _ok), (_spec("search_web"), _ok), (_spec("read_note"), _ok)]
    wrapped = apply_policy(pairs, confirm=["delete_*", "search_web"], background=["search_*"], runner=runner)
    by_name = {s.name: s for s, _ in wrapped}
    handlers = {s.name: h for s, h in wrapped}

    assert "confirmed" in by_name["delete_note"].parameters["properties"]
    assert "confirmed" not in by_name["read_note"].parameters["properties"]
    # Unconfirmed background tool: refused before any task starts.
    assert (await handlers["search_web"]({}))["needs_confirmation"] is True
    assert runner.pending == 0
    assert (await handlers["search_web"]({"confirmed": True}))["status"] == "started"
    await runner.wait()
    assert delivered == ['[tool result] search_web finished: {"success": true}']


def test_background_without_runner_is_an_error():
    with pytest.raises(ValueError):
        apply_policy([(_spec("x"), _ok)], background=["x"])


def test_instructions_only_when_a_policy_applies():
    pairs = [(_spec("delete_note"), _ok)]
    assert policy_instructions(pairs, ["delete_*"], []) == CONFIRM_INSTRUCTIONS
    assert policy_instructions(pairs, ["other"], ["also_other"]) == ""
    assert "[tool result]" in policy_instructions(pairs, [], ["delete_note"])

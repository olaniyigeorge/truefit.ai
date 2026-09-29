import uuid

import pytest

from src.truefit_infra.realtime.audio_bridge import INPUT_SAMPLE_RATE, AudioBridge
from src.truefit_infra.realtime.session_context import SessionContext

pytestmark = pytest.mark.unit


def _ctx() -> SessionContext:
    return SessionContext(session_id="s1", job_id=uuid.uuid4(), candidate_id=uuid.uuid4())


def test_bridge_defaults_to_24k_agent_output():
    track = AudioBridge(context=_ctx()).create_outbound_track()
    assert track._input_sample_rate == 24_000


@pytest.mark.parametrize("rate", [16_000, 24_000, 44_100, 48_000])
def test_track_uses_the_declared_output_rate(rate):
    track = AudioBridge(context=_ctx(), output_sample_rate=rate).create_outbound_track()
    assert track._input_sample_rate == rate


def test_input_rate_constant_matches_the_adapter_contract():
    assert INPUT_SAMPLE_RATE == 16_000

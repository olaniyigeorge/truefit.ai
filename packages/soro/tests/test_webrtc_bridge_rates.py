
import pytest

pytest.importorskip("aiortc")

from soro.transport.webrtc import INPUT_SAMPLE_RATE, AudioBridge

pytestmark = pytest.mark.unit


def test_bridge_defaults_to_24k_agent_output():
    track = AudioBridge(session_id="s1").create_outbound_track()
    assert track._input_sample_rate == 24_000


@pytest.mark.parametrize("rate", [16_000, 24_000, 44_100, 48_000])
def test_track_uses_the_declared_output_rate(rate):
    track = AudioBridge(session_id="s1", output_sample_rate=rate).create_outbound_track()
    assert track._input_sample_rate == rate


def test_input_rate_constant_matches_the_adapter_contract():
    assert INPUT_SAMPLE_RATE == 16_000

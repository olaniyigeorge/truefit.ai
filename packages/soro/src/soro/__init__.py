"""
Soro: model-agnostic realtime voice agent infrastructure.

Write an agent once (a prompt, some tools, audio in and out) and run it on any
realtime model through the LiveSessionPort interface.
"""

from soro import connectors
from soro.adapters.factory import create_live_adapter
from soro.agent import Agent
from soro.connectors.functions import tool
from soro.errors import CapabilityNotSupported, SoroError
from soro.ports import LIVE_EVENT_TYPES, AdapterCapabilities, LiveSessionPort
from soro.runtime import (
    RuntimeCallbacks,
    SessionComplete,
    ToolRegistry,
    VoiceAgentRuntime,
)
from soro.tools import ToolSpec, normalize_tools

__version__ = "0.1.0"

__all__ = [
    "AdapterCapabilities",
    "Agent",
    "CapabilityNotSupported",
    "LIVE_EVENT_TYPES",
    "LiveSessionPort",
    "RuntimeCallbacks",
    "SessionComplete",
    "SoroError",
    "ToolRegistry",
    "ToolSpec",
    "VoiceAgentRuntime",
    "connectors",
    "create_live_adapter",
    "normalize_tools",
    "tool",
    "__version__",
]

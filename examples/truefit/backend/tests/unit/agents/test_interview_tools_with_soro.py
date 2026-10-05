"""The interview's tools must work on every provider Soro supports."""

import pytest
from soro import ToolRegistry, normalize_tools
from soro.adapters.gemini import _to_gemini_tools
from soro.adapters.openai import _to_openai_tools

from src.truefit_core.agents.interviewer.tools import INTERVIEW_TOOLS

pytestmark = pytest.mark.unit

EXPECTED = ["complete_interview", "flag_interrupt", "persist_answer", "record_question"]


def test_interview_tools_normalize_cleanly():
    assert sorted(s.name for s in normalize_tools(INTERVIEW_TOOLS)) == EXPECTED


def test_gemini_receives_every_interview_tool():
    (group,) = _to_gemini_tools(normalize_tools(INTERVIEW_TOOLS))
    assert sorted(d["name"] for d in group["function_declarations"]) == EXPECTED


def test_openai_can_translate_the_interview_tools():
    """Regression: the Gemini group shape used to be passed to OpenAI untouched."""
    tools = _to_openai_tools(normalize_tools(INTERVIEW_TOOLS))
    assert sorted(t["name"] for t in tools) == EXPECTED
    assert all(t["type"] == "function" and "function_declarations" not in t for t in tools)


def test_every_interview_tool_has_a_handler():
    from src.truefit_core.agents.interviewer.handlers import InterviewToolHandlers

    handlers = InterviewToolHandlers(
        interview_id=__import__("uuid").uuid4(),
        orchestration=None,
        queue=None,
        cache=None,
        stop_session=lambda reason: None,
    ).as_map()
    ToolRegistry.from_declarations(INTERVIEW_TOOLS, handlers)  # raises if they disagree

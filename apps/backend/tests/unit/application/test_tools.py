import pytest

from src.truefit_core.application.tools import ToolSpec, normalize_tools

pytestmark = pytest.mark.unit

PARAMS = {"type": "object", "properties": {"q": {"type": "string"}}}


def test_toolspec_defaults_to_empty_object_schema():
    assert ToolSpec(name="ping").parameters == {"type": "object", "properties": {}}


def test_toolspec_rejects_blank_name():
    with pytest.raises(ValueError):
        ToolSpec(name="  ")


def test_toolspec_default_schema_is_not_shared_between_instances():
    a, b = ToolSpec(name="a"), ToolSpec(name="b")
    a.parameters["properties"]["x"] = 1
    assert b.parameters["properties"] == {}


def test_normalize_none_and_empty():
    assert normalize_tools(None) == []
    assert normalize_tools([]) == []


def test_normalize_passes_specs_through():
    spec = ToolSpec(name="a", description="d", parameters=PARAMS)
    assert normalize_tools([spec]) == [spec]


def test_normalize_legacy_gemini_group_shape():
    legacy = [
        {"function_declarations": [
            {"name": "a", "description": "da", "parameters": PARAMS},
            {"name": "b", "description": "db"},
        ]}
    ]
    assert normalize_tools(legacy) == [
        ToolSpec(name="a", description="da", parameters=PARAMS),
        ToolSpec(name="b", description="db"),
    ]


def test_normalize_openai_style_function_dict():
    tool = {"type": "function", "name": "a", "description": "d", "parameters": PARAMS}
    assert normalize_tools([tool]) == [ToolSpec(name="a", description="d", parameters=PARAMS)]


def test_normalize_sdk_style_object():
    class Decl:
        name = "a"
        description = "d"

        class parameters:  # noqa: N801
            @staticmethod
            def model_dump(exclude_none=True):
                return PARAMS

    assert normalize_tools([Decl()]) == [ToolSpec(name="a", description="d", parameters=PARAMS)]


def test_normalize_rejects_duplicate_names_across_groups():
    with pytest.raises(ValueError, match="Duplicate tool names: \\['a'\\]"):
        normalize_tools([ToolSpec(name="a"), {"function_declarations": [{"name": "a"}]}])


def test_normalize_rejects_nameless_dict_and_unknown_types():
    with pytest.raises(ValueError):
        normalize_tools([{"description": "no name"}])
    with pytest.raises(TypeError):
        normalize_tools([42])


def test_interview_tools_normalize_cleanly():
    from src.truefit_core.agents.interviewer.tools import INTERVIEW_TOOLS

    names = [s.name for s in normalize_tools(INTERVIEW_TOOLS)]
    assert sorted(names) == ["complete_interview", "flag_interrupt", "persist_answer", "record_question"]

import json

import pytest

from distillation_replay.mock_tool import (
    ToolMockCache,
    build_tool_mock_prompt,
    normalize_arguments,
    parse_tool_mock_output,
)


def test_tool_mock_prompt_uses_sections_instead_of_one_big_json():
    prompt = build_tool_mock_prompt(
        tool_name="lookup",
        tool_schema={"type": "object", "properties": {"code": {"type": "string"}}},
        arguments={"code": "A1"},
        tool_examples=[{"arguments": {"code": "A0"}, "result": {"name": "item"}}],
        conversation_prior_mock_results=[],
    )

    assert "### Tool\n" in prompt
    assert "### Arguments\n" in prompt
    assert "### Tool Examples\n" in prompt
    assert "Each item has arguments and result." in prompt
    assert "generate only the raw tool result" in prompt
    assert "If examples are empty" in prompt
    assert "### Conversation Prior Mock Results\n" in prompt
    assert "### Context" not in prompt
    assert '"conversation_id"' not in prompt
    assert '"turn_index"' not in prompt
    assert '"conversation"' not in prompt
    assert '"meta"' not in prompt
    assert '"trace"' not in prompt
    assert "expected_tool" not in prompt
    assert "Rewrite Judge" not in prompt


def test_tool_mock_output_is_raw_result_not_wrapped_result():
    examples = [{"arguments": {"code": "A0"}, "result": {"status": "ok", "content": "value"}}]

    parsed = parse_tool_mock_output(
        '{"status":"ok","content":"mocked"}',
        examples,
    )

    assert parsed == {"status": "ok", "content": "mocked"}


def test_tool_mock_output_rejects_shape_mismatch():
    examples = [{"arguments": {"code": "A0"}, "result": {"status": "ok", "content": "value"}}]

    with pytest.raises(ValueError, match="shape mismatch"):
        parse_tool_mock_output('"just text"', examples)


def test_tool_mock_output_accepts_string_when_example_is_string():
    assert parse_tool_mock_output(
        '"mock text"',
        [{"arguments": {"query": "x"}, "result": "example text"}],
    ) == "mock text"


def test_tool_mock_cache_key_is_stable_for_same_arguments():
    cache = ToolMockCache()
    args_a = {"b": 2, "a": {"x": 1}}
    args_b = {"a": {"x": 1}, "b": 2}

    assert normalize_arguments(args_a) == normalize_arguments(args_b)
    cache.put("lookup", args_a, {"ok": True})
    assert cache.get("lookup", args_b) == {"ok": True}


def test_tool_mock_output_rejects_wrapper_when_example_is_not_wrapper():
    examples = [{"arguments": {"code": "A0"}, "result": {"status": "ok"}}]

    with pytest.raises(ValueError):
        parse_tool_mock_output(json.dumps({"result": {"status": "ok"}}), examples)


def test_tool_mock_output_rejects_empty_array_and_zero():
    with pytest.raises(ValueError, match="must not be empty"):
        parse_tool_mock_output("[]", [{"arguments": {"query": "x"}, "result": [{"title": "example"}]}])

    with pytest.raises(ValueError, match="must not be empty"):
        parse_tool_mock_output("0", [{"arguments": {"count": 1}, "result": 42}])


def test_tool_mock_output_validates_all_list_items():
    examples = [{"arguments": {"query": "x"}, "result": [{"title": "example"}]}]

    assert parse_tool_mock_output(
        json.dumps([{"title": "first"}, {"title": "second"}]),
        examples,
    ) == [{"title": "first"}, {"title": "second"}]

    with pytest.raises(ValueError, match="shape mismatch"):
        parse_tool_mock_output(json.dumps([{"title": "first"}, {"url": "missing title"}]), examples)


def test_tool_mock_output_accepts_non_empty_json_without_examples():
    assert parse_tool_mock_output('{"status":"ok","content":"schema-only"}', []) == {
        "status": "ok",
        "content": "schema-only",
    }

    with pytest.raises(ValueError, match="must not be empty"):
        parse_tool_mock_output("{}", [])

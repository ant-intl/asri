"""
Tests for tool_rule_deny_hook: resolve_path, evaluate_condition, ToolRuleDenyHook.
"""
import json

import pytest

from apps.agent.hooks.base import HookAction, HookResult
from apps.agent.hooks.tool_rule_deny_hook import (
    resolve_path,
    evaluate_condition,
    ToolRuleDenyHook,
)


# ====================================================================
# resolve_path
# ====================================================================


class TestResolvePath:
    """resolve_path(data, path) -> list"""

    def test_empty_path(self):
        data = {"a": 1, "b": 2}
        assert resolve_path(data, "") == [data]

    def test_simple_field(self):
        data = {"name": "hello", "other": "world"}
        assert resolve_path(data, "name") == ["hello"]

    def test_nested_field(self):
        data = {"a": {"b": {"c": 42}}}
        assert resolve_path(data, "a.b.c") == [42]

    def test_array_wildcard(self):
        data = {"arr": [{"f": 1}, {"f": 2}]}
        assert resolve_path(data, "arr.*.f") == [1, 2]

    def test_non_existent_path(self):
        data = {"a": 1}
        assert resolve_path(data, "b.c") == []

    def test_wildcard_on_non_list(self):
        """* on a dict item is silently skipped."""
        data = {"a": {"b": 1}}
        assert resolve_path(data, "a.*") == []

    def test_complex_nested_arrays(self):
        data = {"a": [{"b": [{"c": 1}, {"c": 2}]}]}
        assert resolve_path(data, "a.*.b.*.c") == [1, 2]

    def test_wildcard_in_middle(self):
        data = {"a": [{"b": 1}, {"b": 2}], "c": 3}
        assert resolve_path(data, "a.*.b") == [1, 2]

    def test_deeply_nested(self):
        data = {"x": [{"y": [{"z": [{"w": 1}]}]}]}
        assert resolve_path(data, "x.*.y.*.z.*.w") == [1]

    def test_partial_path_missing(self):
        """Returns empty list when path exists partway but final key is missing."""
        data = {"a": {"b": 1}}
        assert resolve_path(data, "a.b.c") == []

    def test_wildcard_then_key_missing(self):
        """Returns empty list when sub-key is missing after wildcard expansion."""
        data = {"arr": [{"f": 1}]}
        assert resolve_path(data, "arr.*.g") == []

    def test_empty_array(self):
        data = {"arr": []}
        assert resolve_path(data, "arr.*.f") == []

    def test_non_dict_item_in_array(self):
        """Non-dict items in array cannot have sub-fields accessed."""
        data = {"arr": [1, 2, 3]}
        assert resolve_path(data, "arr.*.f") == []

    def test_mixed_array_items(self):
        """Array contains both dicts and non-dicts."""
        data = {"arr": [{"f": 1}, 2, {"f": 3}]}
        assert resolve_path(data, "arr.*.f") == [1, 3]

    def test_top_level_wildcard(self):
        data = [{"f": 1}, {"f": 2}]
        # data is a list, not a dict; part='*' would trigger isinstance(list) branch
        # but the first split part won't be '*' so this tests the top-level being a list
        # Actually, let's test with a dict wrapper
        data = {"items": [{"f": 1}, {"f": 2}]}
        assert resolve_path(data, "items.*.f") == [1, 2]

    def test_path_does_not_start_at_root(self):
        data = {"a": {"b": {"c": 1}}}
        assert resolve_path(data, "x.y.z") == []

    def test_multiple_wildcards(self):
        data = {"a": [{"b": [{"c": 1}]}, {"b": [{"c": 2}]}]}
        assert resolve_path(data, "a.*.b.*.c") == [1, 2]


# ====================================================================
# evaluate_condition
# ====================================================================


class TestEvaluateCondition:
    """evaluate_condition(values, op, target) -> (violated, matched)"""

    # -- not_in (whitelist) --

    def test_not_in_violated(self):
        violated, matched = evaluate_condition(["unknown_tool"], "not_in", ["safe_tool"])
        assert violated is True
        assert matched == "unknown_tool"

    def test_not_in_allowed(self):
        violated, matched = evaluate_condition(["safe_tool"], "not_in", ["safe_tool", "another"])
        assert violated is False
        assert matched is None

    def test_not_in_multiple_values_one_violates(self):
        violated, matched = evaluate_condition(
            ["safe_tool", "unknown_tool"], "not_in", ["safe_tool"],
        )
        assert violated is True
        assert matched == "unknown_tool"

    # -- in (blacklist) --

    def test_in_violated(self):
        violated, matched = evaluate_condition(["bad_tool"], "in", ["bad_tool"])
        assert violated is True
        assert matched == "bad_tool"

    def test_in_allowed(self):
        violated, matched = evaluate_condition(["good_tool"], "in", ["bad_tool"])
        assert violated is False
        assert matched is None

    def test_in_multiple_values_one_violates(self):
        violated, matched = evaluate_condition(
            ["good_tool", "bad_tool"], "in", ["bad_tool"],
        )
        assert violated is True
        assert matched == "bad_tool"

    # -- contains (substring) --

    def test_contains_violated(self):
        violated, matched = evaluate_condition(["admin_delete"], "contains", ["delete"])
        assert violated is True
        assert matched == "admin_delete"

    def test_contains_allowed(self):
        violated, matched = evaluate_condition(["view_page"], "contains", ["delete"])
        assert violated is False
        assert matched is None

    def test_contains_multiple_keywords(self):
        violated, matched = evaluate_condition(
            ["execute_script"], "contains", ["delete", "script"],
        )
        assert violated is True
        assert matched == "execute_script"

    def test_contains_nested_keyword(self):
        violated, matched = evaluate_condition(
            ["very_bad_tool_name"], "contains", ["bad"],
        )
        assert violated is True
        assert matched == "very_bad_tool_name"

    # -- edge cases --

    def test_empty_values_list(self):
        violated, matched = evaluate_condition([], "not_in", ["x"])
        assert violated is False
        assert matched is None

    def test_non_string_conversion_in(self):
        """Numeric value 123 is converted via str() to '123' and matches string '123'."""
        violated, matched = evaluate_condition([123, 456], "in", ["123"])
        assert violated is True
        assert matched == "123"

    def test_non_string_conversion_not_in(self):
        violated, matched = evaluate_condition([789], "in", ["123"])
        assert violated is False
        assert matched is None

    def test_unknown_op(self):
        violated, matched = evaluate_condition(["val"], "unknown_op", ["x"])
        assert violated is False
        assert matched is None

    def test_empty_target_list_not_in(self):
        """Empty whitelist: all values are not in the list -> all trigger violation."""
        violated, matched = evaluate_condition(["anything"], "not_in", [])
        assert violated is True
        assert matched == "anything"

    def test_empty_target_list_in(self):
        """Empty blacklist: no values trigger violation."""
        violated, matched = evaluate_condition(["anything"], "in", [])
        assert violated is False
        assert matched is None

    def test_contains_empty_keywords(self):
        violated, matched = evaluate_condition(["value"], "contains", [])
        assert violated is False
        assert matched is None

    def test_none_value_in_values(self):
        """None is converted via str() to 'None'."""
        violated, matched = evaluate_condition([None], "in", ["None"])
        assert violated is True
        assert matched == "None"


# ====================================================================
# ToolRuleDenyHook
# ====================================================================


class TestToolRuleDenyHook:
    """ToolRuleDenyHook.on_tool_pre_execute integration tests."""

    # -- no rules / empty config --

    @pytest.mark.asyncio
    async def test_no_config(self, mock_agent_context):
        hook = ToolRuleDenyHook(config=None)
        result = await hook.on_tool_pre_execute("any_tool", "{}", mock_agent_context)
        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_empty_config(self, mock_agent_context):
        hook = ToolRuleDenyHook(config={})
        result = await hook.on_tool_pre_execute("any_tool", "{}", mock_agent_context)
        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_empty_rules_list(self, mock_agent_context):
        hook = ToolRuleDenyHook(config={"rules": []})
        result = await hook.on_tool_pre_execute("any_tool", "{}", mock_agent_context)
        assert result.action == HookAction.ALLOW

    # -- tool_name filtering --

    @pytest.mark.asyncio
    async def test_tool_name_mismatch_skips_rule(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "only-for-toolA",
                    "tool_name": "toolA",
                    "deny_message": "denied",
                    "conditions": [
                        {"path": "field", "op": "not_in", "value": ["safe"]},
                    ],
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute("toolB", '{"field": "unsafe"}', mock_agent_context)
        # Rule skipped because tool_name doesn't match
        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_no_tool_name_matches_all(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "match-all",
                    # no tool_name -> matches every tool
                    "deny_message": "denied {value}",
                    "conditions": [
                        {"path": "field", "op": "not_in", "value": ["safe"]},
                    ],
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute("any_tool", '{"field": "unsafe"}', mock_agent_context)
        assert result.action == HookAction.DENY

    # -- condition matching --

    @pytest.mark.asyncio
    async def test_single_condition_violated_denies(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "test-rule",
                    "tool_name": "mcpToolExecute",
                    "deny_message": "拒绝工具 {tool} 的参数值 {value}",
                    "conditions": [
                        {"path": "tool", "op": "not_in", "value": ["safe"]},
                    ],
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute(
            "mcpToolExecute", '{"tool": "unsafe"}', mock_agent_context,
        )
        assert result.action == HookAction.DENY
        assert "拒绝工具" in result.reason
        assert "mcpToolExecute" in result.reason
        assert "unsafe" in result.reason

    @pytest.mark.asyncio
    async def test_single_condition_not_violated_allows(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "test-rule",
                    "tool_name": "mcpToolExecute",
                    "deny_message": "denied",
                    "conditions": [
                        {"path": "tool", "op": "not_in", "value": ["safe", "unsafe"]},
                    ],
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute(
            "mcpToolExecute", '{"tool": "safe"}', mock_agent_context,
        )
        assert result.action == HookAction.ALLOW

    # -- multiple rules --

    @pytest.mark.asyncio
    async def test_multiple_rules_first_matches(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "rule1",
                    "tool_name": "toolA",
                    "deny_message": "rule1 denied {value}",
                    "conditions": [{"path": "field", "op": "not_in", "value": ["safe"]}],
                },
                {
                    "name": "rule2",
                    "tool_name": "toolB",
                    "deny_message": "rule2 denied {value}",
                    "conditions": [{"path": "field", "op": "not_in", "value": ["safe"]}],
                },
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute("toolA", '{"field": "bad"}', mock_agent_context)
        assert result.action == HookAction.DENY
        assert "rule1" in result.reason or "rule1 denied" in result.reason

    @pytest.mark.asyncio
    async def test_multiple_rules_second_matches(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "rule1",
                    "tool_name": "toolA",
                    "deny_message": "rule1 denied",
                    "conditions": [{"path": "field", "op": "not_in", "value": ["safe"]}],
                },
                {
                    "name": "rule2",
                    "tool_name": "toolB",
                    "deny_message": "rule2 denied {value}",
                    "conditions": [{"path": "field", "op": "not_in", "value": ["safe"]}],
                },
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute("toolB", '{"field": "bad"}', mock_agent_context)
        assert result.action == HookAction.DENY
        assert "rule2" in result.reason

    @pytest.mark.asyncio
    async def test_multiple_rules_no_match(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "rule1",
                    "tool_name": "toolA",
                    "conditions": [{"path": "field", "op": "not_in", "value": ["safe"]}],
                },
                {
                    "name": "rule2",
                    "tool_name": "toolB",
                    "conditions": [{"path": "field", "op": "not_in", "value": ["safe"]}],
                },
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute("toolC", '{"field": "bad"}', mock_agent_context)
        assert result.action == HookAction.ALLOW

    # -- deny_message formatting --

    @pytest.mark.asyncio
    async def test_deny_message_formatting(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "fmt-test",
                    "tool_name": "myTool",
                    "deny_message": "Tool {tool} rejected value {value}",
                    "conditions": [{"path": "x", "op": "not_in", "value": ["ok"]}],
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute("myTool", '{"x": "bad"}', mock_agent_context)
        assert result.action == HookAction.DENY
        assert result.reason == "Tool myTool rejected value bad"

    @pytest.mark.asyncio
    async def test_missing_deny_message_uses_default(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "no-msg",
                    "tool_name": "myTool",
                    "conditions": [{"path": "x", "op": "not_in", "value": ["ok"]}],
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute("myTool", '{"x": "bad"}', mock_agent_context)
        assert result.action == HookAction.DENY
        assert result.reason == "规则拒绝"

    # -- multiple conditions --

    @pytest.mark.asyncio
    async def test_multiple_conditions_first_violated(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "multi-cond",
                    "tool_name": "t",
                    "deny_message": "denied {value}",
                    "conditions": [
                        {"path": "a", "op": "not_in", "value": ["ok"]},
                        {"path": "b", "op": "not_in", "value": ["ok"]},
                    ],
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute(
            "t", '{"a": "bad", "b": "ok"}', mock_agent_context,
        )
        assert result.action == HookAction.DENY
        assert result.reason == "denied bad"

    @pytest.mark.asyncio
    async def test_multiple_conditions_all_pass(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "multi-cond-pass",
                    "tool_name": "t",
                    "deny_message": "denied",
                    "conditions": [
                        {"path": "a", "op": "not_in", "value": ["ok", "good"]},
                        {"path": "b", "op": "not_in", "value": ["ok", "good"]},
                    ],
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute(
            "t", '{"a": "ok", "b": "good"}', mock_agent_context,
        )
        assert result.action == HookAction.ALLOW

    # -- edge cases: arguments parsing --

    @pytest.mark.asyncio
    async def test_invalid_json_arguments(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "any-rule",
                    "conditions": [{"path": "x", "op": "not_in", "value": ["ok"]}],
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute("t", "not valid json", mock_agent_context)
        assert result.action == HookAction.DENY
        assert "工具参数格式无效" in result.reason

    @pytest.mark.asyncio
    async def test_empty_arguments_string(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "any-rule",
                    "conditions": [{"path": "x", "op": "not_in", "value": ["ok"]}],
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute("t", "", mock_agent_context)
        # Empty string parses as {}, resolve_path("x", {}) returns [], condition skipped
        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_resolve_path_returns_empty_skips_condition(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "skip-cond",
                    "tool_name": "t",
                    "conditions": [{"path": "nonexistent.path", "op": "not_in", "value": ["ok"]}],
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute("t", '{"other": "data"}', mock_agent_context)
        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_rule_without_conditions_key(self, mock_agent_context):
        config = {
            "rules": [
                {
                    "name": "no-conditions",
                    "tool_name": "t",
                    "deny_message": "should not trigger",
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute("t", "{}", mock_agent_context)
        assert result.action == HookAction.ALLOW

    # -- real-world scenarios --

    @pytest.mark.asyncio
    async def test_mcp_tool_whitelist_deny(self, mock_agent_context):
        """Simulate MCP tool whitelist scenario: unknown tool is denied."""
        config = {
            "rules": [
                {
                    "name": "mcp-whitelist",
                    "tool_name": "mcpToolExecute",
                    "deny_message": "MCP tool {value} is not allowed",
                    "conditions": [
                        {
                            "path": "mcpExecuteTools.*.mcpToolName",
                            "op": "not_in",
                            "value": ["kycSummaryQuery", "certifyFailReasonQuery"],
                        }
                    ],
                }
            ]
        }
        arguments = json.dumps({
            "mcpExecuteTools": [
                {"mcpToolName": "unknownTool", "args": {}},
            ]
        })
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute("mcpToolExecute", arguments, mock_agent_context)
        assert result.action == HookAction.DENY
        assert "unknownTool" in result.reason

    @pytest.mark.asyncio
    async def test_mcp_tool_whitelist_allow(self, mock_agent_context):
        """Simulate MCP tool whitelist scenario: whitelisted tool passes."""
        config = {
            "rules": [
                {
                    "name": "mcp-whitelist",
                    "tool_name": "mcpToolExecute",
                    "deny_message": "denied",
                    "conditions": [
                        {
                            "path": "mcpExecuteTools.*.mcpToolName",
                            "op": "not_in",
                            "value": ["kycSummaryQuery", "certifyFailReasonQuery"],
                        }
                    ],
                }
            ]
        }
        arguments = json.dumps({
            "mcpExecuteTools": [
                {"mcpToolName": "kycSummaryQuery", "args": {}},
            ]
        })
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute("mcpToolExecute", arguments, mock_agent_context)
        assert result.action == HookAction.ALLOW

    @pytest.mark.asyncio
    async def test_in_op_blacklist_deny(self, mock_agent_context):
        """Blacklist test: banned tool is matched."""
        config = {
            "rules": [
                {
                    "name": "blacklist",
                    "tool_name": "toolExecutor",
                    "deny_message": "工具 {value} 被禁止使用",
                    "conditions": [
                        {"path": "toolName", "op": "in", "value": ["delete_user", "drop_table"]},
                    ],
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute(
            "toolExecutor", '{"toolName": "delete_user"}', mock_agent_context,
        )
        assert result.action == HookAction.DENY
        assert "delete_user" in result.reason

    @pytest.mark.asyncio
    async def test_contains_op_deny(self, mock_agent_context):
        """Contains match test: argument contains sensitive keyword."""
        config = {
            "rules": [
                {
                    "name": "sensitive-content",
                    "tool_name": "searchTool",
                    "deny_message": "搜索内容包含敏感词: {value}",
                    "conditions": [
                        {"path": "query", "op": "contains", "value": ["password", "secret"]},
                    ],
                }
            ]
        }
        hook = ToolRuleDenyHook(config=config)
        result = await hook.on_tool_pre_execute(
            "searchTool", '{"query": "get_password_from_db"}', mock_agent_context,
        )
        assert result.action == HookAction.DENY
        assert "password" in result.reason or "get_password_from_db" in result.reason

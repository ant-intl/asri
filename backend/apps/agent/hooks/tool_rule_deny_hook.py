"""
ToolRuleDenyHook — Generic rules engine, a configuration-driven tool denial Hook.

Through configuring a rules list, matches tool_name + argument JSON Paths,
and directly denies execution when a rule is triggered (no user confirmation required).

Configuration (config_json):
    {
        "rules": [
            {
                "name": "rule name",
                "tool_name": "mcpToolExecute",   # optional, matches all tools if omitted
                "deny_message": "deny message {value}",
                "conditions": [
                    {
                        "path": "mcpExecuteTools.*.mcpToolName",  # JSON Path
                        "op": "not_in",                            # not_in / in / contains
                        "value": ["kycSummaryQuery", "certifyFailReasonQuery"]
                    }
                ]
            }
        ]
    }

Path syntax:
    "field"           → args["field"]                          # simple field
    "a.b.c"           → args["a"]["b"]["c"]                    # nested field
    "arr.*.field"     → args["arr"][i]["field"]                # array wildcard
"""
import json
import logging
from typing import Any

from .base import BaseHook, HookResult

logger = logging.getLogger(__name__)


# ─────────────────────────── PathResolver ───────────────────────────


def resolve_path(data: dict, path: str) -> list:
    """Resolve dot-notation path and return list of matched values.

    Supports:
        "field"           → [data["field"]]
        "a.b.c"           → [data["a"]["b"]["c"]]
        "arr.*.field"     → [data["arr"][0]["field"], data["arr"][1]["field"], ...]

    Args:
        data: dict to resolve (deserialized arguments).
        path: Dot-separated path expression.

    Returns:
        List of matched values. Returns empty list if path does not exist.
    """
    if not path:
        return [data]

    parts = path.split(".")
    current: list[Any] = [data]

    for part in parts:
        next_current: list[Any] = []
        for item in current:
            if part == "*":
                if isinstance(item, list):
                    next_current.extend(item)
                # ignore non-list items
            elif isinstance(item, dict) and part in item:
                next_current.append(item[part])
            # ignore non-matching path segments
        current = next_current
        if not current:
            return []

    return current


# ───────────────────────── ConditionEvaluator ───────────────────────


def evaluate_condition(values: list, op: str, target: list) -> tuple[bool, str | None]:
    """Evaluate whether a condition is triggered.

    Args:
        values: List of values extracted by resolve_path.
        op: Operator (not_in / in / contains).
        target: Target value list (whitelist/blacklist/keyword list).

    Returns:
        (is_violated, matched_value): Whether denial is triggered and the value that triggered it.
    """
    for val in values:
        val_str = str(val)

        if op == "not_in":
            # Whitelist: value not in list → trigger
            if val_str not in target:
                return True, val_str

        elif op == "in":
            # Blacklist: value in list → trigger
            if val_str in target:
                return True, val_str

        elif op == "contains":
            # Contains match: value contains any keyword → trigger
            for keyword in target:
                if keyword in val_str:
                    return True, val_str

    return False, None


# ─────────────────────────── ToolRuleDenyHook ───────────────────────


class ToolRuleDenyHook(BaseHook):
    """Generic tool denial Hook, matches tool_name + arguments based on configured rules.

    Rules have OR relationship: any single condition in any rule being triggered results in DENY.
    """

    hook_name = "tool_rule_deny"

    def __init__(self, config: dict | None = None) -> None:
        self._rules: list[dict] = (config or {}).get("rules", [])

    async def on_tool_pre_execute(
        self,
        tool_name: str,
        arguments: str,
        context,
    ) -> HookResult:
        # Parse arguments
        try:
            args = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            logger.warning("ToolRuleDenyHook: failed to parse arguments: %s", arguments[:200])
            return HookResult.deny("Tool arguments format invalid, denied")

        # Iterate rules
        for rule in self._rules:
            rule_name = rule.get("name", "")

            # Filter by tool_name
            rule_tool = rule.get("tool_name")
            if rule_tool and rule_tool != tool_name:
                continue

            # Iterate conditions
            for condition in rule.get("conditions", []):
                path = condition.get("path", "")
                op = condition.get("op", "")
                target = condition.get("value", [])

                values = resolve_path(args, path)
                if not values:
                    continue

                violated, matched = evaluate_condition(values, op, target)
                if violated:
                    msg = rule.get("deny_message", "Rule denied").format(
                        value=matched or "",
                        tool=tool_name,
                    )
                    logger.info(
                        "ToolRuleDenyHook: rule '%s' triggered, denied tool '%s' argument value '%s' (op=%s)",
                        rule_name, tool_name, matched, op,
                    )
                    return HookResult.deny(msg)

        return HookResult.allow()

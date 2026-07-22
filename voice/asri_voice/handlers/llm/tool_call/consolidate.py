"""Consolidate streaming tool call deltas into complete tool calls.

In streaming mode, the OpenAI API sends tool call data in incremental
deltas (partial id, name, arguments). This module groups them by index
and accumulates the fragments into complete tool call dicts.
"""

import logging

logger = logging.getLogger(__name__)


def _is_already_consolidated(deltas: list[dict]) -> bool:
    """Check if deltas are already complete (non-streaming path).

    A delta is considered complete if it has both function.name and
    function.arguments is non-empty (not None and not ""). We only need
    one to be complete to distinguish from streaming deltas (which have
    None/empty on first chunks).
    """
    if len(deltas) <= 1:
        return True
    # In streaming mode, early deltas have name=None or arguments=None/"".
    # In non-streaming mode, all deltas are complete.
    for d in deltas:
        fn = d.get("function", {})
        if fn.get("name") and fn.get("arguments") not in (None, ""):
            # This delta has both name and arguments — likely complete.
            # But streaming can also have this for the first chunk of a
            # single-argument tool. Check if we have duplicates by index.
            pass
        else:
            # Definitely a streaming delta (missing name or arguments).
            return False
    # All have name and arguments — check for duplicate indices.
    indices = [d.get("index") for d in deltas]
    if len(indices) != len(set(indices)):
        return False  # Duplicate indices = streaming deltas
    return True


def consolidate_tool_call_deltas(deltas: list[dict]) -> list[dict]:
    """Consolidate streaming tool call deltas into complete tool calls.

    In streaming mode, each delta chunk is appended separately.
    Group by 'index', accumulate id/function.name/function.arguments.

    Args:
        deltas: List of tool call delta dicts from streaming chunks.

    Returns:
        List of complete tool call dicts with full id, function.name,
        and function.arguments.
    """
    if not deltas:
        return []

    # Fast path: if all deltas have complete function.name and function.arguments,
    # they're already consolidated (non-streaming path).
    if _is_already_consolidated(deltas):
        return sorted(deltas, key=lambda d: d.get("index", 0))

    groups: dict[int, dict] = {}
    for d in deltas:
        idx = d.get("index", 0)
        if idx not in groups:
            groups[idx] = {
                "type": "function",
                "id": None,
                "function": {"name": "", "arguments": ""},
            }
        g = groups[idx]
        if d.get("id"):
            g["id"] = d["id"]
        fn = d.get("function", {})
        if fn.get("name"):
            g["function"]["name"] += fn["name"]
        if fn.get("arguments"):
            g["function"]["arguments"] += fn["arguments"]
        if d.get("type") and not g.get("type"):
            g["type"] = d["type"]

    return [groups[i] for i in sorted(groups.keys())]
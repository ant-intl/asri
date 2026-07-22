"""Offline distillation replay helpers.

This package is intentionally separate from the online speech pipeline.  It
contains deterministic data loading, virtual-time bookkeeping, and trace
rewriting helpers used by offline replay jobs.
"""

from .manifest import ManifestIndex, ManifestRecord
from .mock_tool import (
    ToolMockCache,
    build_tool_mock_prompt,
    normalize_arguments,
    parse_tool_mock_output,
)
from .sample_builder import (
    ResponseTurn,
    build_response_conversations,
    build_response_sample,
    build_response_user_value,
)
from .timeline import HeartbeatEvent, SnapshotState, ToolEvent, build_snapshot_state
from .tool_latency import (
    TOOL_LATENCY_TIERS,
    ToolLatencyTier,
    stable_tool_latency_tier,
    stable_virtual_tool_latency_ms,
)

__all__ = [
    "HeartbeatEvent",
    "ManifestIndex",
    "ManifestRecord",
    "SnapshotState",
    "ToolEvent",
    "TOOL_LATENCY_TIERS",
    "ToolLatencyTier",
    "ToolMockCache",
    "ResponseTurn",
    "build_snapshot_state",
    "build_response_conversations",
    "build_response_sample",
    "build_response_user_value",
    "build_tool_mock_prompt",
    "normalize_arguments",
    "parse_tool_mock_output",
    "stable_tool_latency_tier",
    "stable_virtual_tool_latency_ms",
]

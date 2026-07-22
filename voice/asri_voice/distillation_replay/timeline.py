from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class HeartbeatEvent:
    heartbeat_ref: str
    triggered_at_ms: int
    completed_at_ms: int
    output: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolEvent:
    tool_event_ref: str
    heartbeat_ref: str
    tool_name: str
    arguments: dict[str, Any]
    dispatched_at_ms: int
    tool_completed_at_ms: int
    result: Any | None = None
    mock_status: str = "completed"


@dataclass
class SnapshotState:
    snapshot_at_ms: int
    thinking_heartbeats: list[HeartbeatEvent] = field(default_factory=list)
    completed_heartbeats: list[HeartbeatEvent] = field(default_factory=list)
    pending_tools: list[ToolEvent] = field(default_factory=list)
    completed_tools: list[ToolEvent] = field(default_factory=list)
    late_tools: list[ToolEvent] = field(default_factory=list)


def build_snapshot_state(
    *,
    snapshot_at_ms: int,
    heartbeat_events: list[HeartbeatEvent],
    tool_events: list[ToolEvent],
    response_start_ms: int | None = None,
) -> SnapshotState:
    """Merge all prior heartbeat/tool events into the state visible at a snapshot."""
    state = SnapshotState(snapshot_at_ms=snapshot_at_ms)

    for event in sorted(heartbeat_events, key=lambda e: (e.triggered_at_ms, e.heartbeat_ref)):
        if event.triggered_at_ms <= snapshot_at_ms < event.completed_at_ms:
            state.thinking_heartbeats.append(event)
        elif event.completed_at_ms <= snapshot_at_ms:
            state.completed_heartbeats.append(event)

    for event in sorted(tool_events, key=lambda e: (e.dispatched_at_ms, e.tool_event_ref)):
        if event.mock_status != "completed":
            continue
        if response_start_ms is not None and event.tool_completed_at_ms > response_start_ms:
            if event.dispatched_at_ms <= snapshot_at_ms:
                state.late_tools.append(event)
            continue
        if event.dispatched_at_ms <= snapshot_at_ms < event.tool_completed_at_ms:
            state.pending_tools.append(event)
        elif event.tool_completed_at_ms <= snapshot_at_ms:
            state.completed_tools.append(event)

    return state

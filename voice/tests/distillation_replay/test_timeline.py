from distillation_replay.timeline import HeartbeatEvent, ToolEvent, build_snapshot_state


def test_snapshot_merges_all_prior_events_not_only_previous_one():
    heartbeats = [
        HeartbeatEvent("hb1", triggered_at_ms=500, completed_at_ms=700, output={"action": "think"}),
        HeartbeatEvent("hb2", triggered_at_ms=1000, completed_at_ms=1400, output={"action": "think"}),
        HeartbeatEvent("hb3", triggered_at_ms=1500, completed_at_ms=1900, output={"action": "think"}),
    ]
    tools = [
        ToolEvent("tool1", "hb1", "lookup", {}, dispatched_at_ms=700, tool_completed_at_ms=760, result="done"),
        ToolEvent("tool2", "hb2", "lookup", {}, dispatched_at_ms=1400, tool_completed_at_ms=1800, result="later"),
    ]

    state = build_snapshot_state(
        snapshot_at_ms=1600,
        heartbeat_events=heartbeats,
        tool_events=tools,
    )

    assert [event.heartbeat_ref for event in state.completed_heartbeats] == ["hb1", "hb2"]
    assert [event.heartbeat_ref for event in state.thinking_heartbeats] == ["hb3"]
    assert [event.tool_event_ref for event in state.completed_tools] == ["tool1"]
    assert [event.tool_event_ref for event in state.pending_tools] == ["tool2"]


def test_response_snapshot_excludes_late_tool_result():
    tools = [
        ToolEvent("tool1", "hb1", "lookup", {}, dispatched_at_ms=900, tool_completed_at_ms=1300, result="late"),
    ]

    state = build_snapshot_state(
        snapshot_at_ms=1400,
        heartbeat_events=[],
        tool_events=tools,
        response_start_ms=1200,
    )

    assert state.completed_tools == []
    assert [event.tool_event_ref for event in state.late_tools] == ["tool1"]

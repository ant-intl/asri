from distillation_replay.tool_latency import (
    TOOL_LATENCY_TIERS,
    stable_tool_latency_tier,
    stable_virtual_tool_latency_ms,
)


def _tool_name_for_tier(tier_name: str) -> str:
    for i in range(10_000):
        tool_name = f"tool_{tier_name}_{i}"
        if stable_tool_latency_tier(tool_name).name == tier_name:
            return tool_name
    raise AssertionError(f"could not find tool name for tier {tier_name}")


def test_stable_virtual_tool_latency_uses_tool_name_tiers() -> None:
    for tier in TOOL_LATENCY_TIERS:
        tool_name = _tool_name_for_tier(tier.name)
        latency_a = stable_virtual_tool_latency_ms(
            tool_name=tool_name,
            arguments={"query": "alpha"},
            salt="call-a",
        )
        latency_b = stable_virtual_tool_latency_ms(
            tool_name=tool_name,
            arguments={"query": "beta"},
            salt="call-b",
        )

        assert tier.min_ms <= latency_a <= tier.max_ms
        assert tier.min_ms <= latency_b <= tier.max_ms
        assert stable_tool_latency_tier(tool_name).name == tier.name


def test_stable_virtual_tool_latency_is_reproducible() -> None:
    first = stable_virtual_tool_latency_ms(
        tool_name="lookup_order",
        arguments={"order_id": "A1"},
        salt="heartbeat_1",
    )
    second = stable_virtual_tool_latency_ms(
        tool_name="lookup_order",
        arguments={"order_id": "A1"},
        salt="heartbeat_1",
    )

    assert first == second

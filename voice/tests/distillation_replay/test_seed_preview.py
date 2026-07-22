from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_seed_preview_module():
    path = REPO_ROOT / "scripts" / "distillation_seed_preview.py"
    spec = importlib.util.spec_from_file_location("distillation_seed_preview", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reformatted_row_uses_conversation_tool_trace_over_meta(tmp_path: Path) -> None:
    module = _load_seed_preview_module()
    obj = {
        "id": "conv_a_turn0_resp3",
        "audios": ["audio/turn0.wav"],
        "meta": {
            "message_index": 3,
            "target_tool_calls": [
                {"name": "wrong_tool", "arguments": {"wrong": True}},
            ],
        },
        "conversations": [
            {"role": "user", "content": "Check order ORD-7."},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "lookup_order",
                            "arguments": "{\"order_id\":\"ORD-7\"}",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_1",
                "name": "lookup_order",
                "content": "{\"status\":\"shipped\"}",
            },
            {"role": "assistant", "content": "Order ORD-7 has shipped."},
        ],
        "tools": [{"name": "lookup_order", "parameters": {"type": "object"}}],
    }
    args = argparse.Namespace(
        require_target_tool=False,
        require_tool_examples=False,
        examples_per_tool=8,
    )

    row = module._reformatted_to_row(tmp_path, tmp_path, "assistant_rewrite_v0", 1, obj, {}, args)

    assert row is not None
    assert row["target_tool_trace"] == [
        {
            "name": "lookup_order",
            "arguments": {"order_id": "ORD-7"},
            "tool_call_id": "call_1",
            "result": {"status": "shipped"},
        }
    ]
    assert row["tool_mock_examples"] == {
        "lookup_order": [
            {
                "arguments": {"order_id": "ORD-7"},
                "result": {"status": "shipped"},
            }
        ]
    }

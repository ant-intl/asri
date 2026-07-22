import json

from handlers.llm.tool_call.xml_tool_call import (
    extract_xml_tool_calls,
    tool_schemas_xml_system_block,
)
from handlers.allm.qwen3omni_handler import Qwen3OmniALLMHandler
from handlers.llm.chat import Chat


def test_extract_xml_tool_calls_returns_chat_api_format():
    text = (
        "Let me check that.\n"
        "<tool_call>\n"
        '{"name":"search_products","arguments":{"query":"camera","limit":2}}\n'
        "</tool_call>"
    )

    clean_text, tool_calls = extract_xml_tool_calls(text)

    assert clean_text == "Let me check that."
    assert len(tool_calls) == 1
    call = tool_calls[0]
    assert call["type"] == "function"
    assert call["function"]["name"] == "search_products"
    assert json.loads(call["function"]["arguments"]) == {"query": "camera", "limit": 2}
    assert call["id"].startswith("call_")


def test_tool_schemas_xml_system_block_uses_xml_instruction():
    block = tool_schemas_xml_system_block([
        {
            "type": "function",
            "function": {
                "name": "book_flight",
                "description": "Book a flight.",
                "parameters": {
                    "type": "object",
                    "properties": {"destination": {"type": "string"}},
                    "required": ["destination"],
                },
            },
        }
    ])

    assert "book_flight" in block
    assert "<tool_call>" in block
    assert '"name": <function-name>' in block


def test_qwen3omni_tool_history_uses_canonical_xml_and_cleans_role_prefix():
    assert Qwen3OmniALLMHandler._clean_spoken_response_text("assistant\nI found it.") == "I found it."
    assert Qwen3OmniALLMHandler._clean_spoken_response_text("</think>") == ""

    history = Qwen3OmniALLMHandler._render_assistant_tool_calls_for_history([
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "search_products",
                "arguments": '{"query":"hiking boots"}',
            },
        }
    ])

    assert 'Assistant Call for "Search Products"' not in history
    assert "<tool_call>" in history
    assert '"name": "search_products"' in history
    assert '"query": "hiking boots"' in history


def test_qwen3omni_empty_final_response_retries_before_finishing():
    handler = Qwen3OmniALLMHandler.__new__(Qwen3OmniALLMHandler)
    handler.max_agent_iterations = 2
    handler.chat = Chat(10)
    handler.tool_registry = None
    handler.cancel_scope = None
    handler._heartbeat_snapshot = []

    calls = iter([
        {
            "raw_text": "",
            "clean_text": "",
            "tool_calls": [],
            "input_tokens": 10,
            "output_tokens": 0,
            "cancelled": False,
            "ttft_ms": 1.0,
            "llm_total_ms": 2.0,
        },
        {
            "raw_text": "Retried answer.",
            "clean_text": "Retried answer.",
            "tool_calls": [],
            "input_tokens": 11,
            "output_tokens": 3,
            "cancelled": False,
            "ttft_ms": 1.0,
            "llm_total_ms": 2.0,
        },
    ])
    handler._call_omni_once = lambda _gen: next(calls)

    outputs = list(handler._process_with_xml_agent_loop(None, None))

    assert ("Retried answer.", None, [], None) in outputs
    assert any(item[0] == "__LLM_METRICS__" for item in outputs)
    assert handler.chat.buffer[-1] == {"role": "assistant", "content": "Retried answer."}


def test_qwen3omni_strips_audio_history_to_audio_placeholder():
    handler = Qwen3OmniALLMHandler.__new__(Qwen3OmniALLMHandler)
    handler.chat = Chat(10)
    handler.chat.append({
        "role": "user",
        "content": [
            {"type": "audio_url", "audio_url": {"url": "data:audio/wav;base64,abc"}},
            {"type": "text", "text": "\n### HeartbeatContext\n{}"},
        ],
    })

    handler._strip_audio_from_history()

    assert handler.chat.buffer[-1]["content"][0] == {"type": "text", "text": "<audio>"}
    assert "asr" not in str(handler.chat.buffer[-1]).lower()

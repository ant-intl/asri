"""Prompt template for Response-side HeartbeatContext injection."""

import json
from textwrap import dedent


def _clean(text: str) -> str:
    if text.startswith("\n"):
        text = text[1:]
    return dedent(text).rstrip()


HEARTBEAT_CONTEXT_TEMPLATE = """

{header}
{payload}

{usage}

{examples}"""


RESPONSE_HEARTBEAT_CONTEXT_V0_PROMPT = {
    "header": "### HeartbeatContext",
    "usage": _clean("""
        [HeartbeatContext usage]
        Use this JSON only as temporary context for the current response.
        Full user input has priority over prefix thinking.
        Thinking entries are prior same-turn judgments; use them only when they still match the full user input.
        Entry metadata is runtime context for the current turn. In FD mode, `interrupted_assistant_text` is the assistant sentence that had already reached the TTS playback path when the user started speaking. This identifies where the interruption happened; it is not user speech.
        FD interrupt gate notes describe the likely user behavior:
        - `interrupt_gate:respond`: the user intentionally interrupted, corrected, stopped, redirected, asked, or commanded. Follow the final user input.
        - `interrupt_gate:resume`: the user gave weak acknowledgement or backchannel. Do not answer it as a new request; continue or complete the interrupted answer naturally.
        - `interrupt_gate:ignore`: the speech is likely background, side conversation, or not addressed to the assistant. Do not answer that content.
        Completed tool results may be used as candidate facts when they answer the full user input.
        Pending tool calls and tool error states are not facts.
        Do not mention heartbeat, thinking entries, tool status, or internal state to the user.
    """),
    "examples": _clean("""
        [HeartbeatContext examples]
        - Full input confirms an earlier completed lookup still matches:
          Use the completed result as supporting context for the user-visible answer.

        - Full input corrects or replaces an earlier prefix interpretation:
          Ignore the stale thinking entry and answer from the full input.

        - HeartbeatContext contains only pending or error tool states:
          Do not present them as facts. If the final request still needs the tool, issue the normal response-stage tool call.

        - HeartbeatContext contains a blocked or proposed tool call:
          Treat it as an unexecuted suggestion, not a result. If needed and allowed, the main assistant should call the tool itself.
    """),
    "blocked_tool_note": _clean("""
        HeartBeat Thinking proposed the tool call above, but it was not executed.
        If the final user request still needs this action and the main assistant is allowed,
        the main assistant should issue the structured tool call itself.
    """),
}


def render_context(context_payload: dict) -> str:
    return HEARTBEAT_CONTEXT_TEMPLATE.format(
        header=RESPONSE_HEARTBEAT_CONTEXT_V0_PROMPT["header"],
        payload=json.dumps(context_payload, ensure_ascii=False, indent=2),
        usage=RESPONSE_HEARTBEAT_CONTEXT_V0_PROMPT["usage"],
        examples=RESPONSE_HEARTBEAT_CONTEXT_V0_PROMPT["examples"],
    )

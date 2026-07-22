"""Generic prompt template for ASRI HeartBeat Thinking."""

from copy import deepcopy

from handlers.heartbeat_interaction.prompt_templates.thinking_asri_v0 import (
    THINKING_ASRI_V0_PROMPT,
    USER_PROMPT_TEMPLATE,
    _clean,
    _extra_section,
    _runtime_sections,
)


THINKING_ASRI_GENERIC_V0_PROMPT = deepcopy(THINKING_ASRI_V0_PROMPT)
THINKING_ASRI_GENERIC_V0_PROMPT.update(
    {
        "system": "You are an incremental HeartBeat Thinking worker for a general real-time voice assistant.",
        "task": _clean("""
            [Task]
            You listen to the user's speech through partial ASR text. After each fixed interval, decide whether the new fragment contains stable information that is useful for the final assistant response.

            You will receive:
            - `### Conversation History`: conversation history before the current user turn.
            - `### Current Turn State`: same-turn HeartBeat Thinking entries, tool status, and tool results.
            - `### Current Fragment`: the current cumulative partial ASR transcript.

            Do only incremental work. If previous HeartBeat Thinking entries or tools already cover the fragment, or the fragment is filler, repetition, or an unfinished phrase with no stable signal, return `{"action":"noop"}`.
        """),
        "business_background": _clean("""
            [Assistant background]
            The assistant is a general real-time voice assistant, not tied to any fixed domain or workflow. The available tools are provided dynamically in the `[Tools]` section of each request. Use the injected schema as-is. Do not add domain or business rules that are not present in the schema.
        """),
    }
)


def render_user_prompt(
    *,
    tools_block: str,
    history_body: str,
    current_fragment: str,
    time_range: str,
    current_turn_state: str | None = None,
    current_turn_metadata: dict | None = None,
    extra_instructions: str | None = None,
    mode: str = "text",
) -> str:
    history_section, turn_state_section, metadata_section, fragment_section = _runtime_sections(
        history_body=history_body,
        current_fragment=current_fragment,
        time_range=time_range,
        current_turn_state=current_turn_state,
        current_turn_metadata=current_turn_metadata,
        mode=mode,
    )
    return USER_PROMPT_TEMPLATE.format(
        task=THINKING_ASRI_GENERIC_V0_PROMPT["task"],
        business_background=THINKING_ASRI_GENERIC_V0_PROMPT["business_background"],
        tools_block=tools_block,
        decision_policy=THINKING_ASRI_GENERIC_V0_PROMPT["decision_policy"],
        history_usage=THINKING_ASRI_GENERIC_V0_PROMPT["history_usage"],
        argument_rules=THINKING_ASRI_GENERIC_V0_PROMPT["argument_rules"],
        output_format=THINKING_ASRI_GENERIC_V0_PROMPT["output_format"],
        examples=THINKING_ASRI_GENERIC_V0_PROMPT["examples"],
        extra_section=_extra_section(extra_instructions),
        history_section=history_section,
        turn_state_section=turn_state_section,
        fragment_section=metadata_section + fragment_section,
    )

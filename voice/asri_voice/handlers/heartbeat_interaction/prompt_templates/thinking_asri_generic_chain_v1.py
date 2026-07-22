"""Generic chain-stable prompt template for ASRI HeartBeat Thinking."""

from copy import deepcopy

from handlers.heartbeat_interaction.prompt_templates.thinking_asri_generic_v0 import (
    THINKING_ASRI_GENERIC_V0_PROMPT,
    USER_PROMPT_TEMPLATE,
    _clean,
    _extra_section,
    _runtime_sections,
)


GENERIC_CHAIN_DECISION_POLICY = _clean("""
    [Generic chain-stable policy]
    These rules keep the prompt generic while improving real-time multi-step tasks:
    - Preserve every user-requested subtask in order. When a fragment contains a lookup followed by a downstream action, write the thinking note so the final response can finish the whole chain instead of stopping at the first lookup.
    - If a completed same-turn tool result clearly identifies the target for a downstream requested action, use that result. Do not ask the user to repeat an identifier, address, item, account, record, or target when a valid result already provides a usable value.
    - Treat natural references such as "whatever you find", "the first one", "from there", "once you find something", "that one", "the result", and "the item" as result references. They should usually trigger the downstream tool after the lookup result exists.
    - For location-like requests, a place description or result reference is a usable string when no exact street address is available and the schema accepts a string. Use the best available concrete value rather than asking for a more specific address by default.
    - Do not execute write/action tools from a partial identifier, amount, date, or quantity. Wait until the latest fragment no longer looks like a prefix or self-correction.
    - For alphanumeric identifiers spoken with separators, compact only the final stable identifier. Do not emit calls for intermediate prefixes such as P8, P889, BOB1, or P52 before the user has finished the identifier.
    - If the user corrects themselves, the latest stable correction wins and supersedes earlier same-turn thinking, pending calls, and completed calls with the wrong argument.
    - Never hard-fill an unknown argument just to satisfy a schema. Do not use placeholders, generic field names, zero, one, or guessed defaults for fields the user did not provide.
    - For unsupported subtasks inside a larger request, keep the supported tool-backed subtasks. Do not invent a tool for the unsupported part, and do not let it block valid calls.
""")

GENERIC_CHAIN_ARGUMENT_RULES = _clean("""
    [Generic argument discipline]
    - Prefer exact user wording or exact tool-result values for tool arguments. Normalize only when the schema clearly expects the normalized form.
    - Convert spoken IDs to compact canonical IDs only after they are stable, such as P dash five dash two to P52, G G five to GG5, and M one to M1.
    - Convert spoken quantities, dates, and amounts carefully. Use the number or normalized value only when the user's intent is stable.
    - For enum-like values, use the schema's canonical token when the schema or a prior valid result clearly indicates it.
    - If a lookup result returns an id or result list and the user requested a downstream action on that result, use the returned id for the downstream call when the downstream schema asks for an id.
    - If a lookup result lacks a dedicated id but contains a usable descriptive value, use that descriptive value rather than asking the user again.
    - Do not include unsupported optional arguments. Extra plausible filters can hurt precision when the user did not ask for them.
""")

THINKING_ASRI_GENERIC_CHAIN_V1_PROMPT = deepcopy(THINKING_ASRI_GENERIC_V0_PROMPT)
THINKING_ASRI_GENERIC_CHAIN_V1_PROMPT.update(
    {
        "decision_policy": "\n\n".join(
            [
                THINKING_ASRI_GENERIC_V0_PROMPT["decision_policy"],
                GENERIC_CHAIN_DECISION_POLICY,
            ]
        ),
        "argument_rules": "\n\n".join(
            [
                THINKING_ASRI_GENERIC_V0_PROMPT["argument_rules"],
                GENERIC_CHAIN_ARGUMENT_RULES,
            ]
        ),
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
        task=THINKING_ASRI_GENERIC_CHAIN_V1_PROMPT["task"],
        business_background=THINKING_ASRI_GENERIC_CHAIN_V1_PROMPT["business_background"],
        tools_block=tools_block,
        decision_policy=THINKING_ASRI_GENERIC_CHAIN_V1_PROMPT["decision_policy"],
        history_usage=THINKING_ASRI_GENERIC_CHAIN_V1_PROMPT["history_usage"],
        argument_rules=THINKING_ASRI_GENERIC_CHAIN_V1_PROMPT["argument_rules"],
        output_format=THINKING_ASRI_GENERIC_CHAIN_V1_PROMPT["output_format"],
        examples=THINKING_ASRI_GENERIC_CHAIN_V1_PROMPT["examples"],
        extra_section=_extra_section(extra_instructions),
        history_section=history_section,
        turn_state_section=turn_state_section,
        fragment_section=metadata_section + fragment_section,
    )

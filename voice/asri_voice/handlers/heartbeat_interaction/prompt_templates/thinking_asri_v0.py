"""Prompt template for ASRI HeartBeat Thinking."""

import json
from textwrap import dedent


def _clean(text: str) -> str:
    if text.startswith("\n"):
        text = text[1:]
    return dedent(text).rstrip()


USER_PROMPT_TEMPLATE = """{task}

{business_background}

[Tools]
{tools_block}
{decision_policy}

{history_usage}

{argument_rules}

{output_format}

{examples}

{extra_section}{history_section}{turn_state_section}{fragment_section}"""


THINKING_ASRI_V0_PROMPT = {
    "system": "You are an incremental HeartBeat Thinking worker for a general tool-enabled voice support agent.",
    "task": _clean("""
        [Task]
        You listen to the customer's speech through partial ASR text. After each fixed interval, decide whether the new fragment contains stable information that is useful for the final assistant response.

        You will receive:
        - `### Conversation History`: conversation history before the current user turn.
        - `### Current Turn State`: same-turn HeartBeat Thinking entries, tool status, and tool results.
        - `### Current Fragment`: the current cumulative partial ASR transcript.

        Do only incremental work. If previous HeartBeat Thinking entries or tools already cover the fragment, or the fragment is filler, repetition, or an unfinished phrase with no stable signal, return `{"action":"noop"}`.
    """),
    "business_background": _clean("""
        [Business background]
        The available tools are provided dynamically in the `[Tools]` section of each request. Use the injected schema as-is. Do not add tool business rules that are not present in the schema.
    """),
    "tools": [],
    "decision_policy": _clean("""
        [Decision policy]

        Context usage:
        - Use `### Conversation History` to resolve cross-turn references, omissions, and follow-up context. Do not act from history alone.
        - Use `### Current Turn State` to understand existing same-turn thinking entries, tool status, and tool results.
        - Use `### Current Fragment` as the source of new stable information for this heartbeat.

        First classify the relation between `### Current Fragment` and the existing context:
        - `new`: the fragment adds a stable intent, entity, constraint, or question.
        - `refined`: the fragment adds a more specific constraint such as location, time, target, or quantity.
        - `repeated`: the fragment repeats information already covered by a thinking entry.
        - `superseded`: the fragment changes, narrows, replaces, or contradicts an earlier thinking entry or tool result.
        - `unstable`: the current fragment is obviously incomplete, such as ending after `is`, `number`, `ID`, `for`, or a half-spoken entity.

        Tool status:
        - `pending` applies only to tool calls. A pending tool call is in-flight and is not a fact.
        - `completed` applies only to tool calls. A completed tool result is a candidate fact only if it still matches the current fragment.
        - `error` applies only to tool calls. A tool error is failed feedback, not a business fact.

        First decide `action`:
        - `noop`: the fragment is `repeated`, `unstable`, only filler, or adds no useful stable information beyond previous HeartBeat Thinking entries/tools.
        - `think`: the fragment is `new`, `refined`, or `superseded`, and should be preserved for the final response or can safely enter tool judgment.

        When `action` is `think`, write `thinking` as a short operational note for the main LLM:
        - Maximum length: 30 Chinese characters, or 12 English words.
        - Summarize only the new incremental interpretation.
        - Do not write hidden step-by-step reasoning or private chain-of-thought.
        - If the only useful note is to wait for more speech, return `{"action":"noop"}` instead.

        Tool decisions:
        - Choose a tool only from the injected `[Tools]` section.
        - Tool names must exactly copy one injected `[Tools]` heading, including case, underscores, dots, and prefixes. Do not translate, shorten, expand, alias, or rename a tool.
        - Before writing any tool call, identify the exact `[Tools]` heading you will copy. If you cannot copy an exact heading, leave `tools` empty.
        - Tool arguments must exactly use keys defined by that tool's `Parameters.properties`. Do not rename argument keys, add unsupported keys, or move values into a semantically similar key.
        - Do not infer tool behavior beyond the injected schema.
        - Use a tool when the current fragment contains a clear intent and all required arguments are present, unless an argument is obviously unfinished in the current fragment.
        - When a matching tool has no required arguments and the current fragment clearly asks for that tool's information, emit that tool with `{}` arguments.
        - When a matching tool's required arguments are stable and present, emit the tool call. A thinking-only response is not enough in that case.
        - Do not infer ASR stability from earlier raw fragments that are not present in the input. Use `### Current Turn State` to avoid repeated thinking or repeated tool work, not to reconstruct raw ASR history.
        - For ASR-sensitive values such as verification codes, order IDs, payment digits, phone numbers, emails, addresses, dates, and named entities, do not apply extra waiting rules beyond the current-fragment unfinishedness check.
        - If the intent is clear but required arguments are missing or obviously unfinished, write a short thinking entry and use an empty tools array.
        - Do not invent tool names, argument names, enum values, IDs, dates, locations, or other parameters not supported by the injected schema.
        - Do not use placeholder values such as `pending`, `unknown`, `now`, `0`, empty arrays, empty objects, or guessed identifiers to satisfy required arguments.
        - Schema `default` values are examples or service defaults, not facts from the user. Do not copy a default value into a tool argument unless the user actually said it or the conversation history already established it.
        - If an argument comes from the last word or phrase at the end of the current fragment and is obviously unfinished, do not emit a tool yet. This is especially important for company names, ticker symbols, person names, locations, IDs, dates, and product names.
        - Do not treat a prefix of an entity as stable. For example, `for Mi` is not enough to call a stock tool; wait until the entity is complete, such as `for Microsoft`.
        - Separate argument values from surrounding labels, discourse markers, and recognition artifacts. If the boundary between a label and its value is unclear, malformed, or only partially heard, leave `tools` empty.
        - Fill each tool argument from the matching semantic role in the user's request. Do not move a value from one role into another role just because the target parameter has the same type.
        - When the user is correcting, replacing, or clarifying earlier information, scope the correction to the affected role. Do not mix old and new values for a tool call unless the current fragment or conversation history clearly confirms each required role.
        - Do not call a tool with an obviously partial numeric ID just because it matches the parameter type.
        - If previous same-turn thinking already covers the fragment and there is no new stable information, return `{"action":"noop"}`.
    """),
    "history_usage": _clean("""
        [Context usage]
        `### Conversation History` is for reference resolution and follow-up context. It does not trigger actions by itself.
        `### Current Turn State` is for current-turn records: thinking entries, tool status, and tool results. A thinking entry is used to judge whether the current fragment is already covered. Tool `pending`, `completed`, and `error` are tool-call states only.
        `### Current Fragment` is the source of new stable information. Use history to resolve references first, then decide whether the fragment relation is `new`, `refined`, `repeated`, `superseded`, or `unstable`.
    """),
    "argument_rules": _clean("""
        [Argument rules]
        - Match the selected tool schema before emitting a tool call: exact tool name, exact argument keys, required keys present, and no unsupported argument keys.
        - If the schema requires no arguments, use `{}`. Do not invent placeholder arguments.
        - Fill only arguments that are present, implied by conversation history, or directly inferable from the current fragment.
        - Required arguments must be present and not obviously unfinished before a tool is emitted. A half-spoken entity, ambiguous reference, or unfinished constraint is not usable.
        - Optional arguments that identify the target, such as `id`, `is_id`, `property_id`, `order_id`, `task_id`, `ticker`, `domain`, `restaurant`, or `items`, must follow the same stability rules as required arguments.
        - A required argument is not usable if it is the current fragment's trailing partial token or trailing partial phrase.
        - A required numeric argument is not usable if it is immediately preceded by words like `is`, `number`, `ID`, or `for` and the fragment ends there.
        - Do not include labels, discourse markers, or malformed recognition artifacts inside identifier arguments.
        - Do not combine arguments from incompatible semantic roles. Every required argument must be supported by the current fragment or by unambiguous conversation history for that same role.
        - Optional arguments should be included only when they add useful precision.
        - Preserve user-provided identifiers, names, dates, and numbers exactly unless the tool schema clearly requires normalization.
    """),
    "output_format": _clean("""
        [Output format (STRICT)]
        Return one JSON object.

        For no new stable information, return exactly:
        {"action":"noop"}

        For useful new thinking, return exactly these three keys:
        - `"action"`: `"think"`.
        - `"thinking"`: string, max 30 Chinese characters or 12 English words.
        - `"tools"`: array of tool calls. Each item is `{"name": "...", "arguments": {...}}`. Use an empty array when there is no tool call.

        No markdown fences, no explanation, no extra keys.
        Never return an empty message. Never return action values other than `"noop"` or `"think"`.

        Format:
        {"action":"think", "thinking":"...", "tools":[...]}
    """),
    "examples": _clean("""
        [Examples]
        - Current fragment ends before a required value is complete:
          {"action":"think","thinking":"用户想查订单但编号未说完","tools":[]}

        - Current fragment has clear intent and present required arguments for an injected tool:
          {"action":"think","thinking":"用户提供订单号并请求查询","tools":[{"name":"get_order_status","arguments":{"order_id":"FD34567"}}]}

        - Argument boundary unclear: `I'm calling about order hashtag`:
          {"action":"think","thinking":"用户提到目标但参数未清楚","tools":[]}

        - Argument boundary unclear: `I'm calling about order hasag3`:
          {"action":"think","thinking":"用户提到订单但编号不清","tools":[]}

        - Semantic role mismatch: user says `User ID SENIOR500, Order ID ORD1040`, but the tool requires guest `confirmation_number` and `payment_digits`:
          {"action":"think","thinking":"用户提供用户ID和订单ID","tools":[]}

        - Correction scope: user is replacing a placeholder confirmation number and has only said `actual confirmation number is A987`:
          {"action":"think","thinking":"用户正在更正确认号","tools":[]}

        - Current fragment repeats an already covered concern:
          {"action":"noop"}
    """),
}


def _extra_section(extra_instructions: str | None) -> str:
    if not extra_instructions or not extra_instructions.strip():
        return ""
    return f"[Extra Instructions]\n{extra_instructions.strip()}\n\n"


def _runtime_sections(
    *,
    history_body: str,
    current_fragment: str,
    time_range: str,
    current_turn_state: str | None,
    current_turn_metadata: dict | None = None,
    mode: str = "text",
) -> tuple[str, str, str, str]:
    metadata_section = ""
    if current_turn_metadata:
        metadata_section = (
            "### Current Turn Metadata\n"
            f"{json.dumps(current_turn_metadata, ensure_ascii=False, indent=2)}\n\n"
        )
    if mode == "audio":
        fragment_section = f"### Current Fragment\n{current_fragment}\n{time_range}"
    else:
        fragment_section = f"### Current Fragment\n<asr>{current_fragment}</asr>\n{time_range}"

    return (
        f"### Conversation History\n{history_body or '(empty)'}\n\n",
        f"### Current Turn State\n{current_turn_state or '{}'}\n\n",
        metadata_section,
        fragment_section,
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
        task=THINKING_ASRI_V0_PROMPT["task"],
        business_background=THINKING_ASRI_V0_PROMPT["business_background"],
        tools_block=tools_block,
        decision_policy=THINKING_ASRI_V0_PROMPT["decision_policy"],
        history_usage=THINKING_ASRI_V0_PROMPT["history_usage"],
        argument_rules=THINKING_ASRI_V0_PROMPT["argument_rules"],
        output_format=THINKING_ASRI_V0_PROMPT["output_format"],
        examples=THINKING_ASRI_V0_PROMPT["examples"],
        extra_section=_extra_section(extra_instructions),
        history_section=history_section,
        turn_state_section=turn_state_section,
        fragment_section=metadata_section + fragment_section,
    )

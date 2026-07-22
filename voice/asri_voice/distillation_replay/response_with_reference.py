from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

from handlers.llm.thinking import disabled_thinking_extra_body


def _looks_like_error_result(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    lowered = value.strip().lower()
    return (
        lowered.startswith("error:")
        or lowered.startswith("error executing tool")
        or "llm mock did not produce a result" in lowered
        or "tool_error" in lowered
    )


def has_effective_tool_result(value: Any) -> bool:
    if value in (None, "", [], {}):
        return False
    return not _looks_like_error_result(value)


@dataclass(frozen=True)
class ResponseWithReferenceConfig:
    base_url: str
    model: str = "default"
    api_key: str = "EMPTY"
    temperature: float = 0.0
    timeout_s: float = 120.0
    disable_thinking: bool = True

    @classmethod
    def from_env(cls, prefix: str = "HEARTBEAT_RESPONSE_WITH_REFERENCE") -> "ResponseWithReferenceConfig | None":
        base_url = os.getenv(f"{prefix}_BASE_URL")
        if not base_url:
            return None
        return cls(
            base_url=base_url,
            model=os.getenv(f"{prefix}_MODEL", "default"),
            api_key=os.getenv(f"{prefix}_API_KEY", "EMPTY"),
            temperature=float(os.getenv(f"{prefix}_TEMPERATURE", "0")),
            timeout_s=float(os.getenv(f"{prefix}_TIMEOUT_S", "120")),
            disable_thinking=os.getenv(f"{prefix}_DISABLE_THINKING", "true").lower() not in {"0", "false", "no"},
        )

    @property
    def chat_completions_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        return f"{base}/v1/chat/completions"


def _compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _section_value(value: Any) -> str:
    return _compact(value)


def build_response_with_reference_prompt(
    *,
    history_messages: list[dict[str, Any]],
    seed_current_user_text: str,
    final_asr_transcript: str,
    current_turn_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    heartbeat_context: list[dict[str, Any]],
    target_tool_trace: list[dict[str, Any]],
    dropped_history_toolcalls: list[dict[str, Any]] | None = None,
) -> str:
    sections = [
        ("History Before Current User", history_messages),
        ("Seed Current User Text", seed_current_user_text),
        ("Final ASR Transcript", final_asr_transcript),
        ("Current Turn GT Reference Messages", current_turn_messages),
        ("Available Tool Schemas", tools),
        ("Heartbeat Context", heartbeat_context),
        ("Target Tool Trace Reference", target_tool_trace),
    ]
    if dropped_history_toolcalls:
        sections.append(("Dropped History Toolcalls", dropped_history_toolcalls))
    body = "\n\n".join(f"### {title}\n{_section_value(value)}" for title, value in sections)
    rules = [
        "### Output",
        "Return one JSON object with exactly these keys:",
        "- asr_equivalent: boolean. True only if Final ASR preserves the actionable meaning, entities, and tool arguments of Seed Current User Text.",
        "- reference_adjusted: boolean. True when output messages differ from the GT reference because ASR or HeartbeatContext requires it.",
        "- reason: short string.",
        "- heartbeat_coverage: list of semantic coverage decisions. Each item should contain reference_tool, heartbeat_tool, covered, decision, and reason.",
        "- messages: list of OpenAI-style messages for the current turn after the current user message only.",
        "",
        "Task:",
        "- Produce response messages for the ASR-visible request in Final ASR Transcript. The GT reference messages, seed current user text, and target tool trace are references, not authorities.",
        "- Judge heartbeat coverage yourself. For each tool call you would emit, check whether Heartbeat Context already contains a completed tool result that answers the same ASR-visible request. If it does, do not re-emit that tool call; mark it covered in heartbeat_coverage and use the heartbeat result as context when writing the assistant response.",
        "- Only emit a new tool call when Heartbeat Context has not already covered it AND the ASR-visible request supports all required arguments. Do not emit a tool call just because the GT reference has one.",
        "- When heartbeat covered a tool call, the assistant response should reference the heartbeat result directly (e.g. 'Order B2 has shipped.'). Do not duplicate the tool call, and do not invent a new tool_call id for it.",
        "- Answer based on the real ASR result. If Final ASR changes the entity, id, number, date, location, or required tool argument vs. Seed Current User Text, write response messages for the ASR-visible request. Do not force the answer to match the GT reference.",
        "- If Final ASR is wrong or incomplete and no valid tool call can be grounded, write an assistant clarification question instead of dropping the sample.",
        "- A Heartbeat tool without an effective completed result cannot cover a reference tool. Pending, late, timeout, empty result, and error result are not coverage.",
        "- Message roles may be assistant or tool. Do not include system or user messages. Do not invent tool_call ids; preserve existing ids only when they are already present in GT reference messages.",
        "- Tool calls must use names and arguments from Available Tool Schemas and the ASR-visible request/history only.",
        '- Every tool message MUST include a "name" field set to the tool\'s name from Available Tool Schemas.',
        "",
        "Response style alignment with ASRI generic response prompt:",
        "- Assistant natural-language content must be a spoken voice response for the ASR-visible user request, not a written chat answer.",
        "- Reply in the same language the user is speaking. Keep it brief by default: one sentence is enough for most turns; use two only when needed for clarity.",
        "- Do not use markdown, bullet lists, numbered lists, headings, tables, code blocks, block quotes, action markers, or visual formatting symbols in assistant content.",
        "- Never mention internal terms or implementation details such as tool, tool call, API, database, harness, HeartBeat, prompt, system message, background process, prefetch, temporary context, or internal note to the user.",
        "- Ground assistant content in the final valid result that matches the user's latest ASR-visible request. Do not mention earlier guesses, partial attempts, pending/failed calls, stale values, or GT-only facts contradicted by Final ASR.",
        "- If multiple attempts or corrections exist, mention only the latest successful result matching the final request. Do not repeat superseded identifiers, amounts, destinations, dates, or product names.",
        "- Do not ask whether the user wants an action or lookup if the user already requested it and required arguments are available. Emit the required tool call instead.",
        "- For multi-step requests, complete each requested step in order. If a later action depends on an earlier lookup result, use that result to form the downstream tool call when the target is clear.",
        "- Use schema-faithful tool arguments: exact JSON types, exact enum values, only schema-supported fields, and user-provided identifiers preserved unless the schema clearly requires normalization.",
        "- Use speech-stable wording in assistant content: say currency and quantities naturally, keep alphanumeric identifiers compact and canonical, and avoid repeating uncertain variants.",
    ]
    if dropped_history_toolcalls:
        rules.append("")
        rules.append("Dropped History Toolcalls rule:")
        rules.append(
            "- Dropped History Toolcalls are tool calls that were removed from the history to simulate heartbeat cover. "
            "Their results may or may not still be needed by the current turn."
        )
        rules.append(
            "- For each dropped toolcall, decide whether to re-emit it in the current turn. "
            "You MUST re-emit the toolcall ONLY when ALL of the following conditions are met:"
        )
        rules.append(
            "  1. The information (result) is ONLY available from the dropped toolcall itself — "
            "no previous history turn (assistant response, tool result, user message) mentions or contains the same information."
        )
        rules.append(
            "  2. The current turn's Heartbeat Context does NOT contain the same completed tool result."
        )
        rules.append(
            "  3. The current turn's final answer (the assistant response you are writing) actually USES the information "
            "from the dropped toolcall — i.e. the answer depends on the result that was only in the dropped toolcall."
        )
        rules.append(
            "  4. The current turn has not already emitted an equivalent toolcall that covers the same information."
        )
        rules.append(
            "- If ALL 4 conditions are met, re-emit the toolcall in the current turn messages "
            "(i.e. add the assistant tool_call + tool result to the current turn)."
        )
        rules.append(
            "- If ANY condition is NOT met (e.g. the information is also available in a previous assistant response, "
            "or Heartbeat Context already covers it, or the current answer does not use the dropped result), "
            "then do NOT re-emit the toolcall."
        )
    return body + "\n\n" + "\n".join(rules)


class ResponseWithReferenceClient:
    def __init__(self, config: ResponseWithReferenceConfig):
        self.config = config
        self.session = requests.Session()

    def build(
        self,
        *,
        history_messages: list[dict[str, Any]],
        seed_current_user_text: str,
        final_asr_transcript: str,
        current_turn_messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        heartbeat_context: list[dict[str, Any]],
        target_tool_trace: list[dict[str, Any]],
        dropped_history_toolcalls: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        prompt = build_response_with_reference_prompt(
            history_messages=history_messages,
            seed_current_user_text=seed_current_user_text,
            final_asr_transcript=final_asr_transcript,
            current_turn_messages=current_turn_messages,
            tools=tools,
            heartbeat_context=heartbeat_context,
            target_tool_trace=target_tool_trace,
            dropped_history_toolcalls=dropped_history_toolcalls,
        )
        payload: dict[str, Any] = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an offline Response With Reference judge for voice-agent replay traces. "
                        "Return JSON only. Your job is to produce response messages for the ASR-visible "
                        "request, judging heartbeat coverage yourself: if Heartbeat Context already "
                        "completed a tool that answers the ASR-visible request, do not re-emit that "
                        "tool call. Answer based on the real ASR result, not the GT reference. Any "
                        "assistant natural-language content you generate must match the ASRI generic "
                        "spoken response style: concise, grounded in final valid results, same "
                        "language as the user, and free of markdown or internal implementation terms."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
        }
        if self.config.disable_thinking:
            extra_body = disabled_thinking_extra_body(self.config.model)
            if extra_body:
                payload.update(extra_body)

        start = time.perf_counter()
        response = self.session.post(
            self.config.chat_completions_url,
            json=payload,
            headers={"Authorization": f"Bearer {self.config.api_key}"},
            timeout=self.config.timeout_s,
        )
        wall_latency_ms = round((time.perf_counter() - start) * 1000)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"response_with_reference llm output must be valid JSON: {content[:200]}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("response_with_reference llm output must be a JSON object")
        messages = parsed.get("messages")
        if not isinstance(messages, list):
            raise ValueError("response_with_reference llm output must include messages list")
        if not isinstance(parsed.get("reference_adjusted"), bool):
            raise ValueError("response_with_reference llm output must include reference_adjusted boolean")
        heartbeat_coverage = parsed.get("heartbeat_coverage")
        if not isinstance(heartbeat_coverage, list):
            raise ValueError("response_with_reference llm output must include heartbeat_coverage list")
        return parsed, {
            "response_with_reference_wall_latency_ms": wall_latency_ms,
            "model": self.config.model,
            "base_url": self.config.base_url,
        }

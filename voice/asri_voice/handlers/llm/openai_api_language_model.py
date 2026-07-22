import json
import logging
import os
import time
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import httpx
from handlers.llm.utils import split_sentences

# ANSI colors for terminal logging
_Y = "\033[33m"   # yellow — tool calls
_G = "\033[32m"   # green — LLM text output
_B = "\033[36m"   # cyan — tool results
_R = "\033[0m"    # reset
from rich.console import Console
from openai import OpenAI, Stream
from openai.types.responses import Response, ResponseStreamEvent

from pipeline.base_handler import BaseHandler
from pipeline.cancel_scope import CancelScope
from handlers.llm.chat import Chat
from handlers.llm.thinking import disabled_thinking_extra_body
from handlers.llm.utils import remove_unspeechable, strip_markdown, strip_xml_tags
from api.openai_realtime.runtime_config import RuntimeConfig
from handlers.llm.tool_call.tool_registry import ToolRegistry
from handlers.llm.tool_call.normalize import normalize_chat_completions_tools
from utils.utils import log_llm_request
from handlers.heartbeat_interaction.history_formatter import (
    clean_tool_result_for_model,
    load_heartbeat_response_prompt_template,
    normalize_heartbeat_response_tool_payload,
    render_heartbeat_response_context,
    strip_model_hidden_tool_fields,
)

# Shared agent loop utilities (tool delta accumulation + JSON parsing)
from core.agent_loop import AgentLoopCore

logger = logging.getLogger(__name__)


def _scan_messages_for_control(messages: list, log) -> list:
    """Diagnostic: walk every value in *messages* and flag any
    PipelineControlMessage instances hiding inside nested structures.
    Returns a deep-cleaned copy with control messages replaced by empty string.
    """
    from pipeline.control import PipelineControlMessage

    def _clean(obj, path: str = "root"):
        if isinstance(obj, PipelineControlMessage):
            log.error(
                "DIAGNOSTIC: PipelineControlMessage found at %s: %r",
                path, obj,
            )
            return ""  # replace with empty string
        if isinstance(obj, dict):
            return {k: _clean(v, f"{path}[{k!r}]") for k, v in obj.items()}
        if isinstance(obj, list):
            return [_clean(v, f"{path}[{i}]") for i, v in enumerate(obj)]
        if isinstance(obj, tuple):
            return tuple(_clean(v, f"{path}[{i}]") for i, v in enumerate(obj))
        return obj

    return [_clean(msg, f"messages[{i}]") for i, msg in enumerate(messages)]


def _scan_kwargs_for_control(kwargs: dict, log) -> None:
    """Scan optional_kwargs for any PipelineControlMessage hiding in values."""
    from pipeline.control import PipelineControlMessage

    def _walk(obj, path: str = "root"):
        if isinstance(obj, PipelineControlMessage):
            log.error(
                "DIAGNOSTIC_KWARGS: PipelineControlMessage found at %s: %r",
                path, obj,
            )
        elif isinstance(obj, dict):
            for k, v in obj.items():
                _walk(v, f"{path}[{k!r}]")
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]")

    for k, v in kwargs.items():
        _walk(v, f"kwargs[{k!r}]")


def _safe_repr(obj) -> str:
    """Return a string repr of obj, replacing non-serializable items with type info."""
    from pipeline.control import PipelineControlMessage

    def _convert(o):
        if isinstance(o, PipelineControlMessage):
            return f"<PipelineControlMessage:{o.kind}>"
        if isinstance(o, dict):
            return {k: _convert(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_convert(v) for v in o]
        if isinstance(o, str) and len(o) > 200:
            return o[:200] + "..."
        return o

    try:
        import json
        return json.dumps(_convert(obj), ensure_ascii=False, default=str)
    except Exception:
        return repr(obj)

console = Console()

WHISPER_LANGUAGE_TO_LLM_LANGUAGE = {
    "en": "english",
    "fr": "french",
    "es": "spanish",
    "zh": "chinese",
    "ja": "japanese",
    "ko": "korean",
}


class OpenApiModelHandler(BaseHandler):
    """
    Handles the language model part.
    """

    def setup(
        self,
        model_name="deepseek-chat",
        device="cuda",
        gen_kwargs={},
        base_url=None,
        api_key=None,
        stream=False,
        user_role="user",
        chat_size=999,
        init_chat_role="system",
        init_chat_prompt="You are a helpful AI assistant.",
        runtime_config: RuntimeConfig | None = None,
        cancel_scope: CancelScope | None = None,
        disable_thinking=True,
        clean_response_text=True,
        request_timeout_s=20.0,
        tool_registry: ToolRegistry | None = None,
        max_agent_iterations: int = 10,
        heartbeat_cache=None,
        text_output_queue=None,
    ):
        self.cancel_scope = cancel_scope
        self.heartbeat_cache = heartbeat_cache
        self.heartbeat_replay_drain_hook = None
        self.text_output_queue = text_output_queue
        self._heartbeat_snapshot = []
        self._heartbeat_history_rewrite = None
        self._heartbeat_formal_commits: list[tuple[dict, dict]] = []
        self._heartbeat_formal_commit_results_by_signature: dict[tuple[str, str], dict] = {}
        self.model_name = model_name
        self.base_url = base_url
        self.api_key = api_key
        self.stream = stream
        self.clean_response_text = clean_response_text
        self.gen_kwargs = {k: v for k, v in dict(gen_kwargs).items() if v is not None}
        self.request_timeout_s = float(request_timeout_s)
        self.request_timeout = httpx.Timeout(
            self.request_timeout_s,
            connect=min(10.0, self.request_timeout_s),
        )
        self.chat = Chat(chat_size)
        self._initial_chat_message = None
        if init_chat_role:
            if not init_chat_prompt:
                raise ValueError(
                    "An initial promt needs to be specified when setting init_chat_role."
                )
            self._initial_chat_message = {"role": init_chat_role, "content": init_chat_prompt}
            self.chat.init_chat(dict(self._initial_chat_message))
        self.user_role = user_role
        self.runtime_config = runtime_config
        self._initial_instructions = init_chat_prompt
        self._last_instructions = init_chat_prompt
        self._last_system_prompt = init_chat_prompt
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.tools = None
        self.tools_choice = None
        # Model-class detection: Instruct models use T=0.7/topP=0.8/topK=20/minP=0.
        _is_instruct = "instruct" in model_name.lower()
        if _is_instruct:
            self._extra_body = (
                {"top_k": 20, "min_p": 0.0}
                if base_url is not None
                else None
            )
            # Override gen_kwargs defaults for instruct models
            self.gen_kwargs.setdefault("temperature", 0.7)
            self.gen_kwargs.setdefault("top_p", 0.8)
        else:
            self._extra_body = (
                disabled_thinking_extra_body(model_name)
                if disable_thinking and base_url is not None
                else None
            )
        self.tool_registry = tool_registry
        self.max_agent_iterations = max_agent_iterations
        self._agent_loop_active = tool_registry is not None and len(tool_registry) > 0
        if self._agent_loop_active:
            logger.info(
                "Agent loop active: %d server tools registered (%s), max %d iterations",
                len(tool_registry),
                tool_registry.all_server_tool_names(),
                max_agent_iterations,
            )
        self.warmup()

    def warmup(self):
        logger.info(f"Warming up {self.__class__.__name__}")
        messages = [
            {"role": "system", "content": "You are a helpful assistant"},
            {"role": "user", "content": "Hello"},
        ]
        log_llm_request(
            logger, "VoiceAgent.warmup", self.model_name, messages,
            max_tokens=1, timeout=self.request_timeout,
        )
        start = time.time()
        try:
            self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                max_tokens=1,
                timeout=self.request_timeout,
            )
        except Exception as e:
            logger.warning(f"{self.__class__.__name__}: warmup failed ({e}), continuing anyway")
            return
        end = time.time()
        logger.info(
            f"{self.__class__.__name__}:  warmed up! time: {(end - start):.3f} s"
        )

    @staticmethod
    def _consolidate_tool_deltas(deltas: list[dict]) -> list[dict]:
        """Consolidate streaming tool call deltas into complete tool calls.

        Uses shared AgentLoopCore._accumulate_tool_delta for per-delta
        accumulation (same OpenAI delta format as Django).
        """
        if not deltas:
            return []
        # Fast path: already consolidated (non-streaming)
        if (len(deltas) == 1 or all(
            d.get("function", {}).get("name")
            and d.get("function", {}).get("arguments") not in (None, "")
            for d in deltas if d.get("function")
        )):
            return sorted(deltas, key=lambda d: d.get("index", 0))
        # Accumulate using shared utility
        groups: dict[int, dict] = {}
        for d in deltas:
            AgentLoopCore._accumulate_tool_delta(d, groups)
        # Reconstruct OpenAI tool call format from accumulated buffers
        result = []
        for idx in sorted(groups.keys()):
            buf = groups[idx]
            if not buf.get("name"):
                continue
            result.append({
                "type": "function",
                "id": buf.get("id") or None,
                "function": {
                    "name": buf["name"],
                    "arguments": buf.get("arguments", ""),
                },
            })
        return result

    def _convert_tools_for_chat_api(self, tools: list) -> list[dict]:
        """Convert Realtime API tool format to Chat Completions API format.

        Realtime:  {"type": "function", "name": "...", "parameters": {...}}
        Chat API:  {"type": "function", "function": {"name": "...", "parameters": {...}}}
        """
        converted = []
        for tool in tools:
            if isinstance(tool, dict):
                # Already in Chat Completions format
                if "function" in tool:
                    converted.append(self._normalize_chat_tool_schema(tool))
                    continue
                # Realtime / seed-preview flat format: wrap name/parameters inside "function".
                # Some offline rows use bare {"name", "description", "parameters"}
                # without an explicit type.
                if (tool.get("type") == "function" or "type" not in tool) and "name" in tool:
                    converted.append({
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool.get("description", ""),
                            "parameters": self._normalize_json_schema(tool.get("parameters", {})),
                        },
                    })
                    continue
            # Pydantic model or other — try model_dump
            if hasattr(tool, "model_dump"):
                d = tool.model_dump()
                if "function" in d:
                    converted.append(self._normalize_chat_tool_schema(d))
                elif (d.get("type") == "function" or "type" not in d) and "name" in d:
                    converted.append({
                        "type": "function",
                        "function": {
                            "name": d["name"],
                            "description": d.get("description", ""),
                            "parameters": self._normalize_json_schema(d.get("parameters", {})),
                        },
                    })
                else:
                    converted.append(d)
            else:
                logger.warning("Skipping unrecognised tool format: %s", type(tool))
        return converted

    @staticmethod
    def _normalize_json_schema(schema: dict) -> dict:
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}}
        normalized = copy.deepcopy(schema)
        if "properties" in normalized or "required" in normalized:
            normalized.setdefault("type", "object")
        elif "items" in normalized:
            normalized.setdefault("type", "array")
        elif "enum" in normalized:
            enum_values = normalized.get("enum")
            if isinstance(enum_values, list) and enum_values:
                if all(isinstance(v, bool) for v in enum_values):
                    normalized.setdefault("type", "boolean")
                elif all(isinstance(v, int) and not isinstance(v, bool) for v in enum_values):
                    normalized.setdefault("type", "integer")
                elif all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in enum_values):
                    normalized.setdefault("type", "number")
                else:
                    normalized.setdefault("type", "string")
            else:
                normalized.setdefault("type", "string")
        properties = normalized.get("properties")
        if isinstance(properties, dict):
            normalized["properties"] = {
                key: OpenApiModelHandler._normalize_json_schema(value)
                for key, value in properties.items()
            }
        items = normalized.get("items")
        if isinstance(items, dict):
            normalized["items"] = OpenApiModelHandler._normalize_json_schema(items)
        elif isinstance(items, list):
            normalized["items"] = [
                OpenApiModelHandler._normalize_json_schema(item) if isinstance(item, dict) else item
                for item in items
            ]
        return normalized

    @classmethod
    def _normalize_chat_tool_schema(cls, tool: dict) -> dict:
        normalized = copy.deepcopy(tool)
        function = normalized.get("function")
        if isinstance(function, dict):
            function["parameters"] = cls._normalize_json_schema(function.get("parameters", {}))
        return normalized

    def _merge_tools(self, optional_kwargs: dict) -> dict:
        """Choose the structured tools exposed to the response model.

        Runtime tools injected by ``conversation.history.set`` are sample-scoped
        and must be the only visible tool list for that turn. Otherwise expose
        the default server-side registry tools.

        All tools — YAML ``tools_module`` and Django-configured — live in the
        shared ``tool_registry`` now, so no separate merge path is needed.
        """
        kw = dict(optional_kwargs)
        client_tools = list(kw.get("tools", []) or [])
        runtime_config = getattr(self, "runtime_config", None)
        sample_scoped_tools = bool(
            runtime_config
            and getattr(getattr(runtime_config, "session", None), "tools", None)
        )
        if sample_scoped_tools and client_tools:
            kw["tools"] = client_tools
            return kw

        if not self.tool_registry:
            return kw

        server_tools = self.tool_registry.tool_schemas_chat_api()
        all_tools = client_tools + server_tools
        if not all_tools:
            return kw

        merged = []
        seen_names: set[str] = set()
        for tool in all_tools:
            name = ""
            if isinstance(tool, dict):
                function = tool.get("function")
                if isinstance(function, dict):
                    name = str(function.get("name") or "")
            if name and name in seen_names:
                continue
            if name:
                seen_names.add(name)
            merged.append(tool)
        if merged:
            kw["tools"] = merged
        return kw

    @classmethod
    def _tools_schema_system_block(cls, tools: list[dict] | None) -> str:
        if not tools:
            return ""
        normalized_tools = []
        for tool in tools:
            if not isinstance(tool, dict):
                normalized_tools.append(tool)
            elif "function" in tool:
                normalized_tools.append(cls._normalize_chat_tool_schema(tool))
            elif tool.get("type") == "function":
                normalized = copy.deepcopy(tool)
                normalized["parameters"] = cls._normalize_json_schema(normalized.get("parameters", {}))
                normalized_tools.append(normalized)
            else:
                normalized_tools.append(tool)
        return (
            "\n\n### Tool Schemas\n"
            "The following tool schemas are also passed through the structured tools interface. "
            "Use these schemas as the source of truth for tool names, descriptions, arguments, and required fields.\n"
            + json.dumps(normalized_tools, ensure_ascii=False, indent=2)
        )

    @staticmethod
    def _extra_instructions_system_block(extra_instructions: str | None) -> str:
        if not extra_instructions or not extra_instructions.strip():
            return ""
        return (
            "\n\n### Instruction Prompts for current conversation\n"
            "The following sample-specific instructions extend the default system policy. "
            "Follow them only when they do not conflict with higher-priority safety or harness rules.\n"
            f"{extra_instructions.strip()}"
        )

    def _apply_runtime_config(self, override_tool_choice=None, override_instructions: str | None = None):
        if not self.runtime_config:
            return

        raw_tools = self.runtime_config.session.tools
        self.tools = self._convert_tools_for_chat_api(raw_tools) if raw_tools else None
        self.tools_choice = override_tool_choice or self.runtime_config.session.tool_choice

        base_instructions = (
            override_instructions
            or self.runtime_config.session.instructions
            or self._initial_instructions
        )
        if base_instructions != self._last_instructions:
            self._last_instructions = base_instructions
        extra_instructions = getattr(self.runtime_config, "extra_instructions", "") or ""
        system_prompt = (
            base_instructions
            + self._tools_schema_system_block(raw_tools)
            + self._extra_instructions_system_block(extra_instructions)
        )
        if system_prompt != self._last_system_prompt:
            self._last_system_prompt = system_prompt
            self.chat.init_chat({"role": "system", "content": system_prompt})
            logger.info(f"LLM instructions updated ({len(system_prompt)} chars)")

        logger.info("Tools: raw=%s, converted=%s, tool_choice=%s", raw_tools, self.tools, self.tools_choice)

    def _tool_context(self, gen):
        context = {}
        if gen is not None:
            context["turn_id"] = f"gen:{gen}"
        context["conversation_messages"] = self.chat.to_list()
        context["llm_model_name"] = self.model_name
        context["llm_base_url"] = getattr(self, "base_url", None)
        context["llm_api_key"] = getattr(self, "api_key", None)
        return context

    @staticmethod
    def _strip_model_hidden_tool_fields(value):
        return strip_model_hidden_tool_fields(value)

    @staticmethod
    def _clean_tool_result_for_model(result: str) -> str:
        return clean_tool_result_for_model(result)

    def _execute_server_tools_concurrently(self, normalized, iteration, gen, tool_context):
        """Execute server-side tool calls concurrently and return results in call order."""
        if not normalized:
            return [], False

        def _is_cancelled() -> bool:
            return (
                gen is not None
                and self.cancel_scope is not None
                and self.cancel_scope.is_stale(gen)
            )

        if _is_cancelled():
            return [None] * len(normalized), True

        logger.info(
            "%sAgent loop [iter %d]: executing %d server tools concurrently%s",
            _Y, iteration, len(normalized), _R,
        )
        results = [None] * len(normalized)
        cancelled = False

        def _is_interpreter_shutdown_error(exc: RuntimeError) -> bool:
            msg = str(exc)
            return "interpreter shutdown" in msg or "cannot schedule new futures" in msg

        def _run_tool(tc, *, cancellable: bool = True):
            if _is_cancelled():
                logger.info("Agent loop: cancelled before executing tool %s", tc.name)
                return None
            logger.info(
                "%sAgent loop [iter %d]: executing server tool %s (call_id=%s)%s",
                _Y, iteration, tc.name, tc.call_id, _R,
            )
            try:
                result = self.tool_registry.execute(
                    tc.name, tc.arguments,
                    cancel_scope=self.cancel_scope if cancellable else None,
                    gen=gen if cancellable else None,
                    source="main_llm",
                    context=tool_context,
                )
            except RuntimeError as exc:
                if not _is_interpreter_shutdown_error(exc):
                    raise
                logger.warning(
                    "Agent loop: thread scheduling unavailable while executing %s; "
                    "retrying without cancellable worker thread",
                    tc.name,
                )
                result = self.tool_registry.execute(
                    tc.name, tc.arguments,
                    source="main_llm",
                    context=tool_context,
                )
            if result is None:
                logger.info("Agent loop: tool %s cancelled during execution", tc.name)
                return None
            logger.info("%sAgent loop: tool %s result: %s%s", _B, tc.name, result, _R)
            return result

        def _run_remaining_serially(start_idx: int, *, cancellable: bool = False) -> None:
            nonlocal cancelled
            for idx in range(start_idx, len(normalized)):
                if results[idx] is not None:
                    continue
                try:
                    result = _run_tool(normalized[idx], cancellable=cancellable)
                except Exception as exc:
                    tc = normalized[idx]
                    logger.exception("Agent loop: tool %s serial fallback failed", tc.name)
                    result = f"Error executing tool '{tc.name}': {exc}"
                if result is None:
                    cancelled = True
                results[idx] = result

        if len(normalized) == 1:
            _run_remaining_serially(0, cancellable=True)
            return results, cancelled

        max_workers = max(1, min(len(normalized), 8))
        next_unsubmitted_idx = len(normalized)
        try:
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="server-tool") as executor:
                futures = {}
                for idx, tc in enumerate(normalized):
                    try:
                        futures[executor.submit(_run_tool, tc)] = idx
                    except RuntimeError as exc:
                        if not _is_interpreter_shutdown_error(exc):
                            raise
                        next_unsubmitted_idx = idx
                        logger.warning(
                            "Agent loop: thread pool scheduling unavailable; "
                            "falling back to serial execution for %d remaining tools",
                            len(normalized) - idx,
                        )
                        break

                for future in as_completed(futures):
                    idx = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        tc = normalized[idx]
                        logger.exception("Agent loop: tool %s execution future failed", tc.name)
                        result = f"Error executing tool '{tc.name}': {exc}"
                    if result is None:
                        cancelled = True
                    results[idx] = result
        except RuntimeError as exc:
            if not _is_interpreter_shutdown_error(exc):
                raise
            logger.warning(
                "Agent loop: thread pool unavailable before submitting tools; "
                "falling back to serial execution"
            )
            next_unsubmitted_idx = 0

        if next_unsubmitted_idx < len(normalized):
            _run_remaining_serially(next_unsubmitted_idx, cancellable=False)

        return results, cancelled

    def _inject_heartbeat_context(self):
        """Check the HeartBeat cache for completed tool-call predictions.

        If the predict side-branch has already executed tools and cached
        the results, inject all tool-call + tool-response pairs into the
        chat history *before* calling the LLM.  This gives the LLM
        HeartBeat context it can use immediately, saving round-trips.

        After consumption the cache is cleared and the predict handler
        is signalled to stop.
        """
        self._heartbeat_snapshot = []
        self._heartbeat_history_rewrite = None

        if getattr(self, "heartbeat_cache", None) is None:
            self._emit_response_input_messages()
            return

        # Diagnostic: log cache state before consuming
        with self.heartbeat_cache._lock:
            _n = len(self.heartbeat_cache._entries)
            _c = self.heartbeat_cache._consumed.is_set()
        logger.info("_inject_heartbeat_context: cache id=%s, entries=%d, consumed_flag=%s", id(self.heartbeat_cache), _n, _c)

        self._wait_for_replay_pending_heartbeat_tools()

        snapshot_at_ms = (
            self.heartbeat_cache.response_snapshot_at_ms()
            if hasattr(self.heartbeat_cache, "response_snapshot_at_ms")
            else None
        )
        entries = self.heartbeat_cache.consume_all(snapshot_at_ms=snapshot_at_ms)
        if not entries:
            self._emit_response_input_messages()
            return

        thinking_entries = [entry for entry in entries if getattr(entry, "thinking", "")]
        all_items = [it for entry in entries for it in entry.items]
        if not thinking_entries and not all_items:
            self._emit_response_input_messages()
            return
        response_prompt_template = load_heartbeat_response_prompt_template()

        tool_names = [it.tool_name for it in all_items]
        logger.info(
            "%sHeartBeat Thinking injected: entries=%d, thinking=%d, tools=%s%s",
            _Y, len(entries), len(thinking_entries), tool_names, _R,
        )

        def _strip_runtime_managed(value):
            return OpenApiModelHandler._strip_model_hidden_tool_fields(value)

        def _clean_result_for_model(result: str) -> str:
            return OpenApiModelHandler._clean_tool_result_for_model(result)

        # Snapshot for metrics / eval output
        self._heartbeat_snapshot = []
        for it in all_items:
            snap = {
                "tool_name": it.tool_name,
                "arguments": _strip_runtime_managed(it.arguments),
                "status": getattr(it, "status", "completed"),
                "result_preview": _clean_result_for_model(it.result) if it.result else "",
            }
            # Extract cache source for metrics (not injected into conversation)
            if it.tool_name == "search_epos_knowledge" and it.result:
                try:
                    _p = json.loads(it.result)
                    if isinstance(_p, dict):
                        if "source" in _p:
                            snap["source"] = _p["source"]
                        if "cache_info" in _p:
                            snap["cache_info"] = _p["cache_info"]
                except (json.JSONDecodeError, TypeError):
                    pass
            self._heartbeat_snapshot.append(snap)

        context_payload = {
            "thinking_entries": [],
            "subtasks": [],
        }

        for entry in entries:
            entry_payload = {
                "block": entry.order_key,
                "action": getattr(entry, "action", "think"),
                "tools": [],
            }
            if entry.thinking:
                entry_payload["thinking"] = entry.thinking
            metadata = getattr(entry, "metadata", None)
            if isinstance(metadata, dict) and metadata:
                entry_payload["metadata"] = metadata

            for it in entry.items:
                # Strip debug-only fields (source, cache_info) so they don't
                # leak into the conversation or downstream.
                status = getattr(it, "status", "completed")
                tool_payload = normalize_heartbeat_response_tool_payload(
                    {
                        "name": it.tool_name,
                        "arguments": it.arguments,
                        "status": status,
                        "result": it.result,
                    },
                    response_prompt_template,
                )
                if tool_payload is not None:
                    entry_payload["tools"].append(tool_payload)
            context_payload["thinking_entries"].append(entry_payload)

        _PREDICT_HINT = render_heartbeat_response_context(context_payload, response_prompt_template)
        # HeartBeat thinking/tool context is temporary. It is visible to the
        # current LLM call only, then removed from chat history after the
        # response so speculative or unused HeartBeat results do not leak into
        # later turns.
        _HISTORY_HINT = ""

        target_idx = None
        for i in range(len(self.chat.buffer) - 1, -1, -1):
            buf_item = self.chat.buffer[i]
            if not isinstance(buf_item, dict):
                continue
            if buf_item.get("role") == self.user_role:
                target_idx = i
                content = self.chat.buffer[i].get("content", "")
                if isinstance(content, str):
                    self.chat.buffer[i]["content"] = content + _PREDICT_HINT
                    self._heartbeat_history_rewrite = {
                        "idx": i,
                        "full_hint": _PREDICT_HINT,
                        "history_hint": _HISTORY_HINT,
                    }
                elif isinstance(content, list):
                    # multimodal content: append a text part
                    content.append({"type": "text", "text": _PREDICT_HINT})
                    self.chat.buffer[i]["content"] = content
                    self._heartbeat_history_rewrite = {
                        "idx": i,
                        "full_hint": _PREDICT_HINT,
                        "history_hint": _HISTORY_HINT,
                    }
                break
        if target_idx is None:
            raise RuntimeError("HeartBeat Response context injection failed: no user message in chat buffer")

        # Build formal-commit pairs for turn_end tools that were executed.
        # These are yielded before the agent loop so downstream sees them,
        # and the agent loop skips re-executing matching tool calls.
        self._heartbeat_formal_commits = []
        self._heartbeat_formal_commit_results_by_signature = {}
        for it in all_items:
            if not self._heartbeat_result_executed(it):
                continue
            pair = self._heartbeat_tool_commit_pair(it)
            if pair is not None:
                self._heartbeat_formal_commits.append(pair)
                signature = self._tool_signature(it.tool_name, it.arguments)
                if signature is not None:
                    self._heartbeat_formal_commit_results_by_signature[signature] = {
                        "tool_name": it.tool_name,
                        "tool_call_id": it.tool_call_id,
                        "arguments": it.arguments,
                        "result": it.result,
                    }

        self._emit_response_input_messages()

    def _wait_for_replay_pending_heartbeat_tools(self) -> None:
        """Wait for replay-visible pending Heartbeat tools before consuming.

        In normal realtime inference, response generation should not wait for
        speculative Heartbeat tools.  Distillation replay is different: SFT
        input and trace labels are evaluated on the virtual audio timeline, so
        pending tool mocks that are virtually completed by response start must
        be materialized before ``response.input_messages`` is emitted.
        """
        runtime_config = getattr(self, "runtime_config", None)
        if getattr(runtime_config, "trace_level", None) != "replay":
            return
        hook = getattr(self, "heartbeat_replay_drain_hook", None)
        if callable(hook):
            timeout_s = float(os.getenv("HEARTBEAT_REPLAY_PENDING_TOOL_WAIT_TIMEOUT_S", "30"))
            try:
                hook(timeout_s=timeout_s)
            except TypeError:
                hook()
        pending = self.heartbeat_cache.pending_tool_count()
        if pending <= 0:
            return
        timeout_s = float(os.getenv("HEARTBEAT_REPLAY_PENDING_TOOL_WAIT_TIMEOUT_S", "30"))
        logger.info(
            "Replay response input waiting for %d pending HeartBeat tool result(s), timeout=%.1fs",
            pending,
            timeout_s,
        )
        remaining = self.heartbeat_cache.wait_for_pending_results(timeout_s)
        if remaining > 0:
            logger.warning(
                "Replay response input still has %d pending HeartBeat tool result(s) after %.1fs",
                remaining,
                timeout_s,
            )

    def _emit_response_input_messages(self) -> None:
        """Emit ``response.input_messages`` event with the current chat buffer.

        This replay snapshot is the omni-response input view, not a raw dump
        of the text-teacher Chat API payload.  The text teacher may need the
        final ASR transcript to generate a response, but the training/inference
        format for the target omni model uses audio placeholders: historical
        user turns are ``<audio>``, and the current user turn is ``<audio>``
        plus the temporary HeartbeatContext visible at response start.
        """
        text_output_queue = getattr(self, "text_output_queue", None)
        if text_output_queue is None:
            return
        raw_messages = self.chat.to_list()
        current_user_idx = None
        for idx in range(len(raw_messages) - 1, -1, -1):
            if raw_messages[idx].get("role") == self.user_role:
                current_user_idx = idx
                break

        def _content_to_text(content_val) -> str:
            if isinstance(content_val, list):
                return "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in content_val
                )
            return content_val if content_val is not None else ""

        def _user_value_for_replay(content_text: str, *, is_current: bool) -> str:
            if not is_current:
                return "<audio>"
            marker = "### HeartbeatContext"
            marker_idx = content_text.find(marker)
            if marker_idx < 0:
                return "<audio>"
            context_block = content_text[marker_idx:].lstrip()
            return "<audio>\n\n" + context_block

        messages_snapshot = []
        for idx, msg in enumerate(raw_messages):
            role = msg.get("role")
            if role is None:
                continue
            content_val = _content_to_text(msg.get("content"))
            if role == self.user_role:
                content_val = _user_value_for_replay(
                    str(content_val),
                    is_current=(idx == current_user_idx),
                )
            messages_snapshot.append({
                "role": role,
                "content": content_val,
            })
        text_output_queue.put({
            "type": "response.input_messages",
            "trace_level": "replay",
            "messages": messages_snapshot,
            "response_start_ms": int(time.time() * 1000),
        })

    def _finalize_heartbeat_history(self):
        """Drop temporary HeartBeat thinker text from the user message.

        The current LLM call sees HeartBeat thinking notes and tool states as
        temporary text. The whole HeartBeat context is removed after response
        generation, so completed speculative tool results do not become
        cross-turn history unless the final response/tool loop explicitly
        records them elsewhere.
        """
        rewrite = getattr(self, "_heartbeat_history_rewrite", None)
        if not rewrite:
            return

        full_hint = rewrite.get("full_hint", "")
        history_hint = rewrite.get("history_hint", "")
        idx = rewrite.get("idx")

        def _rewrite_message(message: dict) -> bool:
            content = message.get("content", "")
            if isinstance(content, str):
                if full_hint not in content:
                    return False
                message["content"] = content.replace(full_hint, history_hint, 1)
                return True
            if isinstance(content, list):
                for part_idx, part in enumerate(list(content)):
                    if not isinstance(part, dict) or part.get("text") != full_hint:
                        continue
                    if history_hint:
                        part["text"] = history_hint
                    else:
                        content.pop(part_idx)
                    return True
            return False

        try:
            if isinstance(idx, int) and 0 <= idx < len(self.chat.buffer):
                if _rewrite_message(self.chat.buffer[idx]):
                    return
            for message in self.chat.buffer:
                if _rewrite_message(message):
                    return
        finally:
            self._heartbeat_history_rewrite = None

    @staticmethod
    def _tool_signature(tool_name: str, arguments: dict | None) -> tuple[str, str] | None:
        """Build a (tool_name, canonical_json) signature for dedup."""
        if not tool_name:
            return None
        stripped = strip_model_hidden_tool_fields(arguments or {})
        try:
            canonical = json.dumps(stripped, sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            canonical = json.dumps(str(stripped), ensure_ascii=False)
        return (tool_name, canonical)

    @staticmethod
    def _heartbeat_result_executed(item) -> bool:
        """Check if a HeartBeat tool result was actually executed at turn_end."""
        if not item.result:
            return False
        try:
            parsed = json.loads(item.result) if isinstance(item.result, str) else None
        except (json.JSONDecodeError, TypeError):
            return False
        if not isinstance(parsed, dict):
            return False
        source = parsed.get("source")
        executed = parsed.get("executed")
        if source != "heartbeat_turn_end":
            return False
        if executed is False:
            return False
        # Exclude pending/accumulated/superseded/skipped states
        state = parsed.get("state")
        if state in ("PENDING", "ACCUMULATED", "SUPERSEDED", "SKIPPED"):
            return False
        return True

    def _heartbeat_tool_commit_pair(self, item) -> tuple[dict, dict] | None:
        """Build a (tool_call_event, tool_result_event) pair for formal commit."""
        if not item.result:
            return None
        try:
            parsed = json.loads(item.result) if isinstance(item.result, str) else None
        except (json.JSONDecodeError, TypeError):
            parsed = None

        tool_call_event = {
            "id": item.tool_call_id,
            "type": "function",
            "function": {
                "name": item.tool_name,
                "arguments": json.dumps(
                    strip_model_hidden_tool_fields(item.arguments or {}),
                    ensure_ascii=False,
                ),
            },
        }
        # Build result event with source formal_commit
        result_content = item.result
        if isinstance(parsed, dict):
            # Strip internal fields for the downstream event
            clean = {k: v for k, v in parsed.items() if k not in ("source",)}
            result_content = json.dumps(clean, ensure_ascii=False)

        tool_result_event = {
            "tool_call_id": item.tool_call_id,
            "name": item.tool_name,
            "content": result_content,
            "source": "heartbeat_formal_commit",
        }
        return (tool_call_event, tool_result_event)

    @staticmethod
    def _assistant_history_message(
        *,
        clean_text: str,
        consolidated_tools: list[dict],
        cancelled: bool,
    ) -> dict | None:
        """Build the assistant message that is safe to keep in chat history.

        Chat Completions requires assistant tool calls to be complete and paired
        with subsequent ``role=tool`` messages. During barge-in, the stream can
        be cancelled after only partial tool-call deltas were received, and the
        tool execution loop will not append matching tool results. In that case
        keep only any text that may have been emitted to the user.
        """
        text = clean_text or ""
        if cancelled:
            if text.strip():
                return {"role": "assistant", "content": text}
            return None

        assistant_msg: dict = {"role": "assistant", "content": text or None}
        if consolidated_tools:
            assistant_msg["tool_calls"] = [
                OpenApiModelHandler._sanitize_tool_call_for_history(tool_call)
                for tool_call in consolidated_tools
            ]
        return assistant_msg

    @staticmethod
    def _sanitize_tool_call_for_history(tool_call: dict) -> dict:
        """Return a history-safe tool call without mutating the raw event.

        Some OpenAI-compatible servers parse assistant ``tool_calls`` from prior
        turns when building the next prompt. If a model streamed malformed JSON
        arguments, keeping that exact string in chat history can make the next
        request fail before the model even runs. The downstream/eval event still
        receives the raw tool call; only the persisted history copy is made
        valid JSON.
        """
        safe = copy.deepcopy(tool_call)
        function = safe.get("function")
        if not isinstance(function, dict):
            return safe
        arguments = function.get("arguments")
        if arguments is None or arguments == "":
            function["arguments"] = "{}"
            return safe
        if not isinstance(arguments, str):
            function["arguments"] = json.dumps(arguments, ensure_ascii=False)
            return safe
        try:
            json.loads(arguments)
        except (json.JSONDecodeError, TypeError):
            function["arguments"] = json.dumps(
                {"_invalid_arguments": arguments},
                ensure_ascii=False,
            )
        return safe

    def _call_llm_streaming(self, optional_kwargs, gen):
        """Do one LLM API call in streaming mode, yield structured events.

        Yields:
            ("ttft", ms) — time to first token
            ("text", text_chunk) — response text for clients; clean by default, raw when configured for eval
            ("tool_call_start",) — first delta.tool_calls chunk arrived (text should be flushed)
            ("tool_call", tool_dict) — complete consolidated tool call dict (after stream ends)
            ("error", error_str) — stream error (e.g. httpx_read_timeout)
            ("done", (input_tokens, output_tokens, cancelled, llm_total_ms)) — generation ended
        """
        response = None
        tools: list[dict] = []
        clean_text = ""
        input_tokens = 0
        output_tokens = 0
        llm_start = time.perf_counter()
        first_token_logged = False
        first_tool_call_delta_seen = False
        cancelled = False
        try:
            messages_for_api = self.chat.to_list()
            # Diagnostic: scan for non-serializable entries and clean them
            messages_for_api = _scan_messages_for_control(messages_for_api, logger)
            # Also scan optional_kwargs for hidden control messages
            _scan_kwargs_for_control(optional_kwargs, logger)
            log_llm_request(
                logger, "VoiceAgent.llm_streaming", self.model_name,
                messages_for_api, stream=True, extra_body=self._extra_body,
                timeout=self.request_timeout, **optional_kwargs,
            )
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages_for_api,
                    stream=True,
                    extra_body=self._extra_body,
                    timeout=self.request_timeout,
                    **optional_kwargs,
                )
            except TypeError as te:
                if "not JSON serializable" in str(te):
                    logger.error(
                        "SERIALIZE_FAIL: messages=%s | kwargs_keys=%s | kwargs=%s",
                        _safe_repr(messages_for_api),
                        list(optional_kwargs.keys()),
                        _safe_repr(optional_kwargs),
                    )
                raise
            for chunk in response:
                if gen is not None and self.cancel_scope.is_stale(gen):
                    logger.info("LLM generation cancelled (interruption)")
                    cancelled = True
                    break
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    if not first_token_logged:
                        ttft_ms = (time.perf_counter() - llm_start) * 1000
                        cumul = ""
                        if self.cancel_scope and self.cancel_scope.pipeline_start:
                            cumul_ms = (time.perf_counter() - self.cancel_scope.pipeline_start) * 1000
                            cumul = f", cumul {cumul_ms:.0f}ms"
                        logger.info("LLM TTFT: %.0fms%s", ttft_ms, cumul)
                        first_token_logged = True
                        yield ("ttft", ttft_ms)
                    text_delta = (
                        remove_unspeechable(strip_markdown(strip_xml_tags(delta.content)))
                        if self.clean_response_text
                        else delta.content
                    )
                    clean_text += text_delta
                    yield ("text", text_delta)
                if delta and delta.tool_calls:
                    # Signal that tool_call deltas have started arriving.
                    # Downstream (agent loop) uses this to flush buffered text
                    # immediately, so TTS can start synthesizing the ack while
                    # tool_call arguments are still streaming in.
                    if not first_tool_call_delta_seen:
                        first_tool_call_delta_seen = True
                        yield ("tool_call_start",)
                    # First tool-call delta also counts as "first token" for
                    # TTFT purposes; otherwise iterations that emit only
                    # tool_calls (no content) would report ttft=N/A.
                    if not first_token_logged:
                        ttft_ms = (time.perf_counter() - llm_start) * 1000
                        cumul = ""
                        if self.cancel_scope and self.cancel_scope.pipeline_start:
                            cumul_ms = (time.perf_counter() - self.cancel_scope.pipeline_start) * 1000
                            cumul = f", cumul {cumul_ms:.0f}ms"
                        logger.info("LLM TTFT (tool_call): %.0fms%s", ttft_ms, cumul)
                        first_token_logged = True
                        yield ("ttft", ttft_ms)
                    for tc in delta.tool_calls:
                        tools.append(tc.model_dump())
                usage = getattr(chunk, "usage", None)
                if usage:
                    input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                    output_tokens = getattr(usage, "completion_tokens", 0) or 0
            llm_total_ms = (time.perf_counter() - llm_start) * 1000
            # Consolidate streaming tool call deltas into complete tool calls
            consolidated_tools = self._consolidate_tool_deltas(tools) if tools else []
            for tc in consolidated_tools:
                yield ("tool_call", tc)
            if not cancelled:
                if clean_text.strip() or consolidated_tools:
                    logger.info(f"{_G}LLM yielding: text='{clean_text.strip()[:50]}', tools={consolidated_tools}{_R}")
                else:
                    logger.warning(f"LLM stream ended with no text (clean_text={clean_text!r})")
            cumul = ""
            if self.cancel_scope and self.cancel_scope.pipeline_start:
                cumul_ms = (time.perf_counter() - self.cancel_scope.pipeline_start) * 1000
                cumul = f", cumul {cumul_ms:.0f}ms"
            logger.info("LLM total: %.0fms%s (cancelled=%s)", llm_total_ms, cumul, cancelled)
            # Save assistant message to chat history.
            #
            # If the response was interrupted while the model was streaming a
            # tool call, the collected tool-call deltas may be incomplete and
            # no matching tool result will be appended. Keeping that half-built
            # assistant.tool_calls entry poisons the next Chat Completions
            # request. Preserve only text that may have actually been spoken.
            assistant_msg = self._assistant_history_message(
                clean_text=clean_text,
                consolidated_tools=consolidated_tools,
                cancelled=cancelled,
            )
            if assistant_msg is not None:
                self.chat.append(assistant_msg)
        except httpx.ReadTimeout:
            logger.warning(
                "OpenAI API read timed out after %.1fs; ending the current response",
                self.request_timeout_s,
            )
            yield ("error", "httpx_read_timeout")
            yield ("done", (0, 0, False, (time.perf_counter() - llm_start) * 1000))
            return
        finally:
            if response is not None and hasattr(response, "close"):
                try:
                    response.close()
                except Exception:
                    pass

        yield ("done", (input_tokens, output_tokens, cancelled, llm_total_ms))

    def _process_with_agent_loop(self, optional_kwargs, language_code, gen):
        """Agent loop: stream text, execute server tools, loop back to LLM.

        When all tool calls are server-side, they are executed automatically
        and the LLM is called again. When any tool call is client-side,
        tool calls are yielded downstream for client execution (existing flow).

        Returns:
            (total_input_tokens, total_output_tokens) via generator return value.
        """
        total_input_tokens = 0
        total_output_tokens = 0
        t0 = time.perf_counter()
        overall_ttft_ms = None
        iterations_metrics = []
        # Merge server tools into optional_kwargs
        optional_kwargs = self._merge_tools(optional_kwargs)

        # When server tools are present but tool_choice wasn't set by client,
        # default to "auto" so the LLM actually uses them
        if "tools" in optional_kwargs and "tool_choice" not in optional_kwargs:
            optional_kwargs["tool_choice"] = "auto"

        stream_error = None
        for iteration in range(self.max_agent_iterations):
            tool_calls_collected: list[dict] = []
            printable_text = ""
            iter_ttft_ms = None
            iter_llm_total_ms = None

            for event in self._call_llm_streaming(optional_kwargs, gen):
                if event[0] == "ttft":
                    iter_ttft_ms = event[1]
                    if overall_ttft_ms is None:
                        overall_ttft_ms = (time.perf_counter() - t0) * 1000
                elif event[0] == "text":
                    printable_text += event[1]
                    sentences = split_sentences(printable_text)
                    if len(sentences) > 1:
                        buf = ""
                        for s in sentences[:-1]:
                            buf += s
                            if len(buf) >= 25:
                                yield buf, language_code, [], gen
                                buf = ""
                        printable_text = buf + sentences[-1]
                elif event[0] == "tool_call_start":
                    # First delta.tool_calls chunk arrived — flush any buffered
                    # text immediately so TTS can start synthesizing the ack
                    # while tool_call arguments are still streaming in.
                    if printable_text.strip():
                        yield printable_text.strip(), language_code, [], gen
                        printable_text = ""
                elif event[0] == "tool_call":
                    tool_calls_collected.append(event[1])
                elif event[0] == "error":
                    stream_error = event[1]
                elif event[0] == "done":
                    total_input_tokens += event[1][0]
                    total_output_tokens += event[1][1]
                    cancelled = event[1][2]
                    iter_llm_total_ms = event[1][3]

            # Yield any remaining text
            if printable_text.strip():
                yield printable_text.strip(), language_code, [], gen
                printable_text = ""

            if cancelled:
                iterations_metrics.append({
                    "llm_ttft_ms": round(iter_ttft_ms) if iter_ttft_ms is not None else None,
                    "llm_total_ms": round(iter_llm_total_ms) if iter_llm_total_ms is not None else None,
                    "tool_calls": [],
                    "tool_exec_ms": None,
                })
                logger.info("Agent loop: generation cancelled at iteration %d", iteration)
                break

            if not tool_calls_collected:
                iterations_metrics.append({
                    "llm_ttft_ms": round(iter_ttft_ms) if iter_ttft_ms is not None else None,
                    "llm_total_ms": round(iter_llm_total_ms) if iter_llm_total_ms is not None else None,
                    "tool_calls": [],
                    "tool_exec_ms": None,
                })
                break

            tool_context = self._tool_context(gen)
            for tool_call in tool_calls_collected:
                self.tool_registry.augment_tool_call_dict(tool_call, tool_context)

            # Normalize tool calls
            normalized = normalize_chat_completions_tools(tool_calls_collected)

            # --- Heartbeat formal-commit dedup ---
            # If the LLM requests a tool that was already executed at
            # heartbeat_turn_end, reuse the cached result instead of
            # re-executing it.
            heartbeat_duplicate_results: list[tuple[Any, dict]] = []
            remaining_normalized: list[Any] = []
            if self._heartbeat_formal_commit_results_by_signature and normalized:
                for tc in normalized:
                    signature = self._tool_signature(tc.name, tc.arguments)
                    heartbeat_result = (
                        self._heartbeat_formal_commit_results_by_signature.get(signature)
                        if signature is not None
                        else None
                    )
                    if heartbeat_result is not None:
                        heartbeat_duplicate_results.append((tc, heartbeat_result))
                    else:
                        remaining_normalized.append(tc)
                if heartbeat_duplicate_results:
                    logger.info(
                        "%sAgent loop: %d tool call(s) matched heartbeat formal-commit, "
                        "reusing cached result(s)%s",
                        _Y, len(heartbeat_duplicate_results), _R,
                    )
                    # Yield tool_call events for duplicated tools
                    dedup_tool_calls = []
                    for tc, _ in heartbeat_duplicate_results:
                        dedup_tool_calls.append({
                            "id": tc.call_id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(
                                    strip_model_hidden_tool_fields(tc.arguments or {}),
                                    ensure_ascii=False,
                                ),
                            },
                        })
                    if dedup_tool_calls:
                        yield "", language_code, dedup_tool_calls, gen
                        yield ("__ITERATION_DONE__", None, None, gen)
                    # Yield cached tool results and append to chat history
                    for tc, cached in heartbeat_duplicate_results:
                        result = cached.get("result", "")
                        tool_result_event = {
                            "tool_call_id": tc.call_id,
                            "name": tc.name,
                            "content": result,
                            "source": "heartbeat_formal_commit",
                        }
                        chat_content = self._clean_tool_result_for_model(result)
                        self.chat.append({
                            "role": "tool",
                            "tool_call_id": tc.call_id,
                            "content": chat_content,
                        })
                        yield ("__TOOL_RESULT__", tool_result_event, None, gen)
                normalized = remaining_normalized

            server_names = self.tool_registry.all_server_tool_names()
            tool_names = [tc.name for tc in normalized]

            all_server = all(tc.name in server_names for tc in normalized)
            any_client = any(tc.name not in server_names for tc in normalized)

            if any_client:
                client_tools = [tc.name for tc in normalized if tc.name not in server_names]
                logger.info(
                    "Agent loop: client-side tool calls detected, yielding to downstream: %s",
                    client_tools,
                )
                iterations_metrics.append({
                    "llm_ttft_ms": round(iter_ttft_ms) if iter_ttft_ms is not None else None,
                    "llm_total_ms": round(iter_llm_total_ms) if iter_llm_total_ms is not None else None,
                    "tool_calls": tool_names,
                    "tool_exec_ms": None,
                })
                yield printable_text.strip(), language_code, tool_calls_collected, gen
                break

            if all_server:
                # Yield tool_calls to downstream so they appear in the current response
                yield "", language_code, tool_calls_collected, gen

                # Signal iteration boundary — downstream will close the current response
                yield ("__ITERATION_DONE__", None, None, gen)

                # Execute server-side tools and yield results to downstream
                tool_start = time.perf_counter()
                tool_results, cancelled_during_tools = self._execute_server_tools_concurrently(
                    normalized, iteration, gen, tool_context
                )
                for tc, result in zip(normalized, tool_results):
                    if result is None:
                        cancelled_during_tools = True
                        break
                    # Build the event dict for downstream (includes debug info like source)
                    tool_result_event = {
                        "tool_call_id": tc.call_id,
                        "name": tc.name,
                        "content": result,
                    }
                    # Content to store in conversation — strip Harness-only fields so
                    # the LLM sees execution facts, not policy/idempotency internals.
                    chat_content = self._clean_tool_result_for_model(result)
                    if tc.name == "search_epos_knowledge":
                        try:
                            parsed = json.loads(result)
                            if isinstance(parsed, dict):
                                # Extract debug fields for downstream events
                                if "source" in parsed:
                                    tool_result_event["source"] = parsed["source"]
                                if "cache_info" in parsed:
                                    tool_result_event["cache_info"] = parsed["cache_info"]
                                # Strip debug fields from conversation content
                                strip_keys = {"source", "cache_info"}
                                if any(k in parsed for k in strip_keys):
                                    chat_parsed = {k: v for k, v in parsed.items() if k not in strip_keys}
                                    chat_content = self._clean_tool_result_for_model(
                                        json.dumps(chat_parsed, ensure_ascii=False)
                                    )
                        except (json.JSONDecodeError, TypeError):
                            pass

                    self.chat.append({
                        "role": "tool",
                        "tool_call_id": tc.call_id,
                        "content": chat_content,
                    })
                    yield ("__TOOL_RESULT__", tool_result_event, None, gen)
                tool_exec_ms = (time.perf_counter() - tool_start) * 1000

                iterations_metrics.append({
                    "llm_ttft_ms": round(iter_ttft_ms) if iter_ttft_ms is not None else None,
                    "llm_total_ms": round(iter_llm_total_ms) if iter_llm_total_ms is not None else None,
                    "tool_calls": tool_names,
                    "tool_exec_ms": round(tool_exec_ms),
                })

                if cancelled_during_tools:
                    break

                logger.info("%sAgent loop [iter %d]: all tools executed, continuing LLM call%s", _Y, iteration, _R)
                continue

            # Should not reach here, but break to be safe
            break

        server_total_ms = (time.perf_counter() - t0) * 1000
        metrics = {
            "overall_ttft_ms": round(overall_ttft_ms) if overall_ttft_ms is not None else None,
            "server_llm_total_ms": round(server_total_ms),
            "server_e2e_ms": round((time.perf_counter() - self.cancel_scope.pipeline_start) * 1000) if self.cancel_scope and self.cancel_scope.pipeline_start else None,
            "server_asr_ms": self.cancel_scope.turn_asr_ms if self.cancel_scope else None,
            "iterations": iterations_metrics,
            "final": True,
        }
        if stream_error:
            metrics["stream_error"] = stream_error
        metrics["heartbeat"] = self._heartbeat_snapshot
        yield ("__LLM_METRICS__", metrics, None, gen)

        return (total_input_tokens, total_output_tokens)

    def _process_without_agent_loop(self, optional_kwargs, language_code, gen):
        """Original streaming/non-streaming logic (no agent loop).

        Returns:
            (input_tokens, output_tokens) via generator return value.
        """
        response = None
        tools: list[dict[str, str]] = []
        clean_text = ""
        input_tokens = 0
        output_tokens = 0
        llm_start = time.perf_counter()
        first_token_logged = False
        ttft_ms = None
        stream_error = None
        try:
            messages_for_api = self.chat.to_list()
            # Diagnostic: scan for non-serializable entries and clean them
            messages_for_api = _scan_messages_for_control(messages_for_api, logger)
            # Also scan optional_kwargs for hidden control messages
            _scan_kwargs_for_control(optional_kwargs, logger)
            log_llm_request(
                logger, "VoiceAgent.llm", self.model_name,
                messages_for_api, stream=self.stream, extra_body=self._extra_body,
                timeout=self.request_timeout, **optional_kwargs,
            )
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages_for_api,
                    stream=self.stream,
                    extra_body=self._extra_body,
                    timeout=self.request_timeout,
                    **optional_kwargs,
                )
            except TypeError as te:
                if "not JSON serializable" in str(te):
                    logger.error(
                        "SERIALIZE_FAIL: messages=%s | kwargs_keys=%s | kwargs=%s",
                        _safe_repr(messages_for_api),
                        list(optional_kwargs.keys()),
                        _safe_repr(optional_kwargs),
                    )
                raise
            if self.stream:
                cancelled = False
                printable_text = ""
                for chunk in response:
                    if gen is not None and self.cancel_scope.is_stale(gen):
                        logger.info("LLM generation cancelled (interruption)")
                        cancelled = True
                        break
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta and delta.content:
                        if not first_token_logged:
                            ttft_ms = (time.perf_counter() - llm_start) * 1000
                            cumul = ""
                            if self.cancel_scope and self.cancel_scope.pipeline_start:
                                cumul_ms = (time.perf_counter() - self.cancel_scope.pipeline_start) * 1000
                                cumul = f", cumul {cumul_ms:.0f}ms"
                            logger.info("LLM TTFT: %.0fms%s", ttft_ms, cumul)
                            first_token_logged = True
                        text_delta = (
                            remove_unspeechable(strip_markdown(strip_xml_tags(delta.content)))
                            if self.clean_response_text
                            else delta.content
                        )
                        clean_text += text_delta
                        printable_text += text_delta
                        sentences = split_sentences(printable_text)
                        if len(sentences) > 1:
                            buf = ""
                            for s in sentences[:-1]:
                                buf += s
                                if len(buf) >= 25:
                                    yield buf, language_code, [], gen
                                    buf = ""
                            printable_text = buf + sentences[-1]
                    if delta and delta.tool_calls:
                        for tc in delta.tool_calls:
                            tools.append(tc.model_dump())
                    usage = getattr(chunk, "usage", None)
                    if usage:
                        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                        output_tokens = getattr(usage, "completion_tokens", 0) or 0
                llm_total_ms = (time.perf_counter() - llm_start) * 1000
                consolidated_tools = self._consolidate_tool_deltas(tools) if tools else []
                tool_context = self._tool_context(gen)
                if consolidated_tools and getattr(self, "tool_registry", None) is not None:
                    for tool_call in consolidated_tools:
                        self.tool_registry.augment_tool_call_dict(tool_call, tool_context)
                if not cancelled:
                    if printable_text.strip() or consolidated_tools:
                        logger.info(f"{_G}LLM yielding: text='{printable_text.strip()[:50]}', tools={consolidated_tools}{_R}")
                        yield printable_text.strip(), language_code, consolidated_tools, gen
                    else:
                        logger.warning(f"LLM stream ended with no text (clean_text={clean_text!r})")
                cumul = ""
                if self.cancel_scope and self.cancel_scope.pipeline_start:
                    cumul_ms = (time.perf_counter() - self.cancel_scope.pipeline_start) * 1000
                    cumul = f", cumul {cumul_ms:.0f}ms"
                logger.info("LLM total: %.0fms%s (cancelled=%s)", llm_total_ms, cumul, cancelled)
                assistant_msg = self._assistant_history_message(
                    clean_text=clean_text,
                    consolidated_tools=consolidated_tools,
                    cancelled=cancelled,
                )
                if assistant_msg is not None:
                    self.chat.append(assistant_msg)
            else:
                if gen is not None and self.cancel_scope.is_stale(gen):
                    logger.info("LLM generation cancelled (interruption)")
                else:
                    usage = getattr(response, "usage", None)
                    if usage:
                        input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                        output_tokens = getattr(usage, "completion_tokens", 0) or 0
                    msg = response.choices[0].message
                    if msg.tool_calls:
                        for tc in msg.tool_calls:
                            tools.append(tc.model_dump())
                    tool_context = self._tool_context(gen)
                    if tools and getattr(self, "tool_registry", None) is not None:
                        for tool_call in tools:
                            self.tool_registry.augment_tool_call_dict(tool_call, tool_context)
                    if msg.content:
                        clean_text = (
                            remove_unspeechable(strip_markdown(strip_xml_tags(msg.content)))
                            if self.clean_response_text
                            else msg.content
                        )
                    output_text = clean_text
                    self.chat.append({"role": "assistant", "content": clean_text or None, **({"tool_calls": tools} if tools else {})})
                    logger.debug(f"Clean text: {clean_text}")
                    logger.info(f"Tools: {tools}")
                    if output_text.strip() or tools:
                        yield output_text.strip(), language_code, tools, gen
                llm_total_ms = (time.perf_counter() - llm_start) * 1000
        except httpx.ReadTimeout:
            logger.warning(
                "OpenAI API read timed out after %.1fs; ending the current response",
                self.request_timeout_s,
            )
            stream_error = "httpx_read_timeout"
            llm_total_ms = (time.perf_counter() - llm_start) * 1000
        finally:
            if response is not None and hasattr(response, "close"):
                try:
                    response.close()
                except Exception:
                    pass

        tool_names = []
        if tools:
            consolidated = self._consolidate_tool_deltas(tools)
            tool_names = [tc.get("function", {}).get("name", "?") for tc in consolidated] if consolidated else []

        metrics = {
            "overall_ttft_ms": round(ttft_ms) if ttft_ms is not None else None,
            "server_llm_total_ms": round(llm_total_ms),
            "server_e2e_ms": round((time.perf_counter() - self.cancel_scope.pipeline_start) * 1000) if self.cancel_scope and self.cancel_scope.pipeline_start else None,
            "server_asr_ms": self.cancel_scope.turn_asr_ms if self.cancel_scope else None,
            "iterations": [{
                "llm_ttft_ms": round(ttft_ms) if ttft_ms is not None else None,
                "llm_total_ms": round(llm_total_ms),
                "tool_calls": tool_names,
                "tool_exec_ms": None,
            }],
            # Single-shot path always emits exactly one metric event.
            "final": True,
        }
        if stream_error:
            metrics["stream_error"] = stream_error
        metrics["heartbeat"] = self._heartbeat_snapshot
        yield ("__LLM_METRICS__", metrics, None, gen)

        return (input_tokens, output_tokens)

    def process(self, prompt):
        # Eval-only: replace entire chat history with provided messages.
        if isinstance(prompt, tuple) and len(prompt) == 2 and prompt[0] == "__SET_HISTORY__":
            _, messages = prompt
            self.chat.reset()
            for msg in messages:
                self.chat.append(msg)
            logger.info("Chat history replaced (%d messages)", len(messages))
            return

        # Context-only: add user/input text to chat without generating.
        if isinstance(prompt, tuple) and len(prompt) == 3 and prompt[0] == "__ADD_TO_CONTEXT__":
            _, role, content = prompt
            text = content if isinstance(content, str) else str(content)
            self.chat.append({"role": role, "content": text})
            logger.debug("Added to LLM context (role=%s)", role)
            return

        # Context-only: add function-call result to chat without generating.
        # Skip if cancelled (barge-in happened while client was executing the tool).
        if isinstance(prompt, tuple) and len(prompt) == 3 and prompt[0] == "__FUNCTION_RESULT__":
            _, call_id, output = prompt
            if self.cancel_scope and self.cancel_scope.discarding:
                logger.info("Skipping stale function result (call_id=%s) — response was cancelled", call_id)
                return
            self.chat.append({"role": "tool", "tool_call_id": call_id, "content": str(output)})
            logger.debug("Added function result to LLM context (call_id=%s, %d chars)", call_id, len(str(output)))
            return

        language_code = None

        # Skip stale generate requests (barge-in happened while client was executing a tool)
        if isinstance(prompt, tuple) and len(prompt) == 3 and prompt[0] == "__GENERATE_RESPONSE__":
            if self.cancel_scope and self.cancel_scope.discarding:
                logger.info("Skipping stale __GENERATE_RESPONSE__ — response was cancelled")
                return
            _, override_instructions, override_tool_choice = prompt
            self._apply_runtime_config(override_tool_choice, override_instructions)
        else:
            self._apply_runtime_config()
            logger.debug("call api language model...")
            if isinstance(prompt, tuple):
                prompt, language_code = prompt
                if language_code[-5:] == "-auto":
                    language_code = language_code[:-5]
                    prompt = f"Please reply to my message in {WHISPER_LANGUAGE_TO_LLM_LANGUAGE[language_code]}. " + prompt
            self.chat.append({"role": self.user_role, "content": prompt})

        # --- Inject HeartBeat tool-call results from the predict side-branch ---
        self._inject_heartbeat_context()

        optional_kwargs = dict(self.gen_kwargs)
        if self.tools is not None:
            optional_kwargs["tools"] = self.tools
        if self.tools_choice is not None:
            optional_kwargs["tool_choice"] = self.tools_choice

        gen = self.cancel_scope.generation if self.cancel_scope else None

        # Yield formal-commit events for turn_end tools before the agent loop.
        # Downstream sees the tool_call + tool_result pairs, and the agent loop
        # will skip re-executing any tool whose signature matches.
        for tool_call_event, tool_result_event in self._heartbeat_formal_commits:
            yield "", language_code, [tool_call_event], gen
            yield ("__TOOL_RESULT__", tool_result_event, None, gen)

        # Response generation disabled (replay mode): we've already
        # emitted ``response.input_messages`` via ``_inject_heartbeat_context``.
        # Skip the actual OpenAI API call — the replay client only needs
        # the input messages snapshot, not the generated response.
        if getattr(self.runtime_config, "disable_response_generation", False):
            logger.info("Response generation disabled for replay; skipping LLM call")
            self._finalize_heartbeat_history()
            self.chat.strip_images()
            return

        try:
            if self._agent_loop_active:
                total_input, total_output = yield from self._process_with_agent_loop(
                    optional_kwargs, language_code, gen
                )
            else:
                total_input, total_output = yield from self._process_without_agent_loop(
                    optional_kwargs, language_code, gen
                )
        finally:
            self._finalize_heartbeat_history()

        self.chat.strip_images()

        # --- HeartBeat Interaction: dump formatted history for alignment verification ---
        try:
            from handlers.heartbeat_interaction.history_formatter import format_history_for_sft
            formatted_history = format_history_for_sft(self.chat.to_list())
            logger.debug(
                "\n\033[35m===== SFT History (HeartBeat Interaction alignment) =====\033[0m\n%s\n\033[35m===================================================\033[0m",
                formatted_history,
            )
        except Exception:
            logger.debug("HeartBeat Interaction history formatter not available", exc_info=True)

        if total_input or total_output:
            yield ("__TOKEN_USAGE__", total_input, total_output, gen)
        yield ("__END_OF_RESPONSE__", None, None, gen)

    def on_session_end(self):
        self.chat.reset()
        if self._initial_chat_message is not None:
            self.chat.init_chat(dict(self._initial_chat_message))
        self._last_instructions = self._initial_instructions
        self.tools = None
        self.tools_choice = None
        if self.heartbeat_cache is not None:
            self.heartbeat_cache.reset()
        self._heartbeat_formal_commits = []
        self._heartbeat_formal_commit_results_by_signature = {}
        logger.debug("OpenAI API language model session state reset (chat + tool cache)")

"""Server-side tool registry for the agent loop.

Tools registered here are executed automatically by the LLM handler
on the server side, without requiring a client round-trip.
"""

import json
import logging
import copy
import inspect
import os
import random
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from pipeline.cancel_scope import CancelScope
from handlers.llm.tool_call.tool_execution import ToolExecutionHarness, ToolPolicy

logger = logging.getLogger(__name__)


@dataclass
class NormalizedToolCall:
    """Uniform representation of a tool call, regardless of API format."""

    call_id: str
    name: str
    arguments: str  # JSON string
    raw_dict: dict = field(default_factory=dict, repr=False)


class ToolRegistry:
    """Registry of server-side tools that the agent loop can execute.

    Usage::

        registry = ToolRegistry()
        registry.register("get_weather", get_weather_fn,
                          description="Get weather", parameters={...})

        if registry.has("get_weather"):
            result = registry.execute("get_weather", '{"city": "Beijing"}')
    """

    def __init__(
        self,
        timeout_s: float = 30.0,
        execution_harness: ToolExecutionHarness | None = None,
        context_provider: Callable[[], dict[str, Any]] | None = None,
    ):
        self._tools: dict[str, dict] = {}
        self._timeout_s = timeout_s
        self._lock = threading.Lock()
        self._execution_harness = execution_harness or ToolExecutionHarness()
        self._context_provider = context_provider
        self._dynamic_tool_names: set[str] = set()
        self._dynamic_overrides: dict[str, dict] = {}
        self._dynamic_mock_lock = threading.Lock()
        self._dynamic_mock_caches: dict[str, Any] = {}
        self._dynamic_mock_prior_results: dict[str, list[dict[str, Any]]] = {}
        self._dynamic_mock_client: Any | None = None

    def set_context_provider(self, provider: Callable[[], dict[str, Any]] | None) -> None:
        self._context_provider = provider

    def register(
        self,
        name: str,
        fn: Callable,
        description: str = "",
        parameters: dict | None = None,
        policy: ToolPolicy | None = None,
        hidden_fields: list[str] | None = None,
    ) -> None:
        """Register a tool function.

        Args:
            name: Tool name (must match the name the LLM will call).
            fn: Callable to execute when the tool is invoked.
            description: Human-readable description exposed to the LLM.
            parameters: JSON Schema dict for the tool's parameters.
            hidden_fields: Parameter names to hide from the LLM and inject
                from server-side context at execution time.  When *None*,
                ``session_id`` and ``user_id`` are auto-detected from
                ``parameters.properties`` for backward compatibility.
        """
        with self._lock:
            self._tools[name] = {
                "fn": fn,
                "description": description,
                "parameters": parameters or {"type": "object", "properties": {}},
                "policy": policy or ToolPolicy.read(),
                "hidden_fields": hidden_fields,
            }
        logger.info("Registered server tool: %s", name)

    def register_django_tools(
        self,
        schemas: list[dict],
        tenant_id: str,
    ) -> int:
        """Register Django tool schemas with bridge execution functions.

        Each Django tool is wrapped in a sync bridge callable that calls
        ``BaseTool.execute()`` asynchronously via ``asyncio.run``.

        Tools already registered (e.g. from YAML ``tools_module``) take
        precedence and are **not** overwritten.

        Returns the number of newly registered tools.
        """
        from voice_django.django_tool_bridge import (
            make_django_bridge_fn,
            get_django_hidden_fields,
            get_django_tool_policy,
        )

        count = 0
        for schema in schemas or []:
            function = schema.get("function", schema) if isinstance(schema, dict) else {}
            name = function.get("name")
            if not name:
                continue
            with self._lock:
                if name in self._tools:
                    logger.info("Skipping Django tool '%s' (already registered)", name)
                    continue
            description = function.get("description", "")
            parameters = function.get("parameters", {"type": "object", "properties": {}})
            hidden_fields = get_django_hidden_fields(name, tenant_id)
            policy = get_django_tool_policy(name, tenant_id)
            bridge_fn = make_django_bridge_fn(name, tenant_id)
            self.register(
                name=name,
                fn=bridge_fn,
                description=description,
                parameters=parameters,
                hidden_fields=hidden_fields or None,
                policy=policy,
            )
            count += 1
        if count:
            logger.info(
                "Registered %d Django tools (tenant=%s): %s",
                count, tenant_id,
                [s.get("function", {}).get("name", "") for s in schemas or []],
            )
        return count

    def install_dynamic_tools(
        self,
        tools: list[dict],
        tool_mock_examples: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        """Install sample-level dynamic tools for evaluation.

        Dynamic tool-use datasets provide a fresh tool schema per sample. This
        lets the same server-side execution path run those tools without a real
        backend: each dynamic tool returns a deterministic JSON payload containing
        the tool name and arguments. Previous dynamic tools are removed or restored
        before installing the new sample's tools.
        """
        with self._lock:
            self._clear_dynamic_tools_locked()
            for tool_def in tools or []:
                name, description, parameters = self._parse_tool_schema(tool_def)
                if not name:
                    continue
                if name in self._tools:
                    self._dynamic_overrides[name] = self._tools[name]
                examples = []
                if isinstance(tool_mock_examples, dict):
                    raw_examples = tool_mock_examples.get(name)
                    if isinstance(raw_examples, list):
                        examples = [item for item in raw_examples if isinstance(item, dict)]
                self._tools[name] = {
                    "fn": self._make_dynamic_tool(name, parameters, description, examples),
                    "description": description or f"Dynamic implementation for {name}.",
                    "parameters": parameters or {"type": "object", "properties": {}},
                    "policy": ToolPolicy.read(),
                    "dynamic": True,
                }
                self._dynamic_tool_names.add(name)
            logger.info("Installed %d dynamic tools: %s", len(self._dynamic_tool_names), sorted(self._dynamic_tool_names))

    def clear_dynamic_tools(self) -> None:
        """Remove sample-level dynamic tools and restore any overridden tools."""
        with self._lock:
            self._clear_dynamic_tools_locked()

    def _clear_dynamic_tools_locked(self) -> None:
        for name in list(self._dynamic_tool_names):
            previous = self._dynamic_overrides.pop(name, None)
            if previous is not None:
                self._tools[name] = previous
            else:
                self._tools.pop(name, None)
        self._dynamic_tool_names.clear()

    @staticmethod
    def _parse_tool_schema(tool_def: dict) -> tuple[str, str, dict]:
        if not isinstance(tool_def, dict):
            return "", "", {"type": "object", "properties": {}}
        func = tool_def.get("function")
        if isinstance(func, dict):
            return (
                str(func.get("name") or ""),
                str(func.get("description") or ""),
                ToolRegistry._normalize_json_schema(func.get("parameters") or {"type": "object", "properties": {}}),
            )
        return (
            str(tool_def.get("name") or ""),
            str(tool_def.get("description") or ""),
            ToolRegistry._normalize_json_schema(tool_def.get("parameters") or {"type": "object", "properties": {}}),
        )

    @staticmethod
    def _normalize_json_schema(schema: dict) -> dict:
        """Fill minimal JSON Schema ``type`` fields required by chat tool APIs."""
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
                key: ToolRegistry._normalize_json_schema(value)
                for key, value in properties.items()
            }

        items = normalized.get("items")
        if isinstance(items, dict):
            normalized["items"] = ToolRegistry._normalize_json_schema(items)
        elif isinstance(items, list):
            normalized["items"] = [
                ToolRegistry._normalize_json_schema(item) if isinstance(item, dict) else item
                for item in items
            ]

        return normalized

    def _make_dynamic_tool(
        self,
        name: str,
        parameters: dict | None = None,
        description: str = "",
        tool_examples: list[dict[str, Any]] | None = None,
    ) -> Callable:
        def _dynamic_tool(_tool_context: dict[str, Any] | None = None, **kwargs) -> str:
            use_llm_mock = os.getenv("HEARTBEAT_DYNAMIC_TOOL_EXECUTOR", "").lower() == "llm_mock"
            result = self._build_dynamic_mock_result_if_enabled(
                name=name,
                arguments=kwargs,
                parameters=parameters or {},
                tool_examples=tool_examples or [],
                tool_context=_tool_context or {},
            )
            if result is None and use_llm_mock:
                raise RuntimeError(f"LLM mock did not produce a result for dynamic tool '{name}'")
            if result is None:
                result = ToolRegistry._build_dynamic_result(name, kwargs, parameters or {}, description)
            return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)

        return _dynamic_tool

    def _build_dynamic_mock_result_if_enabled(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        parameters: dict,
        tool_examples: list[dict[str, Any]],
        tool_context: dict[str, Any],
    ) -> Any | None:
        if os.getenv("HEARTBEAT_DYNAMIC_TOOL_EXECUTOR", "").lower() != "llm_mock":
            return None
        try:
            from distillation_replay.mock_tool import (
                ToolMockCache,
                ToolMockLLMClient,
                ToolMockLLMConfig,
            )
        except Exception:
            logger.exception("Failed to import distillation replay tool mock client")
            return None

        if not tool_examples:
            logger.warning(
                "LLM mock requested for dynamic tool %s without internal tool_mock_examples; generating schema-only result",
                name,
            )

        conversation_key = self._dynamic_mock_conversation_key(tool_context)
        with self._dynamic_mock_lock:
            cache = self._dynamic_mock_caches.setdefault(conversation_key, ToolMockCache())
            cached = cache.get(name, arguments)
            if cached is not None:
                return cached
            prior_results = list(self._dynamic_mock_prior_results.get(conversation_key, []))
            if self._dynamic_mock_client is None:
                config = ToolMockLLMConfig.from_env()
                if config is None:
                    logger.warning("HEARTBEAT_DYNAMIC_TOOL_EXECUTOR=llm_mock set without HEARTBEAT_TOOL_MOCK_BASE_URL")
                    return None
                self._dynamic_mock_client = ToolMockLLMClient(config)

        result, meta = self._dynamic_mock_client.generate(
            tool_name=name,
            tool_schema=parameters,
            arguments=arguments,
            tool_examples=tool_examples,
            conversation_prior_mock_results=prior_results,
        )
        simulated_latency_ms = random.randint(
            int(os.getenv("HEARTBEAT_TOOL_MOCK_SIMULATED_LATENCY_MIN_MS", "20")),
            int(os.getenv("HEARTBEAT_TOOL_MOCK_SIMULATED_LATENCY_MAX_MS", "100")),
        )
        logger.info(
            "Dynamic tool LLM mock result generated: tool=%s wall_ms=%s simulated_ms=%s",
            name,
            meta.get("mock_wall_latency_ms"),
            simulated_latency_ms,
        )
        with self._dynamic_mock_lock:
            cache = self._dynamic_mock_caches.setdefault(conversation_key, ToolMockCache())
            cache.put(name, arguments, result)
            self._dynamic_mock_prior_results.setdefault(conversation_key, []).append({
                "arguments": arguments,
                "result": result,
            })
        return result

    @staticmethod
    def _dynamic_mock_conversation_key(tool_context: dict[str, Any]) -> str:
        for key in ("conversation_id", "session_id", "turn_id", "generation"):
            value = tool_context.get(key)
            if value not in (None, ""):
                return f"{key}:{value}"
        return "default"

    @staticmethod
    def _build_dynamic_result(
        name: str,
        arguments: dict[str, Any],
        parameters: dict,
        description: str = "",
    ) -> dict[str, Any]:
        """Build a business-shaped sample result for evaluation-only dynamic tools.

        The result is intentionally shaped like a real backend payload. It must
        not expose test harness markers such as "dynamic", "mock", tool names,
        or execution-status boilerplate to the LLM.
        """
        lowered = f"{name} {description}".lower()

        def first_arg(*keys: str, default: Any = None) -> Any:
            for key in keys:
                value = arguments.get(key)
                if value not in (None, "", [], {}):
                    return value
            return default

        if "historical" in lowered and ("price" in lowered or "stock" in lowered):
            ticker = str(first_arg("ticker", "symbol", default="MSFT")).upper()
            return {
                "ticker": ticker,
                "currency": "USD",
                "daily_prices": [
                    {"date": "2026-06-17", "open": 477.80, "high": 481.35, "low": 475.22, "close": 480.12, "volume": 18423000},
                    {"date": "2026-06-18", "open": 480.25, "high": 485.10, "low": 479.40, "close": 483.76, "volume": 19287000},
                    {"date": "2026-06-19", "open": 483.90, "high": 487.62, "low": 481.88, "close": 486.21, "volume": 20154000},
                    {"date": "2026-06-22", "open": 486.00, "high": 489.34, "low": 484.55, "close": 488.02, "volume": 17691000},
                    {"date": "2026-06-23", "open": 488.45, "high": 491.20, "low": 487.16, "close": 490.37, "volume": 16988000},
                ],
            }

        if "weather" in lowered:
            location = first_arg("location", "city", "place", default="current location")
            return {
                "location": location,
                "condition": "partly cloudy",
                "temperature_c": 27,
                "humidity_percent": 68,
                "wind_kph": 12,
            }

        if "time" in lowered:
            return {
                "timezone": first_arg("timezone", "location", default="UTC"),
                "current_time": "2026-06-23T11:30:00+08:00",
            }

        if "password" in lowered and "strength" in lowered:
            password = str(first_arg("password", default=""))
            score = min(100, max(20, len(password) * 8))
            return {
                "score": score,
                "level": "strong" if score >= 80 else "medium" if score >= 50 else "weak",
                "recommendations": [] if score >= 80 else ["Use a longer password with mixed character types."],
            }

        if "body mass index" in lowered or "bmi" in lowered:
            weight = float(first_arg("weight", default=80))
            height = float(first_arg("height", default=170))
            units = str(first_arg("units", default="metric"))
            if units == "imperial":
                bmi = weight / (height * height) * 703
            else:
                bmi = weight / ((height / 100) ** 2)
            return {
                "bmi": round(bmi, 1),
                "category": "normal" if 18.5 <= bmi < 25 else "outside normal range",
            }

        if "order" in lowered and "food" in lowered:
            return {
                "order_id": "ORD-789012",
                "status": "confirmed",
                "restaurant": first_arg("restaurant", default="restaurant"),
                "items": first_arg("items", default=[]),
                "estimated_ready_time": "30 minutes",
            }

        if "photo" in lowered or "image" in lowered:
            target_id = first_arg("property_id", "is_id", "id", "chapter_id", default="item")
            return {
                "id": target_id,
                "photos": [
                    {"url": f"https://example.com/assets/{target_id}/1.jpg", "description": "Exterior view"},
                    {"url": f"https://example.com/assets/{target_id}/2.jpg", "description": "Interior view"},
                    {"url": f"https://example.com/assets/{target_id}/3.jpg", "description": "Detail view"},
                ],
            }

        if "company" in lowered:
            query = first_arg("query", "company", "name", default="company")
            return {
                "company": {
                    "name": query,
                    "industry": "technology",
                    "website": "https://www.example.com",
                    "description": f"{query} is listed as a technology company.",
                }
            }

        if "channel" in lowered:
            channel_id = first_arg("is_id", "id", "channel_id", default="channel")
            return {
                "channel_id": channel_id,
                "title": "Sample Channel",
                "subscriber_count": 125000,
                "video_count": 342,
            }

        if "email" in lowered and "server" in lowered:
            domain = first_arg("domain", default="example.com")
            return {
                "domain": domain,
                "mx_records_found": True,
                "smtp_reachable": True,
            }

        properties = parameters.get("properties") if isinstance(parameters, dict) else {}
        normalized_args = dict(arguments)
        if isinstance(properties, dict):
            for key, schema in properties.items():
                if key not in normalized_args and isinstance(schema, dict) and "default" in schema:
                    normalized_args[key] = schema["default"]

        return {
            "request": normalized_args,
            "items": [
                {
                    "id": "sample-1",
                    "title": name.replace("_", " ").strip().title(),
                    "summary": "The requested record is available.",
                }
            ],
        }

    def get(self, name: str) -> Callable | None:
        """Return the callable for *name*, or None if not registered."""
        entry = self._tools.get(name)
        return entry["fn"] if entry else None

    def has(self, name: str) -> bool:
        return name in self._tools

    def is_dynamic(self, name: str) -> bool:
        entry = self._tools.get(name)
        return bool(entry and entry.get("dynamic"))

    def __len__(self) -> int:
        return len(self._tools)

    def all_server_tool_names(self) -> set[str]:
        """Return the set of tool names registered server-side."""
        return set(self._tools.keys())

    def policy(self, name: str) -> ToolPolicy | None:
        entry = self._tools.get(name)
        return entry.get("policy") if entry else None

    def parameters(self, name: str) -> dict | None:
        entry = self._tools.get(name)
        return copy.deepcopy(entry.get("parameters")) if entry else None

    def execute(
        self,
        name: str,
        arguments_json: str,
        cancel_scope: CancelScope | None = None,
        gen: int | None = None,
        *,
        source: str = "main_llm",
        context: dict[str, Any] | None = None,
    ) -> str | None:
        """Execute a tool through the policy/idempotency harness."""
        entry = self._tools.get(name)
        if entry is None:
            return f"Error: tool '{name}' not found"

        exec_context = self._current_context(context)
        if gen is not None:
            exec_context.setdefault("generation", gen)
            exec_context.setdefault("turn_id", f"gen:{gen}")
        arguments_json = self._augment_arguments_json(name, arguments_json, exec_context)

        return self._execution_harness.execute(
            tool_name=name,
            arguments_json=arguments_json,
            policy=entry.get("policy") or ToolPolicy.read(),
            raw_executor=lambda: self._execute_direct(
                name,
                arguments_json,
                cancel_scope=cancel_scope,
                gen=gen,
                tool_context=exec_context,
            ),
            source=source,
            context=exec_context,
        )

    def _current_context(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        provider_context: dict[str, Any] = {}
        if self._context_provider is not None:
            try:
                provider_context = dict(self._context_provider() or {})
            except Exception:
                logger.debug("Tool context provider failed", exc_info=True)
        merged = dict(provider_context)
        merged.update(context or {})
        for key in ("session_id", "user_id"):
            if provider_context.get(key):
                merged[key] = provider_context[key]
        return merged

    def augment_arguments(
        self,
        name: str,
        arguments: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a copy of *arguments* with runtime-managed fields applied."""
        arguments_json = json.dumps(arguments, ensure_ascii=False)
        augmented_json = self.augment_arguments_json(name, arguments_json, context)
        try:
            augmented = json.loads(augmented_json) if augmented_json else {}
        except json.JSONDecodeError:
            return dict(arguments)
        return augmented if isinstance(augmented, dict) else dict(arguments)

    def augment_arguments_json(
        self,
        name: str,
        arguments_json: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Apply runtime-managed tool arguments such as session/user identity.

        The model is allowed to omit these fields or get them wrong.  The
        server-side execution environment is the source of truth, so these
        values are overwritten before logging, caching, deduping, or executing.
        """
        return self._augment_arguments_json(name, arguments_json, self._current_context(context))

    def augment_tool_call_dict(
        self,
        tool_call: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Mutate a Chat/Responses API tool-call dict with runtime arguments."""
        if not isinstance(tool_call, dict):
            return tool_call

        function = tool_call.get("function")
        if isinstance(function, dict):
            name = function.get("name", "")
            if name:
                function["arguments"] = self.augment_arguments_json(
                    name,
                    function.get("arguments", "") or "{}",
                    context,
                )
            return tool_call

        name = tool_call.get("name", "")
        if name:
            tool_call["arguments"] = self.augment_arguments_json(
                name,
                tool_call.get("arguments", "") or "{}",
                context,
            )
        return tool_call

    def _augment_arguments_json(
        self,
        name: str,
        arguments_json: str,
        context: dict[str, Any],
    ) -> str:
        entry = self._tools.get(name)
        if entry is None:
            return arguments_json
        parameters = entry.get("parameters") or {}
        injectable = {
            key: context.get(key)
            for key in self._runtime_managed_argument_names(name)
            if context.get(key)
        }
        if not injectable:
            return arguments_json
        try:
            arguments = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError:
            return arguments_json
        if not isinstance(arguments, dict):
            return arguments_json
        changed = False
        for key, value in injectable.items():
            if arguments.get(key) != value:
                arguments[key] = value
                changed = True
        if not changed:
            return arguments_json
        return json.dumps(arguments, ensure_ascii=False)

    def _runtime_managed_argument_names(self, name: str) -> tuple[str, ...]:
        """Return parameter names that should be injected from server context.

        Priority:
        1. Explicit ``hidden_fields`` set at registration time.
        2. Auto-detect ``session_id`` / ``user_id`` from ``parameters.properties``
           (backward compatibility for YAML-registered tools).
        """
        entry = self._tools.get(name)
        if entry is None:
            return ()
        if entry.get("dynamic"):
            return ()
        hidden = entry.get("hidden_fields")
        if hidden is not None:
            return tuple(hidden)
        # Backward-compatible auto-detection
        parameters = entry.get("parameters") or {}
        properties = parameters.get("properties") if isinstance(parameters, dict) else {}
        if not isinstance(properties, dict):
            return ()
        return tuple(key for key in ("session_id", "user_id") if key in properties)

    def _parameters_for_model_schema(self, name: str, parameters: dict) -> dict:
        schema = self._normalize_json_schema(parameters)
        entry = self._tools.get(name)
        if entry and entry.get("dynamic"):
            return schema
        hidden = self._runtime_managed_argument_names(name)
        if not hidden:
            return schema
        properties = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(properties, dict):
            return schema
        for key in hidden:
            properties.pop(key, None)
        required = schema.get("required")
        if isinstance(required, list):
            schema["required"] = [item for item in required if item not in set(hidden)]
        return schema

    def _execute_direct(
        self,
        name: str,
        arguments_json: str,
        cancel_scope: CancelScope | None = None,
        gen: int | None = None,
        tool_context: dict[str, Any] | None = None,
    ) -> str | None:
        """Execute a tool by name, returning its raw result as a string.

        Runs the tool in a background thread and polls cancel_scope so that
        a barge-in can abort the wait without waiting for the tool's full
        timeout.

        Args:
            name: Tool name.
            arguments_json: JSON string of keyword arguments.
            cancel_scope: If provided, checked during tool execution.
            gen: Generation counter captured before the LLM call.

        Returns:
            The tool's return value converted to string, an error message,
            or None if cancelled while the tool was still running.
        """
        fn = self.get(name)
        if fn is None:
            return f"Error: tool '{name}' not found"

        try:
            kwargs = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError as e:
            return f"Error: invalid JSON arguments for '{name}': {e}"
        try:
            if "_tool_context" in inspect.signature(fn).parameters:
                kwargs["_tool_context"] = dict(tool_context or {})
        except (TypeError, ValueError):
            pass

        # Fast path: no cancel scope, just call synchronously
        if cancel_scope is None or gen is None:
            try:
                result = fn(**kwargs)
                return str(result)
            except Exception as e:
                logger.exception("Tool '%s' execution failed", name)
                return f"Error executing tool '{name}': {e}"

        # Run tool in a thread, poll cancel_scope while waiting
        result_box: list[Any] = [None]
        error_box: list[Exception | None] = [None]

        def _run():
            try:
                result_box[0] = fn(**kwargs)
            except Exception as exc:
                error_box[0] = exc

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        while thread.is_alive():
            thread.join(timeout=0.05)
            if cancel_scope.is_stale(gen):
                logger.info("Tool '%s' execution cancelled (barge-in)", name)
                return None

        if error_box[0] is not None:
            logger.exception("Tool '%s' execution failed", name)
            return f"Error executing tool '{name}': {error_box[0]}"

        return str(result_box[0])

    def tool_schemas(self) -> list[dict]:
        """Return tool definitions in Realtime API format (flat name/parameters)."""
        schemas = []
        for name, entry in self._tools.items():
            schemas.append({
                "type": "function",
                "name": name,
                "description": entry["description"],
                "parameters": self._parameters_for_model_schema(name, entry["parameters"]),
            })
        return schemas

    def tool_schemas_chat_api(self) -> list[dict]:
        """Return tool definitions in Chat Completions API format (nested function.name)."""
        schemas = []
        for name, entry in self._tools.items():
            schemas.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": entry["description"],
                    "parameters": self._parameters_for_model_schema(name, entry["parameters"]),
                },
            })
        return schemas

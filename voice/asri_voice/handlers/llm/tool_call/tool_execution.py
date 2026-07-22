"""Policy-aware tool execution harness.

This layer owns safety controls around tool calls. The model and HeartBeat
Thinking may propose registered tool calls, but this harness decides whether
they can be executed, whether they should be deduped, and what execution record
to return.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class ToolExecutionState(str, Enum):
    """Explicit write-tool execution state machine states."""

    PROPOSED = "PROPOSED"
    ACCUMULATED = "ACCUMULATED"
    BLOCKED_BY_PERMISSION = "BLOCKED_BY_PERMISSION"
    DEDUPED_RUNNING = "DEDUPED_RUNNING"
    DEDUPED_COMPLETED = "DEDUPED_COMPLETED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PRECONDITION_REQUIRED = "PRECONDITION_REQUIRED"

    @property
    def status(self) -> str:
        if self is ToolExecutionState.ACCUMULATED:
            return "accumulated"
        if self is ToolExecutionState.BLOCKED_BY_PERMISSION:
            return "blocked"
        if self in (ToolExecutionState.DEDUPED_RUNNING, ToolExecutionState.DEDUPED_COMPLETED):
            return "deduped"
        if self is ToolExecutionState.PRECONDITION_REQUIRED:
            return "precondition_required"
        return self.value.lower()


@dataclass(frozen=True)
class ToolPolicy:
    """Execution policy for a registered tool."""

    READ_ONLY_REPEATABLE = "read_only_repeatable"
    STATE_ACCUMULATED_AUTO = "state_accumulated_auto"
    TURN_IDEMPOTENT_ONCE = "turn_idempotent_once"
    STATE_MACHINE_COMMIT = "state_machine_commit"

    permission_level: str = "read_only_repeatable"
    effect: str = "read"  # "read" or "write"
    allowed_sources: tuple[str, ...] | None = None
    idempotency_scope: str | None = None  # "turn", "session", "user", "global", or None
    idempotency_fields: tuple[str, ...] | None = None
    duplicate_strategy: str = "reuse"  # "reuse", "reject", or "always_new"
    lock_ttl_s: float = 30.0

    @classmethod
    def read(cls) -> "ToolPolicy":
        return cls(
            permission_level=cls.READ_ONLY_REPEATABLE,
            effect="read",
            allowed_sources=("main_llm", "heartbeat_thinking"),
        )

    @classmethod
    def write(
        cls,
        *,
        allowed_sources: tuple[str, ...] = ("main_llm",),
        idempotency_scope: str = "turn",
        idempotency_fields: tuple[str, ...] | None = None,
        duplicate_strategy: str = "reuse",
        lock_ttl_s: float = 30.0,
        permission_level: str | None = None,
    ) -> "ToolPolicy":
        if permission_level is None:
            permission_level = (
                cls.TURN_IDEMPOTENT_ONCE
                if "heartbeat_thinking" in allowed_sources
                else cls.STATE_MACHINE_COMMIT
            )
        return cls(
            permission_level=permission_level,
            effect="write",
            allowed_sources=allowed_sources,
            idempotency_scope=idempotency_scope,
            idempotency_fields=idempotency_fields,
            duplicate_strategy=duplicate_strategy,
            lock_ttl_s=lock_ttl_s,
        )

    @classmethod
    def state_accumulated_auto(
        cls,
        *,
        allowed_sources: tuple[str, ...] = ("main_llm", "heartbeat_thinking", "heartbeat_turn_end"),
        idempotency_scope: str = "turn",
        idempotency_fields: tuple[str, ...] | None = None,
        duplicate_strategy: str = "reuse",
        lock_ttl_s: float = 30.0,
    ) -> "ToolPolicy":
        return cls(
            permission_level=cls.STATE_ACCUMULATED_AUTO,
            effect="write",
            allowed_sources=allowed_sources,
            idempotency_scope=idempotency_scope,
            idempotency_fields=idempotency_fields,
            duplicate_strategy=duplicate_strategy,
            lock_ttl_s=lock_ttl_s,
        )

    def is_write(self) -> bool:
        return self.effect == "write"

    def normalized_permission_level(self) -> str:
        if not self.is_write():
            return self.READ_ONLY_REPEATABLE
        if self.permission_level in {
            self.READ_ONLY_REPEATABLE,
            self.STATE_ACCUMULATED_AUTO,
            self.TURN_IDEMPOTENT_ONCE,
            self.STATE_MACHINE_COMMIT,
        }:
            return self.permission_level
        if self.allowed_sources and "heartbeat_thinking" in self.allowed_sources:
            return self.TURN_IDEMPOTENT_ONCE
        return self.STATE_MACHINE_COMMIT

    def is_source_allowed(self, source: str) -> bool:
        allowed = self.allowed_sources
        if allowed is None:
            allowed = ("main_llm",) if self.is_write() else ("main_llm", "heartbeat_thinking")
        return source in allowed


@dataclass
class ToolExecutionRecord:
    execution_id: str
    idempotency_key: str
    tool_name: str
    arguments: dict[str, Any]
    source: str
    state: ToolExecutionState
    result: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @property
    def status(self) -> str:
        return self.state.status


class InMemoryExecutionStore:
    """Thread-safe in-process execution store.

    This is intentionally small. It can be replaced by Redis/DB later without
    changing callers of ToolExecutionHarness.
    """

    def __init__(self):
        self._records: dict[str, ToolExecutionRecord] = {}
        self._lock = threading.Lock()

    def get(self, idempotency_key: str) -> ToolExecutionRecord | None:
        with self._lock:
            return self._records.get(idempotency_key)

    def create_running(
        self,
        *,
        idempotency_key: str,
        tool_name: str,
        arguments: dict[str, Any],
        source: str,
    ) -> ToolExecutionRecord:
        with self._lock:
            record = ToolExecutionRecord(
                execution_id=str(uuid.uuid4()),
                idempotency_key=idempotency_key,
                tool_name=tool_name,
                arguments=arguments,
                source=source,
                state=ToolExecutionState.RUNNING,
            )
            self._records[idempotency_key] = record
            return record

    def complete(self, idempotency_key: str, result: str) -> None:
        with self._lock:
            record = self._records[idempotency_key]
            record.state = ToolExecutionState.COMPLETED
            record.result = result
            record.error = None
            record.updated_at = time.time()

    def fail(
        self,
        idempotency_key: str,
        error: str,
        state: ToolExecutionState = ToolExecutionState.FAILED,
    ) -> None:
        with self._lock:
            record = self._records[idempotency_key]
            record.state = state
            record.error = error
            record.updated_at = time.time()


class IdempotencyKeyBuilder:
    """Builds canonical idempotency keys from tool name, args, and context."""

    @staticmethod
    def build(
        *,
        tool_name: str,
        arguments: dict[str, Any],
        policy: ToolPolicy,
        context: dict[str, Any] | None,
    ) -> str | None:
        if policy.idempotency_scope is None or policy.duplicate_strategy == "always_new":
            return None

        context = context or {}
        scope_value = IdempotencyKeyBuilder._scope_value(policy.idempotency_scope, context)
        selected_args = IdempotencyKeyBuilder._selected_args(arguments, policy.idempotency_fields)
        payload = {
            "tool": tool_name,
            "scope": policy.idempotency_scope,
            "scope_value": scope_value,
            "args": selected_args,
        }
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        return f"{tool_name}:{policy.idempotency_scope}:{scope_value}:{digest}"

    @staticmethod
    def _scope_value(scope: str, context: dict[str, Any]) -> str:
        if scope == "turn":
            return str(context.get("turn_id") or context.get("generation") or f"implicit_turn:{uuid.uuid4()}")
        if scope == "session":
            return str(context.get("session_id") or "unknown_session")
        if scope == "user":
            return str(context.get("user_id") or "unknown_user")
        if scope == "global":
            return "global"
        return str(context.get(scope) or f"unknown_{scope}")

    @staticmethod
    def _selected_args(
        arguments: dict[str, Any],
        fields: tuple[str, ...] | None,
    ) -> dict[str, Any]:
        if not fields:
            return arguments
        return {field: arguments.get(field) for field in fields}


class ToolExecutionHarness:
    """Central policy/idempotency gate in front of raw tool execution."""

    def __init__(self, store: InMemoryExecutionStore | None = None):
        self.store = store or InMemoryExecutionStore()

    def execute(
        self,
        *,
        tool_name: str,
        arguments_json: str,
        policy: ToolPolicy,
        raw_executor: Callable[[], str | None],
        source: str = "main_llm",
        context: dict[str, Any] | None = None,
    ) -> str | None:
        try:
            arguments = json.loads(arguments_json) if arguments_json else {}
            if not isinstance(arguments, dict):
                error = f"Error: arguments for '{tool_name}' must be a JSON object"
                if policy.is_write():
                    return self._state_result(
                        ToolExecutionState.FAILED,
                        [ToolExecutionState.PROPOSED, ToolExecutionState.FAILED],
                        executed=False,
                        tool_name=tool_name,
                        arguments_raw=arguments_json,
                        source=source,
                        error=error,
                    )
                return error
        except json.JSONDecodeError as exc:
            error = f"Error: invalid JSON arguments for '{tool_name}': {exc}"
            if policy.is_write():
                return self._state_result(
                    ToolExecutionState.FAILED,
                    [ToolExecutionState.PROPOSED, ToolExecutionState.FAILED],
                    executed=False,
                    tool_name=tool_name,
                    arguments_raw=arguments_json,
                    source=source,
                    error=error,
                )
            return error

        if not policy.is_write():
            raw = raw_executor()
            precondition = self._business_precondition(raw)
            if precondition:
                return self._state_result(
                    ToolExecutionState.PRECONDITION_REQUIRED,
                    [
                        ToolExecutionState.PROPOSED,
                        ToolExecutionState.RUNNING,
                        ToolExecutionState.PRECONDITION_REQUIRED,
                    ],
                    executed=False,
                    tool_name=tool_name,
                    arguments=arguments,
                    source=source,
                    precondition=precondition,
                    error=raw,
                )
            return raw

        permission_level = policy.normalized_permission_level()
        if permission_level == ToolPolicy.STATE_ACCUMULATED_AUTO and source == "heartbeat_thinking":
            return self._state_result(
                ToolExecutionState.ACCUMULATED,
                [ToolExecutionState.PROPOSED, ToolExecutionState.ACCUMULATED],
                executed=False,
                tool_name=tool_name,
                arguments=arguments,
                source=source,
                permission_level=permission_level,
                pending_execution_stage="turn_end",
            )

        if not policy.is_source_allowed(source):
            allowed_sources = tuple(policy.allowed_sources or ("main_llm",))
            return self._state_result(
                ToolExecutionState.BLOCKED_BY_PERMISSION,
                [ToolExecutionState.PROPOSED, ToolExecutionState.BLOCKED_BY_PERMISSION],
                executed=False,
                tool_name=tool_name,
                arguments=arguments,
                source=source,
                permission_level=permission_level,
                allowed_sources=list(allowed_sources),
                retry_with_allowed_source="main_llm" in allowed_sources and source != "main_llm",
                retry_instruction=(
                    "This call was blocked only for the current source. "
                    "If the user still wants this action and preconditions are satisfied, "
                    "an allowed source should call the same tool with the same arguments."
                ),
                blocked_reason=(
                    f"source '{source}' is not allowed to execute write tool '{tool_name}'"
                ),
            )

        idempotency_key = IdempotencyKeyBuilder.build(
            tool_name=tool_name,
            arguments=arguments,
            policy=policy,
            context=context,
        )
        if idempotency_key is None:
            raw = raw_executor()
            return self._finalize_raw_result(
                raw,
                tool_name=tool_name,
                arguments=arguments,
                source=source,
                permission_level=permission_level,
                transition=[ToolExecutionState.PROPOSED, ToolExecutionState.RUNNING],
            )

        existing = self.store.get(idempotency_key)
        if existing and existing.state in (
            ToolExecutionState.RUNNING,
            ToolExecutionState.COMPLETED,
        ):
            state = (
                ToolExecutionState.DEDUPED_RUNNING
                if existing.state is ToolExecutionState.RUNNING
                else ToolExecutionState.DEDUPED_COMPLETED
            )
            if policy.duplicate_strategy == "reject":
                return self._state_result(
                    state,
                    [ToolExecutionState.PROPOSED, state],
                    executed=False,
                    tool_name=tool_name,
                    arguments=arguments,
                    source=source,
                    permission_level=permission_level,
                    idempotency_key=idempotency_key,
                    duplicate_of_execution_id=existing.execution_id,
                    duplicate_state=existing.state.value,
                    duplicate_status=existing.status,
                    blocked_reason="duplicate write tool call rejected by idempotency policy",
                )
            return self._state_result(
                state,
                [ToolExecutionState.PROPOSED, state],
                executed=False,
                tool_name=tool_name,
                arguments=arguments,
                source=source,
                permission_level=permission_level,
                idempotency_key=idempotency_key,
                duplicate_of_execution_id=existing.execution_id,
                duplicate_state=existing.state.value,
                duplicate_status=existing.status,
                result=existing.result,
                error=existing.error,
            )

        record = self.store.create_running(
            idempotency_key=idempotency_key,
            tool_name=tool_name,
            arguments=arguments,
            source=source,
        )
        raw = raw_executor()
        return self._finalize_raw_result(
            raw,
            tool_name=tool_name,
            arguments=arguments,
            source=source,
            permission_level=permission_level,
            transition=[ToolExecutionState.PROPOSED, ToolExecutionState.RUNNING],
            idempotency_key=idempotency_key,
            execution_id=record.execution_id,
        )

    def _finalize_raw_result(
        self,
        raw: str | None,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        source: str,
        transition: list[ToolExecutionState],
        permission_level: str | None = None,
        idempotency_key: str | None = None,
        execution_id: str | None = None,
    ) -> str:
        if raw is None:
            error = f"tool '{tool_name}' returned no result"
            if idempotency_key is not None:
                self.store.fail(idempotency_key, error)
            return self._state_result(
                ToolExecutionState.FAILED,
                [*transition, ToolExecutionState.FAILED],
                executed=True,
                tool_name=tool_name,
                arguments=arguments,
                source=source,
                permission_level=permission_level,
                idempotency_key=idempotency_key,
                execution_id=execution_id,
                error=error,
            )
        if isinstance(raw, str) and raw.startswith("Error"):
            if idempotency_key is not None:
                self.store.fail(idempotency_key, raw)
            return self._state_result(
                ToolExecutionState.FAILED,
                [*transition, ToolExecutionState.FAILED],
                executed=True,
                tool_name=tool_name,
                arguments=arguments,
                source=source,
                permission_level=permission_level,
                idempotency_key=idempotency_key,
                execution_id=execution_id,
                error=raw,
            )
        precondition = self._business_precondition(raw)
        if precondition:
            if idempotency_key is not None:
                self.store.fail(
                    idempotency_key,
                    raw,
                    state=ToolExecutionState.PRECONDITION_REQUIRED,
                )
            return self._state_result(
                ToolExecutionState.PRECONDITION_REQUIRED,
                [*transition, ToolExecutionState.PRECONDITION_REQUIRED],
                executed=False,
                tool_name=tool_name,
                arguments=arguments,
                source=source,
                permission_level=permission_level,
                idempotency_key=idempotency_key,
                execution_id=execution_id,
                precondition=precondition,
                error=raw,
            )

        if idempotency_key is not None:
            self.store.complete(idempotency_key, raw)
        return self._state_result(
            ToolExecutionState.COMPLETED,
            [*transition, ToolExecutionState.COMPLETED],
            executed=True,
            tool_name=tool_name,
            arguments=arguments,
            source=source,
            permission_level=permission_level,
            idempotency_key=idempotency_key,
            execution_id=execution_id,
            result=raw,
        )

    @staticmethod
    def _business_precondition(raw: str) -> str | None:
        if not isinstance(raw, str):
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        status = parsed.get("status")
        if status in {
            "identity_verification_required",
            "summary_content_required",
            "summary_generation_required",
        }:
            return str(status)
        return None

    @staticmethod
    def _state_result(
        state: ToolExecutionState,
        transition: list[ToolExecutionState],
        **payload: Any,
    ) -> str:
        payload["state"] = state.value
        payload["status"] = state.status
        payload["transition"] = [item.value for item in transition]
        return ToolExecutionHarness._json_result(**payload)

    @staticmethod
    def _json_result(**payload: Any) -> str:
        # Permission policy is an internal Harness concern. Tool results may be
        # injected back into model context, so do not expose policy labels.
        payload.pop("permission_level", None)
        return json.dumps(payload, ensure_ascii=False)

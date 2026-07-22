"""Thread-safe cache for HeartBeat thinking entries and tool-call results.

The HeartbeatInteractionHandler writes HeartBeat thinking entries and tool states
into this cache. The LLM handler reads (consumes) them at the start of each
``process()`` call, injecting temporary HeartBeat context before calling the
LLM API.

Lifecycle per user turn:
    1. HeartBeat worker emits HeartBeat entries with optional ``tools``.
       The handler stores one entry whenever the legacy predict path would
       have written to cache.
    2. LLM handler's ``process()`` fires -> ``consume_all()`` returns all entries
       -> LLM injects thinking notes and tool states as temporary context
       -> cache is cleared
    3. HeartBeat worker checks ``is_consumed()`` and stops further predictions
       for the current turn
"""

import bisect
import copy
import logging
import threading
import time
from dataclasses import dataclass, field

from distillation_replay.tool_latency import stable_virtual_tool_latency_ms

logger = logging.getLogger(__name__)

# Default number of HeartBeat-side HeartBeat entries kept per turn (configurable).
DEFAULT_MAX_ENTRIES = 99


@dataclass
class ToolResultItem:
    """A single tool-call state within a HeartBeat thinking entry."""

    tool_name: str
    tool_call_id: str
    arguments: dict
    result: str
    status: str = "completed"
    dispatched_at_ms: int | None = None
    completed_at_ms: int | None = None
    simulated_latency_ms: int | None = None


@dataclass
class HeartBeatEntry:
    """One HeartBeat thinking entry from a single predict-model invocation.

    May contain async thinking text, 0-N tool results, or both.  The LLM
    handler consumes all entries for the current user turn and injects
    them in order.

    Attributes:
        action: Canonical HeartBeat action.
        items:  Tool-call states in this predict invocation.
        order_key:  ASR block_idx for ordered insertion.
        thinking:  Assistant-facing notes produced by HeartBeat Thinking.
        need_to_think: Legacy compatibility flag. Prefer ``action``.
        trigger_ts_ms:  Epoch timestamp in milliseconds when the predict
            invocation was triggered.
        created_at_ms: Milliseconds since current turn start.
        elapsed_ms: Legacy alias for ``created_at_ms``.
        metadata: Runtime metadata attached to this entry. Used for FD-only
            interrupt context such as the assistant sentence being played.
    """

    action: str | None = None
    items: list[ToolResultItem] = field(default_factory=list)
    order_key: int | None = None
    thinking: str = ""
    need_to_think: bool | None = None
    trigger_ts_ms: int | None = None
    created_at_ms: int | None = None
    elapsed_ms: int | None = None
    metadata: dict = field(default_factory=dict)
    llm_completed_at_ms: int | None = None

    def __post_init__(self) -> None:
        if self.created_at_ms is None:
            self.created_at_ms = self.elapsed_ms
        if self.elapsed_ms is None:
            self.elapsed_ms = self.created_at_ms
        if self.action not in {"noop", "think"}:
            self.action = "noop" if self.need_to_think is False else "think"
        if self.need_to_think is None:
            self.need_to_think = self.action == "think"


class HeartBeatCache:
    """Thread-safe store for HeartBeat thinking entries.

    Stores up to ``max_entries`` (default 99) entries per user turn. Each
    entry represents one predict-model call and may contain thinking text,
    0-N tool results, or both. When the LLM handler calls ``consume_all()``,
    all entries are returned in order and the cache is marked as consumed.
    """

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES):
        self._lock = threading.Lock()
        self._updated = threading.Condition(self._lock)
        self._entries: list[HeartBeatEntry] = []
        self._max_entries = max_entries
        self._consumed = threading.Event()
        self._response_snapshot_at_ms: int | None = None

    @staticmethod
    def stable_tool_latency_ms(
        *,
        tool_name: str,
        arguments: dict,
        min_ms: int,
        max_ms: int,
        salt: str = "",
    ) -> int:
        """Return deterministic replay virtual latency for a tool call.

        ``min_ms`` and ``max_ms`` are retained for compatibility with older
        runner arguments.  Current replay uses a tool-name tier policy instead:
        instant 1-10ms, fast 20-100ms, normal 200-800ms, slow 1000-3000ms.
        """
        return stable_virtual_tool_latency_ms(
            tool_name=tool_name,
            arguments=arguments,
            salt=salt,
        )

    @staticmethod
    def _visible_entries_at(
        entries: list[HeartBeatEntry],
        snapshot_at_ms: int | None,
    ) -> list[HeartBeatEntry]:
        """Deep-copy entries, applying replay virtual-time visibility.

        ``snapshot_at_ms`` is in the HeartBeat virtual timeline.  LLM
        completion controls whether an entry exists at all.  Tool mock
        completion controls whether that visible entry shows pending or
        completed tool state.  This deliberately decouples tool mock wall-clock
        latency from replay-visible tool latency.
        """
        copied = copy.deepcopy(entries)
        if snapshot_at_ms is None:
            return copied

        visible: list[HeartBeatEntry] = []
        for entry in copied:
            llm_completed = entry.llm_completed_at_ms
            if isinstance(llm_completed, int) and llm_completed > snapshot_at_ms:
                continue
            if (
                llm_completed is None
                and isinstance(entry.created_at_ms, int)
                and entry.created_at_ms > snapshot_at_ms
            ):
                continue

            filtered_items: list[ToolResultItem] = []
            for item in entry.items:
                if (
                    isinstance(item.dispatched_at_ms, int)
                    and item.dispatched_at_ms > snapshot_at_ms
                ):
                    continue
                completed_at = item.completed_at_ms
                if (
                    item.status == "completed"
                    and isinstance(completed_at, int)
                    and completed_at > snapshot_at_ms
                ):
                    item.status = "pending"
                    item.result = ""
                filtered_items.append(item)
            entry.items = filtered_items
            visible.append(entry)
        return visible

    def store(self, entry: HeartBeatEntry) -> None:
        """Append or ordered-insert a HeartBeat entry.

        When ``entry.order_key`` is not None, the entry is inserted at
        the position that keeps ``_entries`` sorted by ``order_key``
        ascending.  This lets concurrent predict tasks store results
        in whatever order they complete while the cache still exposes
        a submission-ordered view to the LLM consumer (the tail is
        always the freshest block).  ``None`` keeps the legacy append
        semantics for callers that don't care about order.
        """
        with self._lock:
            if self._consumed.is_set():
                logger.debug("HeartBeatCache: ignoring store after consume")
                return
            if entry.order_key is None:
                self._entries.append(entry)
            else:
                # Ordered insertion by order_key; entries with order_key=None
                # (if any) are treated as +inf (kept at tail).
                keys = [
                    e.order_key if e.order_key is not None else float("inf")
                    for e in self._entries
                ]
                pos = bisect.bisect_right(keys, entry.order_key)
                self._entries.insert(pos, entry)
            if len(self._entries) > self._max_entries:
                # Drop oldest (lowest order_key sits at head).
                dropped = self._entries.pop(0)
                logger.warning(
                    "HeartBeatCache: max entries (%d) reached, dropped oldest "
                    "entry order_key=%s",
                    self._max_entries, dropped.order_key,
                )
            tool_names = [f"{it.tool_name}:{it.status}" for it in entry.items]
            thinking_preview = entry.thinking.replace("\n", " ")[:120] if entry.thinking else ""
            logger.info(
                "HeartBeatCache: stored entry #%d — action=%s, tools=%s, thinking=%s, order_key=%s, trigger_ts_ms=%s, created_at_ms=%s",
                len(self._entries), entry.action, tool_names,
                thinking_preview, entry.order_key, entry.trigger_ts_ms,
                entry.created_at_ms,
            )
            self._updated.notify_all()

    def snapshot_for_thinker(self, snapshot_at_ms: int | None = None) -> list[HeartBeatEntry]:
        """Return a deep-copy snapshot without consuming the cache.

        This is used by later HeartBeat Thinking invocations within the same user
        turn.  It must not clear entries or set the consumed flag; the main
        LLM still consumes all entries after end-of-speech.
        """
        with self._lock:
            return self._visible_entries_at(self._entries, snapshot_at_ms)

    def update_tool_result(
        self,
        tool_call_id: str,
        result: str,
        status: str = "completed",
    ) -> bool:
        """Update a pending tool item after asynchronous execution finishes."""
        with self._lock:
            for entry in self._entries:
                for item in entry.items:
                    if item.tool_call_id == tool_call_id:
                        item.result = result
                        item.status = status
                        logger.info(
                            "HeartBeatCache: updated tool result call_id=%s status=%s result=%s",
                            tool_call_id, status, result if result else "",
                        )
                        self._updated.notify_all()
                        return True
            logger.debug(
                "HeartBeatCache: tool result update skipped; call_id=%s not found",
                tool_call_id,
            )
            return False

    def pending_tool_count(self) -> int:
        """Return the number of pending tool items currently in the cache."""
        with self._lock:
            return sum(
                1
                for entry in self._entries
                for item in entry.items
                if item.status == "pending"
            )

    def wait_for_pending_results(self, timeout_s: float) -> int:
        """Wait until pending tool items are updated or timeout expires.

        This is used by replay response input capture.  Replay visibility is
        defined by the virtual Heartbeat timeline, but the dynamic tool mock
        still returns on wall-clock time.  Waiting here lets the runtime
        ``response.input_messages`` snapshot consume the same completed tool
        states that the virtual trace later deems visible.

        Returns the remaining pending count.
        """
        deadline = time.monotonic() + max(0.0, float(timeout_s))
        with self._updated:
            while True:
                pending = sum(
                    1
                    for entry in self._entries
                    for item in entry.items
                    if item.status == "pending"
                )
                if pending <= 0:
                    return 0
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return pending
                self._updated.wait(timeout=remaining)

    def set_response_snapshot_at_ms(self, snapshot_at_ms: int | None) -> None:
        """Store the replay virtual response snapshot time for this turn."""
        with self._lock:
            self._response_snapshot_at_ms = snapshot_at_ms

    def response_snapshot_at_ms(self) -> int | None:
        """Return the replay virtual response snapshot time, if known."""
        with self._lock:
            return self._response_snapshot_at_ms

    def consume_all(self, snapshot_at_ms: int | None = None) -> list[HeartBeatEntry]:
        """Consume all cached entries (called by LLM handler).

        Returns the list of entries and clears the cache.  Sets the
        consumed flag so the predict handler stops predicting and
        discards any in-flight results (via ``store()`` rejecting and
        ``is_consumed()`` breaking the block loop).

        If the cache is empty, returns an empty list — no HeartBeat-side HeartBeat
        context is injected.  The consumed flag is still set so any
        in-flight predict operations are discarded.
        """
        with self._lock:
            entries = self._visible_entries_at(self._entries, snapshot_at_ms)
            self._entries.clear()
            self._consumed.set()
            if entries:
                all_tools = [
                    it.tool_name for e in entries for it in e.items
                ]
                thinking_count = sum(1 for e in entries if e.thinking)
                logger.info(
                    "HeartBeatCache: consumed %d entries — thinking=%d, tools=%s",
                    len(entries),
                    thinking_count,
                    all_tools,
                )
            return entries

    def is_consumed(self) -> bool:
        """One-shot consumed check (predict handler polls this).

        Returns True if the cache was consumed by the LLM handler,
        then auto-resets the flag.  This ensures the predict handler
        stops immediately on the first detection, and the flag is
        automatically ready for the next turn without requiring
        TURN_END to clear it.

        The flag stays set between ``consume_all()`` and the first
        ``is_consumed()`` call, so ``store()`` also sees it and
        rejects in-flight results during that window.
        """
        with self._lock:
            if self._consumed.is_set():
                self._consumed.clear()
                return True
            return False

    def reset(self) -> None:
        """Full reset for session boundary."""
        with self._lock:
            self._entries.clear()
            self._consumed.clear()
            self._response_snapshot_at_ms = None
            logger.debug("HeartBeatCache: reset for new turn")

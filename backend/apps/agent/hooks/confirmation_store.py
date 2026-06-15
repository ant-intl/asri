"""
ConfirmationStore — singleton for async tool-execution confirmations.

In-memory asyncio.Event based store for same-Pod confirmation flow.
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ConfirmationEntry:
    """A single pending confirmation."""

    tool_name: str
    arguments: str
    event: asyncio.Event = field(default_factory=asyncio.Event)
    approved: bool | None = None
    created_at: float = field(default_factory=time.time)


class ConfirmationStore:
    """Async-safe in-memory confirmation store.

    Used by ToolConfirmationHook to wait for client approval
    and by WebSocket/HTTP handlers to signal the result.

    ``create()`` → in-memory dict → ``respond()`` sets Event → ``wait()`` returns.
    """

    _instance: "ConfirmationStore | None" = None

    def __init__(self) -> None:
        self._confirmations: dict[str, ConfirmationEntry] = {}
        self._lock = asyncio.Lock()

    # ── singleton ─────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> "ConfirmationStore":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── API ───────────────────────────────────────────────────────

    async def create(self, tool_name: str, arguments: str) -> str:
        """Create a confirmation entry and return its ID."""
        confirmation_id = f"confirm_{uuid.uuid4().hex[:12]}"
        entry = ConfirmationEntry(tool_name=tool_name, arguments=arguments)
        async with self._lock:
            self._confirmations[confirmation_id] = entry
        logger.debug(
            "Created confirmation %s for tool '%s'", confirmation_id, tool_name
        )
        return confirmation_id

    async def wait(self, confirmation_id: str, timeout: float = 30.0) -> bool:
        """Wait for a response. Returns False on timeout (auto-reject).

        Uses in-memory ``asyncio.Event`` — instant wake on same Pod.
        """
        entry = await self._get_entry(confirmation_id)
        if entry is None:
            logger.warning("Confirmation %s not found — auto-rejecting", confirmation_id)
            return False

        return await self._wait_local(entry, timeout)

    async def respond(self, confirmation_id: str, approved: bool) -> bool:
        """Signal a client response. Only the first response is accepted.

        Writes to in-memory Event — same-Pod fast path.

        Returns True if the response was processed, False if already resolved or not found.
        """
        entry = await self._get_entry(confirmation_id)
        if entry is not None and entry.approved is None:
            entry.approved = approved
            entry.event.set()
            logger.info(
                "Confirmation %s: %s (tool=%s)",
                confirmation_id,
                "approved" if approved else "rejected",
                entry.tool_name,
            )
            return True

        logger.warning("Confirmation %s not found for respond", confirmation_id)
        return False

    async def cancel(self, confirmation_id: str) -> bool:
        """Remove a pending confirmation (e.g. on session close).

        Removes from in-memory dict.
        """
        async with self._lock:
            entry = self._confirmations.pop(confirmation_id, None)
        if entry:
            entry.event.set()
            logger.debug("Cancelled confirmation %s", confirmation_id)
        return entry is not None

    async def cleanup_expired(self, max_age_seconds: float = 120.0) -> int:
        """Remove entries older than ``max_age_seconds``. Returns count removed."""
        now = time.time()
        async with self._lock:
            stale = [
                cid for cid, entry in self._confirmations.items()
                if now - entry.created_at > max_age_seconds
            ]
            for cid in stale:
                self._confirmations[cid].event.set()
                del self._confirmations[cid]
        if stale:
            logger.debug("Cleaned up %d expired confirmations", len(stale))
        return len(stale)

    async def get_pending_count(self) -> int:
        """Return the number of currently pending confirmations."""
        async with self._lock:
            return len(self._confirmations)

    # ── helpers ───────────────────────────────────────────────────

    async def _get_entry(self, confirmation_id: str) -> ConfirmationEntry | None:
        async with self._lock:
            return self._confirmations.get(confirmation_id)

    @staticmethod
    async def _wait_local(entry: ConfirmationEntry, timeout: float) -> bool:
        """Wait using in-memory asyncio.Event."""
        try:
            await asyncio.wait_for(entry.event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.info(
                "Confirmation timed out after %.1fs — auto-rejecting",
                timeout,
            )
            return False

        approved = entry.approved if entry.approved is not None else False
        logger.debug("Confirmation resolved (local): approved=%s", approved)
        return approved


def get_confirmation_store() -> ConfirmationStore:
    """Get the global ConfirmationStore singleton."""
    return ConfirmationStore.get_instance()

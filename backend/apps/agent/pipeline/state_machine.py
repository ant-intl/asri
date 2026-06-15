"""
State machine for full-duplex LLM processor.

Manages the state transitions during multi-round tool calling.
"""
import logging
from enum import Enum, auto
from typing import Optional, Set

logger = logging.getLogger(__name__)


class State(Enum):
    """States for the LLM processor state machine."""
    IDLE = "idle"                           # Idle state
    LLM_CALLING = "llm_calling"             # LLM call in progress
    WAITING_FOR_TOOLS = "waiting_for_tools" # Waiting for tool results
    TOOL_EXECUTING = "tool_executing"       # Tool execution in progress
    COMPLETED = "completed"                 # Completed successfully
    ERROR = "error"                         # Error state


class InvalidStateTransition(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


class LLMStateMachine:
    """State machine for managing LLM processor state.

    Tracks the current state and pending tool calls during multi-round
    conversations with tool calling.
    """

    # Valid state transitions
    # LLM_CALLING -> TOOL_EXECUTING is allowed for streaming tool detection
    _VALID_TRANSITIONS: dict[State, set[State]] = {
        State.IDLE: {State.LLM_CALLING},
        State.LLM_CALLING: {State.WAITING_FOR_TOOLS, State.TOOL_EXECUTING, State.COMPLETED, State.ERROR},
        State.WAITING_FOR_TOOLS: {State.TOOL_EXECUTING, State.LLM_CALLING, State.COMPLETED, State.ERROR},
        State.TOOL_EXECUTING: {State.WAITING_FOR_TOOLS, State.LLM_CALLING, State.COMPLETED, State.ERROR},
        State.ERROR: {State.IDLE},
        State.COMPLETED: {State.IDLE},
    }

    def __init__(self, initial_state: State = State.IDLE):
        """Initialize the state machine.

        Args:
            initial_state: The initial state. Defaults to IDLE.
        """
        self._state = initial_state
        self._pending_tools: Set[str] = set()
        self._completed_tools: Set[str] = set()
        self._error_count: int = 0
        self._max_errors: int = 3  # Max consecutive errors before giving up

    @property
    def current_state(self) -> State:
        """Get the current state.

        Returns:
            The current state.
        """
        return self._state

    @property
    def is_idle(self) -> bool:
        """Check if in idle state.

        Returns:
            True if idle, False otherwise.
        """
        return self._state == State.IDLE

    @property
    def is_calling(self) -> bool:
        """Check if LLM is being called.

        Returns:
            True if calling LLM, False otherwise.
        """
        return self._state == State.LLM_CALLING

    @property
    def is_waiting_for_tools(self) -> bool:
        """Check if waiting for tool results.

        Returns:
            True if waiting, False otherwise.
        """
        return self._state == State.WAITING_FOR_TOOLS

    @property
    def is_executing_tools(self) -> bool:
        """Check if tools are executing.

        Returns:
            True if executing, False otherwise.
        """
        return self._state == State.TOOL_EXECUTING

    @property
    def is_completed(self) -> bool:
        """Check if completed.

        Returns:
            True if completed, False otherwise.
        """
        return self._state == State.COMPLETED

    @property
    def is_error(self) -> bool:
        """Check if in error state.

        Returns:
            True if error, False otherwise.
        """
        return self._state == State.ERROR

    @property
    def pending_tool_count(self) -> int:
        """Get the number of pending tools.

        Returns:
            Number of pending tools.
        """
        return len(self._pending_tools)

    @property
    def has_pending_tools(self) -> bool:
        """Check if there are pending tools.

        Returns:
            True if pending tools exist, False otherwise.
        """
        return len(self._pending_tools) > 0

    def transition_to(self, new_state: State, reason: Optional[str] = None) -> None:
        """Transition to a new state.

        Args:
            new_state: The state to transition to.
            reason: Optional reason for the transition.

        Raises:
            InvalidStateTransition: If the transition is not valid.
        """
        if not self._can_transition(self._state, new_state):
            raise InvalidStateTransition(
                f"Cannot transition from {self._state.value} to {new_state.value}"
            )

        old_state = self._state
        self._state = new_state

        log_msg = f"State transition: {old_state.value} -> {new_state.value}"
        if reason:
            log_msg += f" ({reason})"
        logger.debug(log_msg)

        # Reset error count on successful transition
        if new_state not in (State.ERROR,):
            self._error_count = 0

    def _can_transition(self, from_state: State, to_state: State) -> bool:
        """Check if a state transition is valid.

        Args:
            from_state: The current state.
            to_state: The target state.

        Returns:
            True if the transition is valid, False otherwise.
        """
        valid_states = self._VALID_TRANSITIONS.get(from_state, set())
        return to_state in valid_states

    def add_pending_tool(self, tool_call_id: str) -> None:
        """Add a tool to pending set.

        Args:
            tool_call_id: The ID of the tool call.
        """
        self._pending_tools.add(tool_call_id)
        logger.debug(f"Added pending tool: {tool_call_id}, total: {len(self._pending_tools)}")

    def complete_tool(self, tool_call_id: str) -> bool:
        """Mark a tool as completed.

        Args:
            tool_call_id: The ID of the tool call.

        Returns:
            True if all pending tools are now completed, False otherwise.
        """
        self._pending_tools.discard(tool_call_id)
        self._completed_tools.add(tool_call_id)

        logger.debug(
            f"Completed tool: {tool_call_id}, "
            f"remaining: {len(self._pending_tools)}"
        )

        return len(self._pending_tools) == 0

    def fail_tool(self, tool_call_id: str, error: str) -> bool:
        """Mark a tool as failed.

        Args:
            tool_call_id: The ID of the tool call.
            error: The error message.

        Returns:
            True if all pending tools are now completed, False otherwise.
        """
        self._pending_tools.discard(tool_call_id)
        self._error_count += 1

        logger.warning(f"Tool failed: {tool_call_id}, error: {error}")

        return len(self._pending_tools) == 0

    def cancel_tool(self, tool_call_id: str) -> bool:
        """Mark a tool as cancelled.

        Args:
            tool_call_id: The ID of the tool call.

        Returns:
            True if all pending tools are now completed, False otherwise.
        """
        self._pending_tools.discard(tool_call_id)

        logger.debug(f"Cancelled tool: {tool_call_id}")

        return len(self._pending_tools) == 0

    def reset(self) -> None:
        """Reset the state machine to initial state."""
        self._state = State.IDLE
        self._pending_tools.clear()
        self._completed_tools.clear()
        self._error_count = 0
        logger.debug("State machine reset to IDLE")

    def should_retry(self) -> bool:
        """Check if we should retry after an error.

        Returns:
            True if error count is below threshold, False otherwise.
        """
        return self._error_count < self._max_errors

    def get_state_info(self) -> dict:
        """Get current state information.

        Returns:
            Dict with current state and pending tools info.
        """
        return {
            "state": self._state.value,
            "pending_tools": list(self._pending_tools),
            "completed_tools": list(self._completed_tools),
            "pending_count": len(self._pending_tools),
            "error_count": self._error_count,
        }

    def __repr__(self) -> str:
        """String representation of the state machine."""
        return (
            f"LLMStateMachine(state={self._state.value}, "
            f"pending={len(self._pending_tools)}, "
            f"completed={len(self._completed_tools)})"
        )

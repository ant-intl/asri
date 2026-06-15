"""
Agent context for runtime state management.
"""
import uuid
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple, TYPE_CHECKING
import time

if TYPE_CHECKING:
    from ..hooks.base import HookManager


# Trace event types for unified format
TRACE_TYPE_THINKING = "thinking"
TRACE_TYPE_TOOL_CALL = "tool_call"
TRACE_TYPE_TOOL_RESULT = "tool_result"
TRACE_TYPE_ANSWER = "answer"
TRACE_TYPE_LLM_START = "llm_start"
TRACE_TYPE_LLM_END = "llm_end"

# Tool call status
TOOL_STATUS_CALLING = "calling"
TOOL_STATUS_SUCCESS = "success"
TOOL_STATUS_ERROR = "error"


@dataclass
class AgentContext:
    """
    Runtime context for agent execution.
    
    Contains all state needed during a single agent run,
    including conversation history, available tools, and execution trace.
    """
    
    # Session information
    session_id: str = ''
    user_id: str = ''
    tenant_id: Optional[str] = None  # Tenant ID for tool/skill isolation
    
    # Conversation state
    messages: List[Dict[str, str]] = field(default_factory=list)
    current_query: str = ''
    
    # Available capabilities
    available_tools: List[str] = field(default_factory=list)
    available_skills: List[str] = field(default_factory=list)
    rag_enabled: bool = False
    
    # Execution state
    iteration_count: int = 0
    max_iterations: int = 10
    
    # Execution trace (for debugging/logging)
    trace: List[Dict[str, Any]] = field(default_factory=list)
    
    # Token tracking
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # User context (for storing hidden parameters such as cookies)
    # Structure: {"_global": {"cookie": "xxx"}, "tool_name": {"token": "yyy"}}
    user_context: Dict[str, Any] = field(default_factory=dict)

    # Hook system
    hook_manager: Any = None  # HookManager instance, optional
    
    def add_trace(
        self,
        step_type: str,
        content: str = None,
        metadata: Dict[str, Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Add an entry to the execution trace.

        Supports both legacy format (backward compatibility) and new unified format.

        New unified format fields (via kwargs):
            - status: Tool call status (calling/success/error)
            - tool_name: Tool/skill name
            - parameters: Tool parameters dict
            - result: Tool result dict
            - tool_call_id: Unique ID to associate call and result

        Returns:
            The created trace entry dict
        """
        trace_entry = {
            'type': step_type,
            'timestamp': int(time.time() * 1000),  # Milliseconds
        }

        # Add content if provided
        if content is not None:
            trace_entry['content'] = content

        # Add legacy iteration for backward compatibility
        trace_entry['iteration'] = self.iteration_count

        # Add metadata
        trace_entry['metadata'] = metadata or {}

        # Add new format fields from kwargs
        for key in ['status', 'tool_name', 'parameters', 'result', 'tool_call_id']:
            if key in kwargs and kwargs[key] is not None:
                trace_entry[key] = kwargs[key]

        self.trace.append(trace_entry)
        return trace_entry
    
    def increment_iteration(self) -> bool:
        """
        Increment iteration count and check limit.
        
        Returns:
            True if can continue, False if limit reached
        """
        self.iteration_count += 1
        return self.iteration_count < self.max_iterations
    
    def get_total_tokens(self) -> int:
        """Get total token count."""
        return self.prompt_tokens + self.completion_tokens

    def add_llm_start(self, model: str, provider: str) -> Tuple[str, Dict[str, Any]]:
        """
        Add LLM call start trace entry.

        Args:
            model: LLM model name
            provider: LLM provider type

        Returns:
            Tuple of (llm_id, trace_entry)
        """
        llm_id = f"llm_{uuid.uuid4().hex[:8]}"

        trace_entry = {
            'type': TRACE_TYPE_LLM_START,
            'timestamp': int(time.time() * 1000),
            'llm_id': llm_id,
            'model': model,
            'provider': provider,
            'iteration': self.iteration_count,
        }
        self.trace.append(trace_entry)
        return llm_id, trace_entry

    def add_llm_end(
        self,
        llm_id: str,
        duration_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        finish_reason: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Add LLM call end trace entry.

        Args:
            llm_id: LLM ID from corresponding llm_start entry
            duration_ms: LLM call duration in milliseconds
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            finish_reason: Reason for completion (e.g., 'stop', 'length')
            **kwargs: Additional optional fields

        Returns:
            The created trace entry dict
        """
        trace_entry = {
            'type': TRACE_TYPE_LLM_END,
            'timestamp': int(time.time() * 1000),
            'llm_id': llm_id,
            'duration_ms': duration_ms,
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': prompt_tokens + completion_tokens,
            'iteration': self.iteration_count,
        }
        if finish_reason:
            trace_entry['finish_reason'] = finish_reason

        for key, value in kwargs.items():
            if value is not None:
                trace_entry[key] = value

        self.trace.append(trace_entry)
        return trace_entry

    def push_card(self, card_data: dict) -> None:
        """Queue a card for frontend rendering.

        Cards are collected during tool execution and flushed to the
        pipeline after the tool result is processed.

        Args:
            card_data: Dict with card_type and custom fields.
        """
        if '_pending_cards' not in self.metadata:
            self.metadata['_pending_cards'] = []
        self.metadata['_pending_cards'].append(card_data)

    def pop_pending_cards(self) -> list[dict]:
        """Pop and return all pending cards.

        Returns:
            List of card data dicts.
        """
        return self.metadata.pop('_pending_cards', [])

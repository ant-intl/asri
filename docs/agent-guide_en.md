# Agent System

ASRI uses a unified **ChatAgent** built on the Pipeline Frame framework, driven by LLM native function_calling. Agent behavior is differentiated through **Prompt modes** (loaded from the database), eliminating the need for multiple Agent implementations.

**File**: `apps/agent/agent/chat_agent.py`

---

## BaseAgent Abstract Base Class

**File**: `apps/agent/agent/base.py`

All Agents must inherit from `BaseAgent` and implement two core methods:

```python
class BaseAgent(ABC):
    def __init__(self, **kwargs):
        self.config = kwargs

    @abstractmethod
    async def run(
        self, query: str,
        history: List[Dict[str, str]] = None,
        context: AgentContext = None,
    ) -> Dict[str, Any]:
        """Non-streaming execution, returns the complete result."""

    @abstractmethod
    async def stream(
        self, query: str,
        history: List[Dict[str, str]] = None,
        context: AgentContext = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Streaming execution, yields results chunk by chunk."""
```

### Return Format

`run()` returns:

```python
{
    "answer": str,           # Final answer
    "trace": list[dict],     # Execution trace
    "prompt_tokens": int,
    "completion_tokens": int,
    "total_tokens": int,
    "model": str,            # Model name used
    "context_messages": list[dict],  # Full context (for subsequent turns)
}
```

`stream()` yields chunks in the following format:

```python
{"type": "answer",     "content": "partial text"}
{"type": "thought",    "content": "thinking process"}
{"type": "tool_call",  "content": "tool call info"}
{"type": "tool_result","content": "tool execution result"}
{"type": "card",       "card_data": {...}}
{"type": "done",       "content": ""}
{"type": "error",      "content": "error description"}
```

---

## AgentContext Runtime Context

**File**: `apps/agent/agent/context.py`

Each Agent execution creates an `AgentContext` instance carrying the complete runtime state:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `session_id` | `str` | `''` | Session ID |
| `user_id` | `str` | `''` | User ID |
| `tenant_id` | `str` | `None` | Tenant ID |
| `messages` | `list[dict]` | `[]` | Conversation history |
| `current_query` | `str` | `''` | Current user query |
| `available_tools` | `list[str]` | `[]` | Available tool names |
| `available_skills` | `list[str]` | `[]` | Available skill names |
| `iteration_count` | `int` | `0` | Current iteration count |
| `max_iterations` | `int` | `10` | Maximum iterations |
| `trace` | `list[dict]` | `[]` | Execution trace entries |
| `prompt_tokens` | `int` | `0` | Prompt token count |
| `completion_tokens` | `int` | `0` | Completion token count |
| `metadata` | `dict` | `{}` | Custom metadata |
| `hook_manager` | `HookManager` | `None` | Hook manager |

### Core Methods

```python
# Add trace entry
context.add_trace(step_type='thought', content='User is asking about refund...', metadata={})

# Increment iteration and check limit
can_continue = context.increment_iteration()  # True / False

# Get total tokens
total = context.get_total_tokens()
```

---

## ChatAgent

**File**: `apps/agent/agent/chat_agent.py`

A unified Agent implementation based on the Pipeline Frame framework, driven by LLM native **function_calling**.

### Initialization Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `llm_provider` | `BaseLLMProvider` | — | LLM provider instance |
| `prompt_mode` | `str` | `'interleaved_thinking'` | Prompt mode, determines which DB PromptTemplate to load |
| `tenant_id` | `str` | `None` | Tenant ID |
| `max_iterations` | `int` | `10` | Maximum tool_call rounds |
| `interrupt_strategy` | `str` | `'none'` | Tool interrupt strategy |

### Prompt Modes

Prompt modes are specified via `REACT_PROMPT_MODE` config (or tenant-level config). Each mode corresponds to a record in the database `PromptTemplate` table:

| Mode | Description | Parsing Strategy |
|------|-------------|-----------------|
| `interleaved_thinking` | Streaming interleaved thinking, default mode | Parses `<think>`, `<tool_call>`, `<answer>` XML tags |
| `react` | Standard ReAct text parsing | Parses Thought/Action/Action Input text format |
| `skill_decision` | JSON decision engine | Injects skill list, parses JSON decisions |
| `pipeline` | Native function_calling format | LLM native tool_calls driven |

Prompt loading flow (lazy loading):
1. Agent initialization does not load the Prompt (only saves `prompt_mode`)
2. First execution calls `_ensure_prompt_initialized()` → `create_prompt_async(prompt_mode)`
3. Factory function queries `PromptTemplate.objects.filter(name=prompt_mode, is_active=True, tenant_id=current_tenant)`
4. Returns a `DynamicPrompt` instance, template data loaded from the database

### Execution Flow

1. `_build_pipeline(context)` creates the processor chain:
   - `FullDuplexLLMProcessor` → `OutputCollectorProcessor`
   - Both enable `enable_direct_mode=True` (synchronous frame processing)
   - `FullDuplexLLMProcessor` registers `AsyncExecutorProcessor` for asynchronous tool execution
   - Uses `build_tool_schemas(context)` to construct tool definitions
   - Uses `build_function_handlers(executor, context)` to construct handlers

2. `_build_messages(query, history)` builds the message list:
   - System Prompt is generated via `DynamicPrompt.build_messages()`
   - Supports Jinja2 template rendering, injecting skill lists and tool schemas
   - Supports multi-layer Prompt strategy (`layers` field): `always` / `first_turn`

3. `_drive_pipeline(llm_processor, messages, queue)` drives execution:
   - Sends `StartFrame` for initialization
   - Sends `LLMMessagesAppendFrame` to trigger LLM call
   - LLM streaming detects tool_calls and immediately sends `AsyncFunctionCallFrame`
   - Receives `FunctionCallEndFrame` callback and re-calls LLM (up to `max_iterations` rounds)

4. Collects output chunks from `asyncio.Queue`

### Pipeline Tool Functions

| Tool | Registration Condition | Description |
|------|----------------------|-------------|
| `skill_load` | Always registered | Loads skill details on demand |
| `execute_tool` | `context.available_tools` not empty | Executes registered tools (including RAG tools registered via `ToolRegistry`) |

---

### Three Core Design Capabilities

#### Parallel Streaming Tool Use

The LLM can return multiple tool calls in a single response. `AsyncExecutorProcessor` dispatches them all to `asyncio.gather` in parallel. The next LLM call only starts after all results are collected.

```python
# Simplified flow
pending_calls = [call1, call2, call3]
results = await asyncio.gather(*[execute(c) for c in pending_calls])
# All results fed back to LLM together
```

#### Interleaved Thinking And Answer

`interleaved_thinking` is the default prompt mode. `FullDuplexLLMProcessor` feeds each token to `StreamingTagFilter` in real time, classifying output into `thought` / `tool_call` / `answer` types and streaming each independently — no waiting for a complete response.

#### Adaptive Interrupt

`ChatService` checks for an active stream before starting a new one:

```python
# Auto-interrupt old stream before starting new one
old_event = _streaming_sessions.get(session_id)
if old_event:
    old_event.set()  # Signal interrupt
    await asyncio.wait_for(done_event.wait(), timeout=5.0)  # Wait for cleanup

# Finally-block fallback: save context if not already saved
finally:
    if not context_saved and agent:
        fallback_ctx = await agent.get_context_messages()
        await session_service.save_session_context(session_id, fallback_ctx)
```

---

## Database-Driven Prompt System

All system prompts are stored in the database and managed through the `PromptTemplate` model.

**Model file**: `apps/chatbot/models/prompt_template.py`

**DB table**: `chatbot_prompt`

### PromptTemplate Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `tenant_id` | str | Tenant identifier (supports multi-tenant isolation) |
| `name` | str | Prompt mode name (`react` / `skill_decision` / `interleaved_thinking` / `pipeline`) |
| `system_template` | text | System prompt template (Jinja2 format) |
| `user_template_mode` | str | Message building mode: `generic` (standard `[system, history, user]`) or `custom` |
| `user_template` | text | User message template (custom mode only) |
| `layers` | JSON | Multi-layer Prompt configuration array |
| `extractor_config` | JSON | Output parser configuration |
| `is_active` | bool | Whether active |

### Unique Constraint

`(tenant_id, name)` — Each tenant can have only one active template per mode.

### Multi-layer Prompt (Layers)

The `layers` field is a JSON array, each layer containing:

| Field | Description |
|-------|-------------|
| `name` | Layer name |
| `target` | `system` (injected into System Message) or `user` (injected into User Message) |
| `strategy` | `always` (every turn) or `first_turn` (first turn only) |
| `template` | Jinja2 template |
| `order` | Sort order |
| `is_active` | Whether active |

### Extractor Configuration

Specifies how to parse LLM output into structured Actions:

```json
{
  "extractor": {
    "type": "xml_tags",
    "default_type": "think"
  },
  "mapper": {
    "tool_keys": ["tool_call"],
    "think_keys": ["think"],
    "answer_keys": ["answer"]
  }
}
```

---

## StreamingTagFilter

**File**: `apps/agent/agent/chat_agent.py`

When using the `interleaved_thinking` Prompt mode, ChatAgent automatically enables streaming tag filtering to identify XML tags in real-time:

```
LLM Output: "Let me check...<think>Need to query user info</think><tool_call>query_user</tool_call>"
                             ↓
After filter: {"type": "thought",    "content": "Need to query user info"}
              {"type": "tool_call",  "content": "query_user"}
```

**Tag Mapping Rules**:
- `<think>...</think>` → `{type: 'thought'}` (thinking process)
- `<tool_call>...</tool_call>` → `{type: 'tool_call'}` (tool invocation)
- `<answer>...</answer>` → `{type: 'answer'}` (final answer)
- Untagged text → `{type: 'token'}` (streaming token)

Tag filtering is handled internally by the `FullDuplexLLMProcessor` in the Pipeline, requiring no external preprocessing.

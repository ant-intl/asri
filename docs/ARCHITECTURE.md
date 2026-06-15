# Architecture Overview

This document provides a high-level overview of the ASRI system architecture.

## System Overview

ASRI is an intelligent dialogue robot service built on Django 4.1 with a unified ChatAgent built on Pipeline Frame architecture. It features the **Interleave Engine** — a design that enables three core capabilities: concurrent tool execution, streaming tool use, and adaptive interruption. It also supports database-driven prompt management, multi-LLM integration, WebSocket streaming, and an extensible Skill/Tool/RAG system.

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                            Client Layer                              │
│   React 19 SPA + Ant Design 6 + WebSocket Client                     │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                            API Layer                                 │
│   HTTP Endpoints (Chat/Session/Message/Providers) + WebSocket Handler│
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          Service Layer                               │
│   ChatService / SessionService / WebSocketService                    │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           Core Layer                                 │
│   ChatAgent + Interleave Engine (Pipeline Frame Architecture)         │
│   AgentContext / ActionExecutor                                       │
│   │                                                                   │
│   ├─► Parallel Streaming Tool Use: AsyncExecutorProcessor (parallel tool_calls)  │
│   ├─► Interleaved Thinking And Answer: FullDuplexLLMProcessor + StreamingTagFilter          │
│   └─► Adaptive Interrupt: interrupt_event + finally-block context save        │
└─────────────────────────────────────────────────────────────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────────┐   ┌───────────────┐
│  LLM Layer    │   │  RAG/Skill/Tool   │   │ Memory Layer  │
│  OpenAI       │   │  HTTP RAG         │   │ Conversation  │
│  Ollama       │   │  FAQ RAG          │   │ Summary       │
│  Custom       │   │  Skill Registry   │   │               │
│               │   │  Tool Registry    │   │               │
└───────────────┘   └───────────────────┘   └───────────────┘
          │                    │                    │
          └────────────────────┴────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Persistence Layer                             │
│   Session / Message / Provider Config / Tenant (Django ORM + MySQL) │
└─────────────────────────────────────────────────────────────────────┘
```

## Layered Architecture

### 1. API Layer (`backend/apps/api/`)

Handles HTTP requests and WebSocket connections.

**Components**:
- `http/` - REST API endpoints
  - `chat.py` - Chat endpoints (non-streaming + SSE)
  - `session.py` - Session CRUD operations
  - `message.py` - Message history
  - `llm_config.py`, `rag_config.py`, `tool_config.py`, `skill_config.py` - Provider management
- `websocket/` - WebSocket handlers
  - `chat_consumer.py` - Real-time streaming handler
- `serializers/` - Data serialization

**Responsibilities**:
- Request validation and parsing
- Response formatting
- Authentication (Bearer Token)
- Error handling

### 2. Service Layer (`backend/apps/services/`)

Orchestrates business logic between API and Core layers.

**Components**:
- `chat_service.py` - Chat orchestration
- `session_service.py` - Session management
- `websocket_service.py` - WebSocket message handling

**Responsibilities**:
- Coordinate Core and Integration layers
- Transaction management
- Business rule enforcement
- **Never contains direct database operations**

### 3. Core Layer (`backend/apps/agent/`)

Implements the Agent execution logic.

**Components**:
  - `chat_agent.py` - ChatAgent (Pipeline Frame Architecture)
  - `base.py` - Base agent abstraction
  - `context.py` - Agent runtime context
- `prompts/` - Prompt templates (database-driven)
  - `base.py` - Base system prompt
  - `dynamic_prompt.py` - DB-loaded DynamicPrompt
- `parsers/` - Response parsers
- `hooks/` - Hook system (confirmation, intercept)

**Agent Execution**:

ChatAgent uses a Frame-based Pipeline architecture with LLM native function_calling:
```
User Input → LLM with Tools → Native function_calling
    ↓
Parse Tool Calls → Execute in Parallel → Get Results
    ↓
Feed Results to LLM → Continue Until Final Answer
```

### 4. Integration Layer (`backend/apps/integrations/`)

Provides unified abstractions for external services.

**Components**:
- `llm/` - LLM providers
  - `base.py` - `BaseLLMProvider` (abstract)
  - `openai_provider.py`, `ollama_provider.py`, `custom_provider.py`
  - `registry.py` - LLM Registry
- `rag/` - RAG providers
  - `base.py` - `BaseRAGProvider` (abstract)
  - `faq_rag_provider.py`
- `skill/` - Skill registry
  - `base.py` - `BaseSkill` (abstract)
  - `registry.py` - Skill Registry
- `tool/` - Tool registry
  - `base.py` - `BaseTool` (abstract)
  - `registry.py` - Tool Registry
- `memory/` - Memory management
  - `base.py` - `BaseMemory` (abstract)
  - `conversation.py`, `summary.py`

**Provider Pattern**:
```python
# All providers follow the same pattern:
# 1. Inherit from base class
# 2. Implement abstract methods
# 3. Register in Registry

class CustomLLMProvider(BaseLLMProvider):
    async def chat(self, messages: list, **kwargs) -> dict:
        # Implementation
        pass

    async def stream_chat(self, messages: list, **kwargs):
        async for chunk in self._stream(messages):
            yield chunk

LLMRegistry.register('custom', CustomLLMProvider)
```

### 5. Persistence Layer (`backend/apps/entities/`)

Django models for data storage.

**Key Models**:
- `ChatSession` - User session management
- `Message` - Chat message history with trace data
- `LLMProvider` - LLM configuration
- `RAGProvider` - RAG service config
- `Tool`, `Skill` - Custom integrations
- `Tenant` - Multi-tenant support

**Design Principles**:
- UUID primary keys
- Automatic timestamps (`created_at`, `updated_at`)
- JSON fields for dynamic metadata
- No foreign keys in schema (enforced via code)

---

## Multi-Tenant Architecture

### Bearer Token Authentication

```
Request → TenantMiddleware → Extract Bearer Token
    ↓
Hash Token (SHA256) → Lookup TenantConfig
    ↓
Set TenantContext (via contextvars) → Process Request
```

### Tenant Isolation

Each tenant has:
- Independent LLM/RAG provider configurations
- Isolated Skills and Tools
- Separate session and message data
- Custom prompt templates

Configuration merging:
```
Default Config (settings/base.py)
    ↓
Tenant Override (tenants/{tenant_id}.json)
    ↓
Final Config (merged)
```

---

## Streaming Output System

### Tag-Based Filtering

ASRI recognizes and classifies LLM output by XML tags:

| Tag | Content Type | Display |
|-----|-------------|---------|
| `<think>` | Thinking process | Collapsible thinking panel |
| `tool_call` | Tool invocation | Tool execution details |
| `<answer>` | Final response | Main chat message |

### Streaming Protocols

**WebSocket** (Recommended):
```
Client → {"type": "chat", "message": "..."} → Server
Server → {"type": "token", "content": "..."} → Client (streaming)
Server → {"type": "done", "content": ""} → Client (complete)
```

**SSE** (Alternative):
```
GET /chatbot/api/chat/?stream=true
Response: text/event-stream
data: {"type": "token", "content": "..."}
```

---

## Request Lifecycle

### Chat Request Flow

1. **Client** sends message via WebSocket
2. **API Layer** validates Bearer Token, extracts tenant context
3. **WebSocketService** routes to ChatService
4. **ChatService** loads session, message history, and tenant config
5. **Agent** (ReAct or Pipeline) executes:
   - Loads LLM provider from config
   - Builds prompt with history and context
   - Calls LLM (streaming)
   - Parses response for actions
   - Executes tools/skills if needed
   - Iterates until final answer
6. **WebSocketService** streams tokens to client in real-time
7. **ChatService** saves messages to database
8. **Client** receives and renders response

---

## Key Design Patterns

### Provider/Registry Pattern

All external integrations follow this pattern:
1. Abstract base class defines interface
2. Concrete implementations provide specifics
3. Registry enables dynamic lookup by name
4. Factory creates instances from config

### Pipeline/Frame Processing

Pipeline Agent uses a Frame processor chain:
```
Input Frame → Processor 1 → Processor 2 → ... → Output Frame
```

Each processor:
- Receives a Frame
- Transforms or enriches it
- Forwards to next processor
- Can yield intermediate results for streaming

### AgentContext

Central context object carrying:
- Current session state
- Available tools/skills
- Execution trace
- Token counts
- Tenant configuration

---

## Data Model Overview

### Core Entities

```
ChatSession (1) ──── (N) Message
     │
     ├── session_id (UUID)
     ├── tenant_id
     ├── title
     └── metadata (JSON)

Message
     ├── message_id (UUID)
     ├── session_id (FK via code)
     ├── role (user/assistant/system)
     ├── content
     └── trace (JSON) - execution details

LLMProvider
     ├── provider_id (UUID)
     ├── tenant_id
     ├── provider_type (openai/ollama/custom)
     ├── config (JSON) - api_key, model, etc.
     └── is_default
```

---

## Three Core Design Capabilities

### 1. Parallel Streaming Tool Use

When the LLM issues multiple `tool_calls` in one response, `AsyncExecutorProcessor` dispatches them all to separate async tasks and runs them in parallel. Results are collected and fed back to the LLM as a batch — no sequential waiting.

```
LLM Response
    │
    ├─► tool_call[0] ─► AsyncTask ─► Result[0] ─┐
    ├─► tool_call[1] ─► AsyncTask ─► Result[1] ─┬► Batch Feed ► LLM
    └─► tool_call[2] ─► AsyncTask ─► Result[2] ─┘
```

**Key file**: `apps/agent/pipeline/processors/` — `AsyncExecutorProcessor`

---

### 2. Interleaved Thinking And Answer

In `interleaved_thinking` prompt mode, the LLM streams `<think>`, `<tool_call>`, and `<answer>` tags in a single pass. `FullDuplexLLMProcessor` feeds each token to `StreamingTagFilter` in real time, classifying and forwarding chunks to the client without waiting for a complete response.

```
LLM Stream: "<think>reasoning...</think><tool_call>...</tool_call><answer>text</answer>"
                                        │
                              StreamingTagFilter
                                        │
    ├───────────────────────────────────────────────────────────────────────────────
    │ {type: "thought",   content: "reasoning..."}  →  Thinking Panel
    │ {type: "tool_call", content: "..."}           →  Tool Execution
    └ {type: "answer",    content: "text"}          →  Chat Bubble
```

**Key file**: `apps/agent/pipeline/processors/full_duplex_llm_processor.py`

---

### 3. Adaptive Interrupt

When a new message arrives for a session that has an active stream, ASRI automatically signals the old stream to stop, waits for it to finish saving context, then starts the new stream with a consistent state. If the stream is killed before the normal save path, a `finally`-block fallback ensures context is never lost.

```
New Message arrives
    │
    ├─ Old stream exists? ─► interrupt_event.set()  (signal stop)
    │                     └─► await done_event.wait() (max 5s)
    │
    ├─ Start new stream ─► load fresh context from DB
    │
    └─ Old stream finally-block:
          if not context_saved: save context + mark interrupted
          done_event.set()  (unblock new stream)
```

**Key file**: `apps/services/chat_service.py` — `_stream_done_events`, `_streaming_sessions`

---

## Related Documentation

- [Installation Guide](docs/INSTALL.md) - Detailed setup instructions
- [Chat API](docs/chat-api.md) - Chat API documentation
- [Agent System](docs/agent-guide.md) - ReAct/Pipeline Agent deep dive
- [Extension Guide](docs/extension-guide.md) - Adding new providers

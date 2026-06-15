# ASRI Developer Documentation

ASRI is an intelligent conversational agent service built on Django 4.1. It employs a unified Pipeline Agent architecture (Frame pipeline framework), supporting a database-driven Prompt system, multiple LLM Providers, WebSocket streaming output, multi-tenant isolation, and an extensible Skill/Tool/RAG capability system.

## Core Features

- **Pipeline Agent**: Unified Frame pipeline architecture with native function_calling support
- **Multiple Prompt Modes**: react / skill_decision / interleaved_thinking / pipeline
- **Streaming Tag Filtering**: Automatically identifies `<think>`, `tool_call`, `<answer>` tags
- **Multi LLM Provider**: OpenAI / Ollama / Custom OpenAI-compatible
- **RAG Integration**: HTTP RAG / FAQ RAG
- **WebSocket Streaming**: Real-time token-level push, supporting both SSE and WebSocket protocols
- **Multi-tenant Isolation**: Tenants identified via `X-Tenant-Id` header, with tenant-level configuration, skill, and data isolation
- **Local Development Friendly**: Uses the `example` tenant by default, no Token required, works out of the box

---

## Quick Start

### Prerequisites

- Python 3.10+
- Django 4.1
- SQLite (default, zero configuration) or MySQL (production)

### Installation & Startup

```bash
# One-click installation (venv + pip + npm + build + migrate + seed)
./setup.sh

# Start the service
./start.sh
```

### Running Tests

```bash
pytest apps/tests/ -v
```

---

## Document Navigation

| Document | Description |
|----------|-------------|
| [chat-api.md](chat-api.md) | Chat API: HTTP non-streaming, WebSocket streaming, SSE mode, batch conversation |
| [agent-guide.md](agent-guide.md) | Agent System: ChatAgent Pipeline Frame architecture in detail |
| [skill-guide.md](skill-guide.md) | Skill System: skill registration, filesystem loading, SkillLoader, tenant isolation |
| [tool-guide.md](tool-guide.md) | Tool System: BaseTool, MCPTool, tool functions |
| [llm-rag-guide.md](llm-rag-guide.md) | LLM + RAG Provider: OpenAI / Ollama / Custom + HTTP RAG / FAQ RAG |
| [extension-guide.md](extension-guide.md) | Extension Guide: how to add new LLM Provider / RAG / Tool / Skill |
| [disable_thinking_mode.md](disable_thinking_mode.md) | Disable Thinking Mode: configure Agent reasoning output |

---

## Glossary

| Term | Description |
|------|-------------|
| **Parallel Streaming Tool Use** | Concurrent tool execution — LLM triggers multiple tool_calls simultaneously, processed in parallel by `AsyncExecutorProcessor` |
| **Interleaved Thinking And Answer** | Interleaved thinking stream — in `interleaved_thinking` mode, reasoning and tool calls are streamed in the same frame |
| **Adaptive Interrupt** | Adaptive interrupt — interrupt at any moment with a new message; context is automatically preserved and resumed |
| **ReAct** | Reasoning + Acting, a think-act-observe loop driven by text parsing |
| **Pipeline** | LLM native function_calling based Agent mode using Frame processing chain |
| **Tenant** | Isolated configuration unit, each tenant has its own configuration, skills, LLM Provider |
| **Skill** | Complex multi-step capability abstraction with complete decision trees or process documents |
| **Tool** | Single-step external capability (e.g., MCP remote invocation) |
| **RAG** | Retrieval-Augmented Generation |
| **AgentContext** | Agent runtime context carrying session state, available capabilities, and execution trace |
| **Prompt Mode** | System prompt mode that determines LLM output format and parsing strategy |
| **Frame** | Data unit in the Pipeline framework that flows through the processor chain |
| **FrameProcessor** | Processor in the Pipeline framework that receives and forwards Frames |
| **ActionExecutor** | Action dispatcher that routes Agent Actions to RAG / Tool / Skill |

---

## Configuration Overview

Core configuration is managed through the `settings.CHATBOT` dictionary. Tenant configurations in the database can override:

| Config Key | Default | Description |
|------------|---------|-------------|
| `AGENT_MODE` | `'react'` | Agent mode: `'react'` or `'pipeline'` |
| `REACT_PROMPT_MODE` | `'interleaved_thinking'` | Prompt mode: `'react'` / `'skill_decision'` / `'interleaved_thinking'` |
| `REACT_MAX_ITERATIONS` | `10` | Maximum ReAct iterations |

Skill storage path configuration:

| Environment Variable | Default | Description |
|----------------------|---------|-------------|
| `ASRI_SKILLS_DIR` | `<project_root>/data/tenant/` | Skills root directory; can be set to an external path like `~/.asri` |

See Agent/Tool/Skill documentation for detailed configuration.

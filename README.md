# ASRI - Intelligent Dialogue Robot Service

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-4.1-green.svg)](https://www.djangoproject.com/)
[![React](https://img.shields.io/badge/React-19-blue.svg)](https://react.dev/)

[Chinese Version](README_cn.md)

## What is ASRI?

Traditional LLM agents suffer from three fundamental problems: **latency accumulates** as tools execute sequentially, **reasoning is invisible** to the user until the final answer arrives, and **interruption is destructive** — there is no clean way to interject mid-response.

ASRI is an intelligent dialogue robot service built on Django 4.1 that addresses all three at the system level. Its **Interleave Engine** enables three breakthrough capabilities — streaming tool use, concurrent tool execution, and adaptive interruption — all powered by a unified Pipeline Agent with LLM native function_calling.

## Key Features

### Three Core Capabilities

- **🧠 Interleaved Thinking And Answer** — As soon as the LLM outputs a complete `<tool_call>` during streaming, the tool is triggered immediately — without waiting for the full LLM response to finish. Thinking and tool execution overlap in the same stream, cutting first-token latency from seconds to milliseconds.

- **🔀 Parallel Streaming Tool Use** — When the LLM plans multiple `tool_calls` in a single response, `AsyncExecutorProcessor` runs them all in parallel. No sequential bottleneck, no idle waiting.

- **⚡ Adaptive Interrupt** — The Agent loop dynamically adapts its next step on every cycle. Users can interrupt at any moment; the agent merges or sequences the new request intelligently without losing context.

### Additional Features

- **Database-Driven Prompts**: All system prompts loaded from DB per tenant, fully configurable without code changes
- **Multi-LLM Support**: OpenAI API, Ollama, and any OpenAI-compatible endpoint. More providers coming soon.
- **WebSocket Streaming**: Real-time token-level streaming via WebSocket and SSE
- **RAG Integration**: HTTP RAG and FAQ RAG modes
- **Multi-Tenant Isolation**: Complete tenant-level configuration, skill, and data isolation with Bearer Token auth
- **Session Management**: Full session and message management with one-to-many and many-to-one conversation modes
- **Extensible Architecture**: Custom Skills, Tools, Prompts via Provider/Registry pattern
- **Database Support**: SQLite (default, zero-config) or MySQL (production)
- **Docker Support**: One-command deployment with Docker Compose

## Architecture

![ASRI System Architecture](docs/architecture.drawio.png)

> Source: [`docs/architecture.drawio`](docs/architecture.drawio) — open in [draw.io](https://app.diagrams.net/) to edit.

## ARC Model — Coming Soon

ARC (Advantage Regularization Conditioning) is a reinforcement learning algorithm designed for open-ended interactive scenarios. It solves the **reward fairness** problem in multi-policy RL — when an agent must learn when to think silently, when to answer aloud, and when to call tools, global advantage comparison unfairly penalizes shorter strategies.

ARC trains the model to fairly master all these strategies. Combined with the INTER3 channel-separation architecture, it delivers **higher accuracy with lower latency**:

### Benchmark Results (Qwen3-8B)

| Method | Tau2 Bench (airline) | Tau2 Bench (retail) | Tau2 Bench (telecom) | TTFT |
|--------|---------------------:|--------------------:|---------------------:|-----:|
| Qwen3-8B No-Think | 14.61 | 36.55 | 32.75 | 0.05s |
| Qwen3-8B Think | 29.75 | 38.71 | 23.46 | 4.91s |
| SFT | 38.58 | — | — | 0.61s |
| SFT + GRPO | 33.35 | — | — | 0.71s |
| **SFT + (GRPO + ARC)** | **40.95** | **45.61** | **21.05** | **1.27s** |

> **Key insight**: ARC achieves +9.60 over Think baseline on Tau2 Bench (31.35 → 40.95) while cutting TTFT by **74%** (4.91s → 1.27s). The latency–quality tradeoff is redefined.

> ⚠️ The ARC model is not yet included in this open-source release. Stay tuned!

## Tech Stack

| Layer | Technology |
|-------|------------|
| Backend | Django 4.1, Python 3.10+, Daphne (ASGI) |
| Frontend | React 19, TypeScript 5.9, Ant Design 6, Vite 8 |
| State Management | Zustand, TanStack Query |
| Database | SQLite (default, zero-config), MySQL (production) |
| Cache | Redis (production), InMemory (dev) |
| WebSocket | Channels 4.0+, Daphne |

## Quick Start

### Prerequisites

- Python 3.10+
- Node.js 18+

### 30-Second Setup

```bash
git clone https://github.com/your-org/asri.git
cd asri
./setup.sh       # One-command: venv + pip + npm + build + migrate + seed
./start.sh       # Start the server
```

Visit http://127.0.0.1:8000/ to start chatting.

### Manual Setup

See the [Installation Guide](docs/INSTALL.md) for step-by-step instructions, Docker deployment, and production configuration.

## API Overview

### Chat Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/chatbot/api/chat/` | Non-streaming chat (supports `stream=true` for SSE) |
| WebSocket | `/ws/chat/{session_id}/` | WebSocket streaming (Bearer Token auth) |
| POST | `/chatbot/api/chat/batch/` | Batch chat (many-to-one) |

### Session Management

| Method | Path | Description |
|--------|------|-------------|
| GET | `/chatbot/api/sessions/` | List sessions |
| POST | `/chatbot/api/sessions/` | Create session |
| GET | `/chatbot/api/sessions/{id}/` | Session details |
| PUT | `/chatbot/api/sessions/{id}/` | Update session |
| DELETE | `/chatbot/api/sessions/{id}/` | Delete session |
| GET | `/chatbot/api/sessions/{id}/messages/` | Message history |

### Provider Management

| Method | Path | Description |
|--------|------|-------------|
| GET/POST | `/chatbot/api/llm-providers/` | LLM Provider config |
| GET/POST | `/chatbot/api/rag-providers/` | RAG Provider config |
| GET/POST | `/chatbot/api/tools/` | Tool management |
| GET/POST | `/chatbot/api/skills/` | Skill management |

## LLM Provider Configuration

LLM Providers are configured through the Admin page at http://127.0.0.1:8000/admin/.
Navigate to **Models** section to add your OpenAI, Ollama, or custom LLM providers.
Environment variables are not used for LLM configuration.

## Documentation

| Document | Description |
|----------|-------------|
| [Installation Guide](docs/INSTALL.md) | Detailed installation instructions |
| [Architecture](docs/ARCHITECTURE.md) | System architecture overview |
| [Contributing Guide](CONTRIBUTING.md) | How to contribute to the project |
| [Chat API](docs/chat-api.md) | Chat API documentation (HTTP/WebSocket/SSE) |
| [Agent System](docs/agent-guide.md) | ReAct/Pipeline Agent guide |
| [LLM/RAG Guide](docs/llm-rag-guide.md) | LLM and RAG integration |
| [Skill Guide](docs/skill-guide.md) | Skill system documentation |
| [Tool Guide](docs/tool-guide.md) | Tool system documentation |
| [Extension Guide](docs/extension-guide.md) | Adding new providers/tools/skills |

## Testing

```bash
# Run all tests
cd backend
pytest apps/tests/ -v

# Run specific tests
pytest apps/tests/test_agent.py -v

# Run frontend E2E tests
cd frontend
npm run test:e2e
```

## Project Structure

```
asri/
├── backend/                 # Django backend
│   ├── apps/                # Application modules
│   │   ├── agent/           # Agent implementations
│   │   ├── api/             # HTTP & WebSocket APIs
│   │   ├── integrations/    # Provider abstractions
│   │   ├── services/        # Business logic
│   │   └── tenant/          # Multi-tenant support
│   ├── manage.py            # Django management script
│   └── requirements.txt     # Python dependencies
├── frontend/                # React frontend
│   ├── src/                 # Source code
│   ├── package.json         # NPM dependencies
│   └── vite.config.ts       # Vite configuration
├── config/                  # Django project config
├── docs/                    # Technical documentation
├── Dockerfile               # Docker image
├── docker-compose.yml       # Docker Compose
├── setup.sh                 # One-command setup script
└── start.sh                 # Startup script
```

## Contributing

We welcome contributions! Please read our [Contributing Guide](CONTRIBUTING.md) for details on our code of conduct and the process for submitting pull requests.

## Security

If you discover a security vulnerability, please see [SECURITY.md](SECURITY.md) for responsible disclosure procedures.

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

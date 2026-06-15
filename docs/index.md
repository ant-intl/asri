# ASRI 开发者文档

ASRI 是一个基于 Django 4.1 的智能对话机器人服务，采用 Pipeline Agent 统一架构（Frame 管道框架），支持数据库驱动的 Prompt 系统、多 LLM Provider 接入、WebSocket 流式输出、多租户隔离，以及可扩展的 Skill/Tool/RAG 能力体系。

## 核心特性

- **Pipeline Agent**: 统一 Frame 管道架构，支持原生 function_calling
- **多 Prompt 模式**: react / skill_decision / interleaved_thinking / pipeline
- **流式标签过滤**: 自动识别 `<think>`（思考）、`tool_call`（工具调用）、`<answer>`（回答）标签
- **多 LLM Provider**: OpenAI / Ollama / Custom OpenAI-compatible
- **RAG 集成**: HTTP RAG / FAQ RAG
- **WebSocket 流式**: Token 级实时推送，支持 SSE 和 WebSocket 两种协议
- **多租户隔离**: `X-Tenant-Id` header 识别租户，租户级配置/技能/数据隔离
- **本地开发友好**: 默认使用 example 租户，无需 Token，开箱即用

---

## 快速开始

### 环境要求

- Python 3.10+
- Django 4.1
- SQLite（默认，零配置）或 MySQL（生产环境）

### 安装与启动

```bash
# 一键安装（venv + pip + npm + build + migrate + seed）
./setup.sh

# 启动服务
./start.sh
```

### 运行测试

```bash
pytest apps/tests/ -v
```

---

## 文档导航

| 文档 | 说明 |
|------|------|
| [chat-api.md](chat-api.md) | 聊天 API：HTTP 非流式、WebSocket 流式、SSE 模式、批量对话 |
| [agent-guide.md](agent-guide.md) | Agent 系统：ChatAgent Pipeline Frame 架构详解 |
| [skill-guide.md](skill-guide.md) | Skill 系统：技能注册、文件系统加载、SkillLoader、租户隔离 |
| [tool-guide.md](tool-guide.md) | Tool 系统：BaseTool、MCPTool、工具函数 |
| [llm-rag-guide.md](llm-rag-guide.md) | LLM + RAG Provider：OpenAI / Ollama / Custom + HTTP RAG / FAQ RAG |
| [extension-guide.md](extension-guide.md) | 扩展指南：如何新增 LLM Provider / RAG / Tool / Skill |
| [disable_thinking_mode.md](disable_thinking_mode.md) | 关闭思考模式：配置 Agent 思考过程输出 |

---

## 术语表

| 术语 | 说明 |
|------|------|
| **一心多用** | 并发工具执行，LLM 同时触发多个 tool_call，`AsyncExecutorProcessor` 并行处理 |
| **边想边答** | 交错思考流，`interleaved_thinking` 模式下思考与工具调用同帧流式输出 |
| **随机应变** | 自适应中断，任意时刻打断并发新消息，上下文自动保留衔接 |
| **ReAct** | Reasoning + Acting，思考-行动-观察循环，Agent 通过文本解析驱动 |
| **Pipeline** | 基于 LLM 原生 function_calling 的 Agent 模式，使用 Frame 处理链 |
| **Tenant** | 租户，每个租户拥有独立的配置、技能、LLM Provider |
| **Skill** | 技能，复杂多步骤能力抽象，包含完整的决策树或流程文档 |
| **Tool** | 工具，单步执行的外部能力（如 MCP 远程调用） |
| **RAG** | Retrieval-Augmented Generation，检索增强生成 |
| **AgentContext** | Agent 运行时上下文，携带会话状态、可用能力、执行追踪 |
| **Prompt Mode** | 系统提示模式，决定 LLM 输出格式和解析策略 |
| **Frame** | Pipeline 框架中的数据单元，在处理器链中流转 |
| **FrameProcessor** | Pipeline 框架中的处理器，接收并转发 Frame |
| **ActionExecutor** | 动作执行器，将 Agent 的 Action 分发到 RAG / Tool / Skill |

---

## 配置概览

核心配置通过 `settings.CHATBOT` 字典管理，数据库中的租户配置可覆盖：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `AGENT_MODE` | `'react'` | Agent 模式：`'react'` 或 `'pipeline'` |
| `REACT_PROMPT_MODE` | `'interleaved_thinking'` | Prompt 模式：`'react'` / `'skill_decision'` / `'interleaved_thinking'` |
| `REACT_MAX_ITERATIONS` | `10` | ReAct 最大迭代次数 |

技能存储路径配置：

| 环境变量 | 默认值 | 说明 |
|--------|--------|------|
| `ASRI_SKILLS_DIR` | `<project_root>/data/tenant/` | 技能根目录，可设为 `~/.asri` 等外部路径 |

详细配置说明参见 Agent/Tool/Skill 相关文档。

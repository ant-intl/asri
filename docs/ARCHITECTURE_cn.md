# 架构概览

本文档提供了 ASRI 系统架构的高层概览。

## 系统简介

ASRI 是一个基于 Django 4.1 的智能对话机器人服务，采用统一的 ChatAgent（Pipeline Frame 架构）。内置 **Interleave Engine**，支持三大核心能力：并发工具执行（一心多用）、交错思考流（边想边答）和自适应中断（随机应变）。同时支持数据库驱动的 Prompt 管理、多 LLM 集成、WebSocket 流式输出，以及可扩展的 Skill/Tool/RAG 系统。

## 高层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                            客户端层                                   │
│   React 19 SPA + Ant Design 6 + WebSocket 客户端                     │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                            API 层                                    │
│   HTTP 端点 (Chat/Session/Message/Providers) + WebSocket 处理器      │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          Service 层                                  │
│   ChatService / SessionService / WebSocketService                    │
└─────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                           Core 层                                    │
│   ChatAgent + Interleave Engine（Pipeline Frame 架构）               │
│   AgentContext / ActionExecutor                                       │
│   │                                                                   │
│   ├─► 一心多用: AsyncExecutorProcessor （并行 tool_call）             │
│   ├─► 边想边答: FullDuplexLLMProcessor + StreamingTagFilter          │
│   └─► 随机应变: interrupt_event + finally-block 上下文保存         │
└─────────────────────────────────────────────────────────────────────┘
          │                    │                    │
          ▼                    ▼                    ▼
┌───────────────┐   ┌───────────────────┐   ┌───────────────┐
│  LLM 层       │   │  RAG/Skill/Tool   │   │ Memory 层     │
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
│                        持久化层                                      │
│   Session / Message / Provider Config / Tenant (Django ORM + MySQL) │
└─────────────────────────────────────────────────────────────────────┘
```

## 分层架构

### 1. API 层 (`backend/apps/api/`)

处理 HTTP 请求和 WebSocket 连接。

**组件**:
- `http/` - REST API 端点
  - `chat.py` - 聊天端点（非流式 + SSE）
  - `session.py` - Session CRUD 操作
  - `message.py` - 消息历史
  - `llm_config.py`, `rag_config.py`, `tool_config.py`, `skill_config.py` - Provider 管理
- `websocket/` - WebSocket 处理器
  - `chat_consumer.py` - 实时流式处理器
- `serializers/` - 数据序列化

**职责**:
- 请求验证和解析
- 响应格式化
- 认证（Bearer Token）
- 错误处理

### 2. Service 层 (`backend/apps/services/`)

协调 API 和 Core 层之间的业务逻辑。

**组件**:
- `chat_service.py` - 聊天编排
- `session_service.py` - 会话管理
- `websocket_service.py` - WebSocket 消息处理

**职责**:
- 协调 Core 和 Integration 层
- 事务管理
- 业务规则执行
- **不包含直接数据库操作**

### 3. Core 层 (`backend/apps/agent/`)

实现 Agent 执行逻辑。

**组件**:
  - `chat_agent.py` - ChatAgent（Pipeline Frame 架构）
  - `base.py` - Agent 基础抽象
  - `context.py` - Agent 运行时上下文
- `prompts/` - Prompt 模板（数据库驱动）
  - `base.py` - 基础系统 Prompt
  - `dynamic_prompt.py` - 数据库动态 Prompt
- `parsers/` - 响应解析
- `hooks/` - Hook 系统（确认、拦截）

**Agent 执行**:

ChatAgent 使用基于 Frame 的 Pipeline 架构，通过 LLM 原生 function_calling 驱动：
```
用户输入 → LLM + Tools → 原生 function_calling
    ↓
解析 Tool 调用 → 并行执行 → 获取结果
    ↓
将结果反馈 LLM → 继续直到最终答案
```

### 4. Integration 层 (`backend/apps/integrations/`)

为外部服务提供统一抽象。

**组件**:
- `llm/` - LLM providers
  - `base.py` - `BaseLLMProvider`（抽象类）
  - `openai_provider.py`, `ollama_provider.py`, `custom_provider.py`
  - `registry.py` - LLM Registry
- `rag/` - RAG providers
  - `base.py` - `BaseRAGProvider`（抽象类）
  - `faq_rag_provider.py`
- `skill/` - Skill registry
  - `base.py` - `BaseSkill`（抽象类）
  - `registry.py` - Skill Registry
- `tool/` - Tool registry
  - `base.py` - `BaseTool`（抽象类）
  - `registry.py` - Tool Registry
- `memory/` - Memory 管理
  - `base.py` - `BaseMemory`（抽象类）
  - `conversation.py`, `summary.py`

**Provider 模式**:
```python
# 所有 provider 遵循相同模式：
# 1. 继承基础类
# 2. 实现抽象方法
# 3. 注册到 Registry

class CustomLLMProvider(BaseLLMProvider):
    async def chat(self, messages: list, **kwargs) -> dict:
        # 实现
        pass

    async def stream_chat(self, messages: list, **kwargs):
        async for chunk in self._stream(messages):
            yield chunk

LLMRegistry.register('custom', CustomLLMProvider)
```

### 5. 持久化层 (`backend/apps/entities/`)

用于数据存储的 Django 模型。

**关键模型**:
- `ChatSession` - 用户会话管理
- `Message` - 聊天消息历史，包含 trace 数据
- `LLMProvider` - LLM 配置
- `RAGProvider` - RAG 服务配置
- `Tool`, `Skill` - 自定义集成
- `Tenant` - 多租户支持

**设计原则**:
- UUID 主键
- 自动时间戳（`created_at`, `updated_at`）
- JSON 字段存储动态元数据
- 模式中无外键（通过代码强制执行）

---

## 多租户架构

### Bearer Token 认证

```
请求 → TenantMiddleware → 提取 Bearer Token
    ↓
哈希 Token (SHA256) → 查找 TenantConfig
    ↓
设置 TenantContext (通过 contextvars) → 处理请求
```

### 租户隔离

每个租户拥有：
- 独立的 LLM/RAG provider 配置
- 隔离的 Skill 和 Tool
- 独立的 session 和 message 数据
- 自定义 prompt 模板

配置合并：
```
默认配置 (settings/base.py)
    ↓
租户覆盖 (tenants/{tenant_id}.json)
    ↓
最终配置 (合并后)
```

---

## 流式输出系统

### 基于标签的过滤

ASRI 通过 XML 标签识别和分类 LLM 输出：

| 标签 | 内容类型 | 显示 |
|-----|---------|------|
| `<think>` | 思考过程 | 可折叠思考面板 |
| `tool_call` | 工具调用 | 工具执行详情 |
| `<answer>` | 最终响应 | 主要聊天消息 |

### 流式协议

**WebSocket**（推荐）:
```
客户端 → {"type": "chat", "message": "..."} → 服务器
服务器 → {"type": "token", "content": "..."} → 客户端（流式）
服务器 → {"type": "done", "content": ""} → 客户端（完成）
```

**SSE**（备选）:
```
GET /chatbot/api/chat/?stream=true
响应: text/event-stream
data: {"type": "token", "content": "..."}
```

---

## 请求生命周期

### 聊天请求流程

1. **客户端** 通过 WebSocket 发送消息
2. **API 层** 验证 Bearer Token，提取租户上下文
3. **WebSocketService** 路由到 ChatService
4. **ChatService** 加载 session、消息历史和租户配置
5. **Agent**（ReAct 或 Pipeline）执行：
   - 从配置加载 LLM provider
   - 构建包含历史和上下文的 prompt
   - 调用 LLM（流式）
   - 解析响应中的行动
   - 如需要执行 tools/skills
   - 迭代直到最终答案
6. **WebSocketService** 实时流式推送 tokens 到客户端
7. **ChatService** 保存消息到数据库
8. **客户端** 接收并渲染响应

---

## 关键设计模式

### Provider/Registry 模式

所有外部集成遵循此模式：
1. 抽象基础类定义接口
2. 具体实现提供细节
3. Registry 支持按名称动态查找
4. Factory 从配置创建实例

### Pipeline/Frame 处理

Pipeline Agent 使用 Frame 处理器链：
```
输入 Frame → 处理器 1 → 处理器 2 → ... → 输出 Frame
```

每个处理器：
- 接收 Frame
- 转换或丰富它
- 转发到下一个处理器
- 可以 yield 中间结果用于流式

### AgentContext

中心上下文对象携带：
- 当前 session 状态
- 可用 tools/skills
- 执行 trace
- Token 计数
- 租户配置

---

## 数据模型概览

### 核心实体

```
ChatSession (1) ──── (N) Message
     │
     ├── session_id (UUID)
     ├── tenant_id
     ├── title
     └── metadata (JSON)

Message
     ├── message_id (UUID)
     ├── session_id (通过代码 FK)
     ├── role (user/assistant/system)
     ├── content
     └── trace (JSON) - 执行详情

LLMProvider
     ├── provider_id (UUID)
     ├── tenant_id
     ├── provider_type (openai/ollama/custom)
     ├── config (JSON) - api_key, model 等
     └── is_default
```

---

## 三大核心设计能力

### 1. 并发工具执行（一心多用）

LLM 在一次响应中可发出多个 `tool_call`，`AsyncExecutorProcessor` 将它们全部分发到独立的异步任务并行执行，结果合并后一次性反馈给 LLM。

```
LLM 回复
    │
    ├─► tool_call[0] ─► AsyncTask ─► Result[0] ─┐
    ├─► tool_call[1] ─► AsyncTask ─► Result[1] ─┬► 批量反馈 ► LLM
    └─► tool_call[2] ─► AsyncTask ─► Result[2] ─┘
```

**关键文件**: `apps/agent/pipeline/processors/` — `AsyncExecutorProcessor`

---

### 2. 交错思考流（边想边答）

`interleaved_thinking` Prompt 模式下，LLM 在同一次过中流式输出 `<think>`、`<tool_call>` 和 `<answer>` 标签。`FullDuplexLLMProcessor` 将每个 token 实时传入 `StreamingTagFilter`，分类并转发给客户端，不等待完整响应。

```
LLM 流: "<think>思考...</think><tool_call>...</tool_call><answer>文本</answer>"
                                 │
                       StreamingTagFilter
                                 │
    ├─ {type: "thought",   content: "思考..."}  →  思考面板
    ├─ {type: "tool_call", content: "..."}   →  工具执行
    └─ {type: "answer",    content: "文本"}  →  聊天气泡
```

**关键文件**: `apps/agent/pipeline/processors/full_duplex_llm_processor.py`

---

### 3. 自适应中断（随机应变）

当一个正在流式的会话收到新消息时，ASRI 自动中断旧流并等待其保存上下文完成，再以一致的状态启动新流。如果流式在正常保存路径之前被杀死，`finally` 块内将保证上下文不丢失。

```
新消息到达
    │
    ├─ 存在旧流? ─► interrupt_event.set()（发信号）
    │             └─► await done_event.wait()（最多 5s）
    │
    ├─ 启动新流 ─► 从 DB 加载新鲜上下文
    │
    └─ 旧流 finally 块:
          if not context_saved: 保存上下文 + 标记已中断
          done_event.set()（解除新流阻塞）
```

**关键文件**: `apps/services/chat_service.py` — `_stream_done_events`、`_streaming_sessions`

---

## 相关文档

- [安装指南](docs/INSTALL_cn.md) - 详细的设置说明
- [聊天 API](docs/chat-api.md) - 聊天 API 文档
- [Agent 系统](docs/agent-guide.md) - ReAct/Pipeline Agent 深入
- [扩展指南](docs/extension-guide.md) - 添加新的 providers

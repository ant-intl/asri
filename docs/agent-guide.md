# Agent 系统

ASRI 采用统一的 **ChatAgent** 实现，基于 Pipeline Frame 框架，支持 LLM 原生 function_calling 驱动。Agent 的行为通过 **Prompt 模式**（从数据库加载）来差异化，无需多种 Agent 实现。

**文件**: `apps/agent/agent/chat_agent.py`

---

## BaseAgent 抽象基类

**文件**: `apps/agent/agent/base.py`

所有 Agent 必须继承 `BaseAgent` 并实现两个核心方法：

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
        """非流式执行，返回完整结果。"""

    @abstractmethod
    async def stream(
        self, query: str,
        history: List[Dict[str, str]] = None,
        context: AgentContext = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """流式执行，逐块 yield 结果。"""
```

### 返回格式

`run()` 返回：

```python
{
    "answer": str,           # 最终回答
    "trace": list[dict],     # 执行追踪
    "prompt_tokens": int,
    "completion_tokens": int,
    "total_tokens": int,
    "model": str,            # 使用的模型名称
    "context_messages": list[dict],  # 完整上下文（用于后续轮次）
}
```

`stream()` yield 的 chunk 格式：

```python
{"type": "answer",     "content": "部分文本"}
{"type": "thought",    "content": "思考过程"}
{"type": "tool_call",  "content": "工具调用信息"}
{"type": "tool_result","content": "工具执行结果"}
{"type": "card",       "card_data": {...}}
{"type": "done",       "content": ""}
{"type": "error",      "content": "错误描述"}
```

---

## AgentContext 运行时上下文

**文件**: `apps/agent/agent/context.py`

每次 Agent 执行创建一个 `AgentContext` 实例，携带完整的运行时状态：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `session_id` | `str` | `''` | 会话 ID |
| `user_id` | `str` | `''` | 用户 ID |
| `tenant_id` | `str` | `None` | 租户 ID |
| `messages` | `list[dict]` | `[]` | 对话历史 |
| `current_query` | `str` | `''` | 当前用户查询 |
| `available_tools` | `list[str]` | `[]` | 可用工具名称列表 |
| `available_skills` | `list[str]` | `[]` | 可用技能名称列表 |
| `iteration_count` | `int` | `0` | 当前迭代次数 |
| `max_iterations` | `int` | `10` | 最大迭代次数 |
| `trace` | `list[dict]` | `[]` | 执行追踪条目 |
| `prompt_tokens` | `int` | `0` | Prompt Token 计数 |
| `completion_tokens` | `int` | `0` | Completion Token 计数 |
| `metadata` | `dict` | `{}` | 自定义元数据 |
| `hook_manager` | `HookManager` | `None` | Hook 管理器 |

### 核心方法

```python
# 添加追踪条目
context.add_trace(step_type='thought', content='用户询问退款...', metadata={})

# 递增迭代并检查是否超限
can_continue = context.increment_iteration()  # True / False

# 获取总 Token 数
total = context.get_total_tokens()
```

---

## ChatAgent

**文件**: `apps/agent/agent/chat_agent.py`

基于 Pipeline Frame 框架的统一 Agent 实现，使用 LLM 原生 **function_calling** 驱动执行。

### 初始化参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `llm_provider` | `BaseLLMProvider` | — | LLM 提供商实例 |
| `prompt_mode` | `str` | `'interleaved_thinking'` | Prompt 模式，决定加载哪个 DB PromptTemplate |
| `tenant_id` | `str` | `None` | 租户 ID |
| `max_iterations` | `int` | `10` | 最大 tool_call 轮数 |
| `interrupt_strategy` | `str` | `'none'` | Tool 中断策略 |

### Prompt 模式

Prompt 模式通过 `REACT_PROMPT_MODE` 配置（或租户级配置）指定，每个模式对应数据库 `PromptTemplate` 表中的一条记录：

| 模式 | 说明 | 解析策略 |
|------|------|----------|
| `interleaved_thinking` | 流式交错思考，默认模式 | 解析 `<think>`、`<tool_call>`、`<answer>` XML 标签 |
| `react` | 标准 ReAct 文本解析 | 解析 Thought/Action/Action Input 文本格式 |
| `skill_decision` | JSON 决策引擎 | 注入技能列表，解析 JSON 决策 |
| `pipeline` | 原生 function_calling 格式 | LLM 原生 tool_calls 驱动 |

Prompt 加载流程（懒加载）：
1. Agent 初始化时不加载 Prompt（仅保存 `prompt_mode`）
2. 首次执行时调用 `_ensure_prompt_initialized()` → `create_prompt_async(prompt_mode)`
3. 工厂函数查询 `PromptTemplate.objects.filter(name=prompt_mode, is_active=True, tenant_id=current_tenant)`
4. 返回 `DynamicPrompt` 实例，模板数据从数据库加载

### 执行流程

1. `_build_pipeline(context)` 创建处理器链：
   - `FullDuplexLLMProcessor` → `OutputCollectorProcessor`
   - 两者均启用 `enable_direct_mode=True`（同步帧处理）
   - `FullDuplexLLMProcessor` 注册 `AsyncExecutorProcessor` 用于异步工具执行
   - 使用 `build_tool_schemas(context)` 构建工具定义
   - 使用 `build_function_handlers(executor, context)` 构建处理函数

2. `_build_messages(query, history)` 构建消息列表：
   - System Prompt 通过 `DynamicPrompt.build_messages()` 生成
   - 支持 Jinja2 模板渲染，注入技能列表和工具 schemas
   - 支持多层 Prompt 策略（`layers` 字段）：`always` / `first_turn`

3. `_drive_pipeline(llm_processor, messages, queue)` 驱动执行：
   - 发送 `StartFrame` 初始化
   - 发送 `LLMMessagesAppendFrame` 触发 LLM 调用
   - LLM 流式检测到 tool_calls 立即发送 `AsyncFunctionCallFrame`
   - 接收 `FunctionCallEndFrame` 回调后重新调用 LLM（最多 `max_iterations` 轮）

4. 从 `asyncio.Queue` 收集输出 chunk

### Pipeline 工具函数

| 工具 | 注册条件 | 说明 |
|------|----------|------|
| `skill_load` | 始终注册 | 按需加载技能详情 |
| `execute_tool` | `context.available_tools` 非空 | 执行注册工具（含通过 `ToolRegistry` 注册的 RAG 工具） |

---

### 三大核心设计特性

#### 一心多用 — 并发工具执行

LLM 在一次 tool_calls 中可同时返回多个工具调用。`AsyncExecutorProcessor` 将它们并行分发给 `asyncio.gather`，所有结果收齐后再进入下一轮 LLM 调用。

```python
# 示意流程（高度简化）
pending_calls = [call1, call2, call3]
results = await asyncio.gather(*[execute(c) for c in pending_calls])
# 全部结果一起反馈给 LLM
```

#### 边想边答 — 交错思考流

`interleaved_thinking` 模式是默认模式。`FullDuplexLLMProcessor` 在流式处理中实时将 token 传入 `StreamingTagFilter`，根据 XML 标签将输出分类为 `thought` / `tool_call` / `answer` 三种类型并分别推流。

#### 随机应变 — 自适应中断

`ChatService` 在每个流式会话开始前检查是否有正在运行的旧流：

```python
# 出新流前自动中断旧流
old_event = _streaming_sessions.get(session_id)
if old_event:
    old_event.set()  # 发中断信号
    await asyncio.wait_for(done_event.wait(), timeout=5.0)  # 等待完成

# 尾部广拥：未正常保存时将退化上下文
finally:
    if not context_saved and agent:
        fallback_ctx = await agent.get_context_messages()
        await session_service.save_session_context(session_id, fallback_ctx)
```

---

## Database-Driven Prompt 系统

所有系统提示词存储在数据库中，通过 `PromptTemplate` 模型管理。

**模型文件**: `apps/chatbot/models/prompt_template.py`

**数据库表**: `chatbot_prompt`

### PromptTemplate 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 主键 |
| `tenant_id` | str | 租户标识（支持多租户隔离） |
| `name` | str | Prompt 模式名称（`react` / `skill_decision` / `interleaved_thinking` / `pipeline`） |
| `system_template` | text | 系统提示词模板（Jinja2 格式） |
| `user_template_mode` | str | 消息构建模式：`generic`（标准 `[system, history, user]`）或 `custom` |
| `user_template` | text | 用户消息模板（仅 custom 模式使用） |
| `layers` | JSON | 多层 Prompt 配置数组 |
| `extractor_config` | JSON | 输出解析器配置 |
| `is_active` | bool | 是否激活 |

### 唯一约束

`(tenant_id, name)` — 每个租户每个模式只能有一个激活的模板。

### 多层 Prompt (Layers)

`layers` 字段为 JSON 数组，每层包含：

| 字段 | 说明 |
|------|------|
| `name` | 层名称 |
| `target` | `system`（注入到 System Message）或 `user`（注入到 User Message） |
| `strategy` | `always`（每次）或 `first_turn`（仅首轮） |
| `template` | Jinja2 模板 |
| `order` | 排序 |
| `is_active` | 是否激活 |

### Extractor 配置

指定如何解析 LLM 输出为结构化 Action：

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

## StreamingTagFilter（流式标签过滤）

**文件**: `apps/agent/agent/chat_agent.py`

当使用 `interleaved_thinking` Prompt 模式时，ChatAgent 自动启用流式标签过滤，实时识别输出中的 XML 标签：

```
LLM 输出: "让我查一下...<think>需要查询用户信息</think><tool_call>query_user</tool_call>"
                              ↓
过滤后:  {"type": "thought",    "content": "需要查询用户信息"}
         {"type": "tool_call",  "content": "query_user"}
```

**标签映射规则**：
- `<think>...</think>` → `{type: 'thought'}`（思考过程）
- `<tool_call>...</tool_call>` → `{type: 'tool_call'}`（工具调用）
- `<answer>...</answer>` → `{type: 'answer'}`（最终回答）
- 无标签文本 → `{type: 'token'}`（流式 token）

标签过滤在 Pipeline 的 `FullDuplexLLMProcessor` 内部处理，无需外部预处理。

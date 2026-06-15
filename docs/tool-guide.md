# Tool 系统

Tool（工具）是 ASRI 中单步执行的外部能力抽象。与 Skill（复杂多步骤能力）不同，Tool 通常封装单次 API 调用或外部服务交互。

---

## BaseTool 抽象基类

**文件**: `apps/integrations/tool/base.py`

```python
class BaseTool(ABC):
    name: str = ''          # 工具名称
    description: str = ''   # 工具描述

    @abstractmethod
    async def execute(self, input_text: str, context: Any) -> str:
        """执行工具，返回结果字符串。"""
```

---

## ToolRegistry

**文件**: `apps/integrations/tool/base.py`

全局工具注册表（非租户隔离）：

| 方法 | 签名 | 说明 |
|------|------|------|
| `register` | `register(tool: BaseTool)` | 注册工具实例 |
| `get_tool` | `get_tool(name: str) → BaseTool \| None` | 按名称获取工具 |
| `list_tools` | `list_tools() → list[str]` | 列出所有工具名称 |

### 使用示例

```python
from apps.integrations.tool.base import ToolRegistry

# 注册
ToolRegistry.register(MyTool())

# 查询
tool = ToolRegistry.get_tool('mcp')
if tool:
    result = await tool.execute('get_balance:{"account":"123"}', context)
```

---

## MCPTool

**文件**: `apps/integrations/tool/mcp_tool.py`

封装 Alipay MCP (Model Context Protocol) 远程工具执行服务。在模块加载时自动注册到 ToolRegistry。

### 输入格式

```
sub_tool_name:{"arg1": "val1", "arg2": "val2"}
```

或无参数时：

```
sub_tool_name
```

### 配置项

通过租户配置文件的 `TOOLS` 数组配置，指定 `type: "mcp"`：

```json
{
  "name": "my-mcp-server",
  "type": "mcp",
  "enabled": true,
  "config": {
    "client_type": "custom",
    "endpoint": "https://example.com/mcp",
    "sse_endpoint": "/mcp/sse",
    "mcp_name": "my-mcp",
    "timeout": 30
  }
}
```

| 配置项 | 说明 | 必填 |
|--------|------|------|
| `client_type` | 客户端类型：`http`、`custom`、`sofa` | 是 |
| `endpoint` | MCP 服务基础地址 | 是 |
| `sse_endpoint` | SSE 端点路径 | 否 |
| `mcp_name` | MCP 服务名称 | 否 |
| `timeout` | 超时时间（秒） | 否 |

### 请求结构

```json
{
  "endpoint": "/worldfirstportalmcp/storefront/sse",
  "SYS_MERCHANT_ID": "...",
  "SYS_USER_ID": "...",
  "SYS_WALLET_ID": "...",
  "toolName": "get_balance",
  "arguments": "{\"account\": \"123\"}"
}
```

### 响应处理

1. 从 `data.data.content[0].text` 提取原始结果
2. 尝试 JSON 解析
3. 检测 `businessCardMCPAnswer` 标记卡片响应
4. 卡片响应时在 `context.metadata` 中设置 `card_response=True`

### 错误处理

| 场景 | 处理 |
|------|------|
| 超时（30s） | 返回超时提示字符串 |
| HTTP 错误 | 返回 HTTP 状态码 |
| JSON 解析失败 | 返回原始文本 |
| 端点未配置 | 返回配置缺失提示 |

---

## Agent 工具函数

**文件**: `apps/agent/agent/chat_agent.py`

ChatAgent 使用 FunctionSchema 定义 LLM 可调用的工具，通过 `build_tool_schemas()` 和 `build_function_handlers()` 动态构建。

### build_tool_schemas(context)

根据 AgentContext 的能力标志，构建工具列表：

| 工具 | 注册条件 | 参数 | 说明 |
|------|----------|------|------|
| `skill_load` | 始终注册 | `skill_name: string` | 按需加载技能详情 |
| `rag_search` | `context.rag_enabled` | `query: string` | 知识库检索 |
| `execute_tool` | `context.available_tools` 非空 | `tool_name, tool_input: string` | 执行注册工具 |
| `execute_skill` | `context.available_skills` 非空 | `skill_name: string` | 执行注册技能 |

### build_function_handlers(executor, context)

返回四个异步处理函数的字典：

```python
{
    "skill_load": handle_skill_load,      # SkillRegistry.get_skill()
    "rag_search": handle_rag_search,      # ActionExecutor.execute("RAG", ...)
    "execute_tool": handle_execute_tool,  # ActionExecutor.execute("TOOL", ...)
    "execute_skill": handle_execute_skill # ActionExecutor.execute("SKILL", ...)
}
```

### Handler 处理流程

每个 handler 接收 `FunctionCallParams` 参数：

```python
@dataclass
class FunctionCallParams:
    function_name: str          # 函数名
    tool_call_id: str           # 工具调用 ID
    arguments: Mapping[str, Any]  # 参数字典
    result_callback: Callable     # 返回结果的回调
```

Handler 通过 `params.result_callback(dict)` 返回结果，并在 `context` 中记录执行追踪。

### skill_load handler 详解

```python
async def handle_skill_load(params):
    skill_name = params.arguments.get("skill_name", "").strip()
    skill = SkillRegistry.get_skill(skill_name)  # 自动使用当前租户

    if skill is None:
        available = SkillRegistry.list_skills()
        await params.result_callback({
            "error": f"Skill '{skill_name}' not found.",
            # 提供可用技能列表帮助 LLM 修正
        })
        return

    await params.result_callback({
        "name": skill.name,
        "description": skill.description,
        "content": skill.content,  # 完整内容供 LLM 推理
    })
```

---

## FunctionSchema 定义规范

**文件**: `apps/agent/pipeline/framework.py`

```python
class FunctionSchema:
    def __init__(self, name, description, properties, required=None):
        ...

    def to_default_dict(self) -> dict:
        """转换为 OpenAI 函数定义格式。"""
        return {
            "name": self._name,
            "description": self._description,
            "parameters": {
                "type": "object",
                "properties": self._properties,
                "required": self._required,
            },
        }
```

### 自定义工具 Schema 示例

```python
my_schema = FunctionSchema(
    name="weather_query",
    description="查询指定城市的天气信息",
    properties={
        "city": {
            "type": "string",
            "description": "城市名称",
        },
    },
    required=["city"],
)
```

---

## ActionExecutor

**文件**: `apps/agent/agent/chat_agent.py`

Action 分发器（在 function_handlers 中实现），将工具调用路由到具体实现：

| Action | 分发逻辑 |
|--------|----------|
| `RAG` | `RAGRegistry.get_default_provider().search(action_input)` |
| `TOOL` | 解析 `tool_name:args` → `ToolRegistry.get_tool(name).execute(args, context)` |
| `SKILL` | `SkillRegistry.get_skill(action_input).execute(action_input, context)` |

---

## 相关文档

- Skill 系统 → [skill-guide.md](skill-guide.md)
- Agent 系统 → [agent-guide.md](agent-guide.md)
- 扩展新 Tool → [extension-guide.md](extension-guide.md)

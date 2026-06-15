# Unified Tool System - 统一工具系统

## 概述

本系统实现了统一的工具注册和加载机制，通过最小化配置实现工具的自动发现和注册。

## 核心特性

### 1. 最小化配置

只需要在租户配置文件中指定工具名称，系统会自动推导模块路径和类名：

```json
{
  "TOOLS": [
    {"name": "skill_load", "config": {...}},
    {"name": "rag_search", "config": {...}}
  ]
}
```

### 2. 自动推导规则

工具名称遵循 `snake_case` 命名约定，系统自动转换为模块路径和类名：

| 工具名称 | 自动推导的模块 | 自动推导的类 |
|---------|--------------|------------|
| `skill_load` | `apps.integrations.tool.skill_load_tool` | `SkillLoadTool` |
| `rag_search` | `apps.integrations.tool.rag_search_tool` | `RAGSearchTool` |
| `mcp_dynamic` | `apps.integrations.tool.mcp_dynamic_tool` | `McpDynamicTool` |

**转换规则**：
- 模块路径：`apps.integrations.tool.{name}_tool`
- 类名：将 `snake_case` 转换为 `CamelCase` + `Tool` 后缀

### 3. 租户隔离

工具按租户隔离注册和查询：
- 每个租户有独立的工具集合
- 支持租户特定工具和全局默认工具
- 查询时优先返回租户特定工具，未找到时回退到全局默认

## 文件结构

```
apps/integrations/tool/
├── base.py                    # BaseTool 抽象类和 ToolRegistry
├── config.py                  # ToolConfig 配置模型
├── loader_v2.py              # 统一工具加载器
├── skill_load_tool.py        # Skill 加载工具
├── rag_search_tool.py        # RAG 搜索工具
├── mcp_dynamic_tool.py       # MCP 动态工具（已存在）
└── README.md                 # 本文档
```

## 使用方法

### 1. 创建新工具

继承 `BaseTool` 并实现 `execute()` 方法：

```python
from apps.integrations.tool.base import BaseTool

class MyCustomTool(BaseTool):
    def __init__(self, tenant_id=None, config=None):
        self.name = "my_custom_tool"
        self.description = "My custom tool description"
        self.tenant_id = tenant_id
        self.config = config or {}
        self.parameters_schema = {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Input text"}
            },
            "required": ["input"]
        }
    
    async def execute(self, input_text: str, context) -> str:
        # 实现工具逻辑
        return "Result"
```

**注意**：文件名应为 `my_custom_tool.py`（与工具名称一致）

### 2. 配置工具

在租户 JSON 配置文件中添加工具：

```json
{
  "TOOLS": [
    {
      "name": "my_custom_tool",
      "enabled": true,
      "config": {
        "custom_setting": "value"
      }
    }
  ]
}
```

### 3. 启动服务

启动 Django 服务时，工具会自动加载：

```bash
SERVER_ENV=local uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --reload
```

查看日志确认工具加载：
```
Loading X tools for tenant 'example_tenant'...
Registered tool 'skill_load'
Registered tool 'rag_search'
```

### 4. 查看已注册工具

```python
from apps.integrations.tool.base import ToolRegistry

# 列出所有工具
tools = ToolRegistry.list_tools(tenant_id='example_tenant')
print(tools)  # ['rag_search', 'skill_load']

# 查看工具 schema
schemas = ToolRegistry.list_tools_with_schemas(tenant_id='example_tenant')
for schema in schemas:
    print(schema)

# 获取特定工具
tool = ToolRegistry.get_tool('skill_load', tenant_id='example_tenant')
if tool:
    print(f"Tool: {tool.name}")
    print(f"Description: {tool.description}")
```

## 内置工具

### SkillLoadTool

**用途**：按需加载技能详情供 LLM 参考

**配置**：
```json
{
  "name": "skill_load",
  "config": {
    "skills_json_path": "remote://8610893650304010371"
  }
}
```

**参数**：
- `skill_name` (必需): 要加载的技能名称

**返回**：
```json
{
  "name": "skill-name",
  "description": "Skill description",
  "content": "Full skill content in Markdown"
}
```

### RAGSearchTool

**用途**：从知识库检索相关信息

**配置**：
```json
{
  "name": "rag_search",
  "config": {
    "rag_url": "https://...",
    "bot_id": "...",
    "biz_user_id": "..."
  }
}
```

**参数**：
- `query` (必需): 搜索查询
- `top_k` (可选): 返回结果数量，默认 5

**返回**：
```
[1] Document content 1

[2] Document content 2
```

### MCPDynamicTool

**用途**：执行远程 MCP 工具

**配置**：
```json
{
  "name": "mcp_dynamic",
  "config": {
    "server_name": "example-mcp",
    "endpoint": "https://...",
    "merchant_id": "...",
    "user_id": "...",
    "wallet_id": "..."
  }
}
```

**参数**：
- `tool_name` (必需): MCP 工具名称
- `arguments` (必需): 工具参数（JSON 对象）

## 高级用法

### 禁用工具

```json
{
  "TOOLS": [
    {
      "name": "skill_load",
      "enabled": false
    }
  ]
}
```

### 工具优先级

可以通过配置调整工具的行为：

```json
{
  "TOOLS": [
    {
      "name": "rag_search",
      "config": {
        "default_top_k": 10,
        "timeout": 30
      }
    }
  ]
}
```

## 故障排查

### 工具未加载

检查日志中的错误信息：
```bash
# 查看详细日志
tail -f logs/asri.log | grep "Failed to load tool"
```

常见问题：
1. 模块路径错误：确保文件名为 `{name}_tool.py`
2. 类名错误：确保类名为 `{CamelCaseName}Tool`
3. 导入错误：确保工具类继承自 `BaseTool`

### 工具冲突

如果多个租户配置了同名工具，系统会按以下优先级查找：
1. 租户特定工具
2. 全局默认工具

## 迁移指南

### 从旧格式迁移

**旧格式**（已废弃）：
```json
{
  "MCP_SERVERS": [...]
}
```

**新格式**（推荐）：
```json
{
  "TOOLS": [
    {"name": "skill_load", "config": {"skills_json_path": "remote://8610893650304010371"}},
    {"name": "mcp_dynamic", "config": {...}}
  ]
}
```

新格式的优势：
- 统一配置方式
- 更清晰的工具管理
- 支持更多工具类型
- 更好的租户隔离

## API 参考

### ToolConfig

```python
@dataclass
class ToolConfig:
    name: str                    # 工具名称（必需）
    config: dict                 # 工具特定配置
    enabled: bool = True         # 是否启用
    
    # 自动推导字段
    module: str                  # 模块路径（自动推导）
    class_name: str              # 类名（自动推导）
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ToolConfig'
```

### ToolRegistry

```python
class ToolRegistry:
    @classmethod
    def register(cls, tool: BaseTool, tenant_id: Optional[str] = None)
    
    @classmethod
    def get_tool(cls, name: str, tenant_id: Optional[str] = None) -> BaseTool | None
    
    @classmethod
    def list_tools(cls, tenant_id: Optional[str] = None) -> list[str]
    
    @classmethod
    def list_tools_with_schemas(cls, tenant_id: Optional[str] = None) -> list[dict]
```

### BaseTool

```python
class BaseTool(ABC):
    name: str
    description: str
    parameters_schema: dict
    tenant_id: Optional[str]
    config: dict
    
    @abstractmethod
    async def execute(self, input_text: str, context) -> str
    
    def to_tool_schema(self) -> dict
```

## 总结

统一工具系统通过最小化配置和自动推导，简化了工具的注册和管理：

✅ **最小配置**：只需指定工具名称  
✅ **自动推导**：基于命名约定自动定位模块和类  
✅ **租户隔离**：支持多租户工具管理  
✅ **易于扩展**：继承 BaseTool 即可创建新工具  
✅ **向后兼容**：保留对旧格式的支持

开始使用吧！🚀

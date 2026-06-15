# Tool System

Tool is the abstraction of single-step external capabilities in ASRI. Unlike Skills (complex multi-step capabilities), Tools typically wrap single API calls or external service interactions.

---

## BaseTool Abstract Base Class

**File**: `apps/integrations/tool/base.py`

```python
class BaseTool(ABC):
    name: str = ''          # Tool name
    description: str = ''   # Tool description

    @abstractmethod
    async def execute(self, input_text: str, context: Any) -> str:
        """Execute the tool and return a result string."""
```

---

## ToolRegistry

**File**: `apps/integrations/tool/base.py`

Global tool registry (not tenant-isolated):

| Method | Signature | Description |
|------|------|------|
| `register` | `register(tool: BaseTool)` | Register a tool instance |
| `get_tool` | `get_tool(name: str) → BaseTool \| None` | Get a tool by name |
| `list_tools` | `list_tools() → list[str]` | List all tool names |

### Usage Example

```python
from apps.integrations.tool.base import ToolRegistry

# Register
ToolRegistry.register(MyTool())

# Query
tool = ToolRegistry.get_tool('mcp')
if tool:
    result = await tool.execute('get_balance:{"account":"123"}', context)
```

---

## MCPTool

**File**: `apps/integrations/tool/mcp_tool.py`

Wraps the Alipay MCP (Model Context Protocol) remote tool execution service. Automatically registers with ToolRegistry on module load.

### Input Format

```
sub_tool_name:{"arg1": "val1", "arg2": "val2"}
```

Or when there are no arguments:

```
sub_tool_name
```

### Configuration

Configured via the `TOOLS` array in the tenant configuration file, specifying `type: "mcp"`:

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

| Config | Description | Required |
|--------|------|------|
| `client_type` | Client type: `http`, `custom`, `sofa` | Yes |
| `endpoint` | MCP service base URL | Yes |
| `sse_endpoint` | SSE endpoint path | No |
| `mcp_name` | MCP service name | No |
| `timeout` | Timeout (seconds) | No |

### Request Structure

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

### Response Handling

1. Extract raw result from `data.data.content[0].text`
2. Attempt JSON parsing
3. Detect `businessCardMCPAnswer` markup for card responses
4. Set `card_response=True` in `context.metadata` for card responses

### Error Handling

| Scenario | Handling |
|------|------|
| Timeout (30s) | Return timeout prompt string |
| HTTP error | Return HTTP status code |
| JSON parse failure | Return raw text |
| Endpoint not configured | Return config missing prompt |

---

## Agent Tool Functions

**File**: `apps/agent/agent/chat_agent.py`

ChatAgent uses FunctionSchema to define tools callable by the LLM, dynamically constructed via `build_tool_schemas()` and `build_function_handlers()`.

### build_tool_schemas(context)

Builds the tool list based on AgentContext capability flags:

| Tool | Registration Condition | Parameters | Description |
|------|----------|------|------|
| `skill_load` | Always registered | `skill_name: string` | Load skill details on demand |
| `rag_search` | `context.rag_enabled` | `query: string` | Knowledge base retrieval |
| `execute_tool` | `context.available_tools` non-empty | `tool_name, tool_input: string` | Execute a registered tool |
| `execute_skill` | `context.available_skills` non-empty | `skill_name: string` | Execute a registered skill |

### build_function_handlers(executor, context)

Returns a dictionary of four async handler functions:

```python
{
    "skill_load": handle_skill_load,      # SkillRegistry.get_skill()
    "rag_search": handle_rag_search,      # ActionExecutor.execute("RAG", ...)
    "execute_tool": handle_execute_tool,  # ActionExecutor.execute("TOOL", ...)
    "execute_skill": handle_execute_skill # ActionExecutor.execute("SKILL", ...)
}
```

### Handler Processing Flow

Each handler receives `FunctionCallParams` parameters:

```python
@dataclass
class FunctionCallParams:
    function_name: str          # Function name
    tool_call_id: str           # Tool call ID
    arguments: Mapping[str, Any]  # Arguments dictionary
    result_callback: Callable     # Callback to return results
```

Handlers return results via `params.result_callback(dict)` and record execution traces in `context`.

### skill_load Handler Details

```python
async def handle_skill_load(params):
    skill_name = params.arguments.get("skill_name", "").strip()
    skill = SkillRegistry.get_skill(skill_name)  # Automatically uses current tenant

    if skill is None:
        available = SkillRegistry.list_skills()
        await params.result_callback({
            "error": f"Skill '{skill_name}' not found.",
            # Provide available skills list to help LLM correct
        })
        return

    await params.result_callback({
        "name": skill.name,
        "description": skill.description,
        "content": skill.content,  # Full content for LLM reasoning
    })
```

---

## FunctionSchema Definition

**File**: `apps/agent/pipeline/framework.py`

```python
class FunctionSchema:
    def __init__(self, name, description, properties, required=None):
        ...

    def to_default_dict(self) -> dict:
        """Convert to OpenAI function definition format."""
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

### Custom Tool Schema Example

```python
my_schema = FunctionSchema(
    name="weather_query",
    description="Query weather information for a specified city",
    properties={
        "city": {
            "type": "string",
            "description": "City name",
        },
    },
    required=["city"],
)
```

---

## ActionExecutor

**File**: `apps/agent/agent/chat_agent.py`

Action dispatcher (implemented in function_handlers), routing tool calls to specific implementations:

| Action | Dispatch Logic |
|--------|----------|
| `RAG` | `RAGRegistry.get_default_provider().search(action_input)` |
| `TOOL` | Parse `tool_name:args` → `ToolRegistry.get_tool(name).execute(args, context)` |
| `SKILL` | `SkillRegistry.get_skill(action_input).execute(action_input, context)` |

---

## Related Documentation

- Skill System → [skill-guide.md](skill-guide.md)
- Agent System → [agent-guide.md](agent-guide.md)
- Extending New Tools → [extension-guide.md](extension-guide.md)

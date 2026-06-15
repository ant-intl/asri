# LLM + RAG Provider 系统

## LLM Provider 系统

### BaseLLMProvider 抽象基类

**文件**: `apps/integrations/llm/base.py`

所有 LLM Provider 必须继承并实现以下方法：

```python
class BaseLLMProvider(ABC):
    def __init__(self, api_base='', api_key='', model_name='', **kwargs): ...

    @abstractmethod
    async def chat(
        self, messages, temperature=0.7, max_tokens=None, stream=False, **kwargs
    ) -> Dict | AsyncGenerator:
        """stream=False 返回 Dict，stream=True 返回 AsyncGenerator。"""

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """生成文本嵌入向量。"""

    @abstractmethod
    def get_provider_type(self) -> str:
        """返回 provider 类型标识符。"""

    def get_model_name(self) -> str:
        """返回模型名称。"""

    def format_messages(self, messages) -> list[dict]:
        """格式化消息（可重写）。"""
```

### chat() 返回格式

非流式 (`stream=False`)：

```python
{
    "content": "回答内容",
    "usage": {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150
    }
}
```

流式 (`stream=True`)：yield chunk dict：

```python
{"type": "content", "content": "部分文本"}
{"type": "tool_calls", "tool_calls": [...]}        # 聚合式（一次性返回所有 tool_call）
{"type": "tool_calls_delta", "tool_calls": [...]}   # 增量式
```

---

### 三种 Provider 实现

| Provider | 类型标识 | 说明 | 流式 | function_calling |
|----------|----------|------|------|------------------|
| `OpenAIProvider` | `openai` | OpenAI API 兼容 | Y | Y |
| `OllamaProvider` | `ollama` | 本地 Ollama 服务 | Y | N |
| `CustomProvider` | `custom` | 自定义 OpenAI-compatible 接口 | Y | Y |

### OpenAIProvider

**文件**: `apps/integrations/llm/openai_provider.py`

兼容 OpenAI Chat Completions API，支持流式和工具调用。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `api_base` | `https://api.openai.com/v1` | API 端点 |
| `api_key` | — | API Key |
| `model_name` | `gpt-4` | 模型名称 |
| `timeout` | `30` | 请求超时（秒） |

### OllamaProvider

**文件**: `apps/integrations/llm/ollama_provider.py`

连接本地 Ollama 服务，适用于开源模型部署。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `api_base` | `http://localhost:11434` | Ollama 服务地址 |
| `model_name` | `llama2` | 模型名称 |

### CustomProvider

**文件**: `apps/integrations/llm/custom_provider.py`

模板基类，需要子类化并实现 `chat()` 和 `embed()` 方法。适合接入任何 OpenAI Chat Completions API 兼容的模型服务。

---

### LLMRegistry

**文件**: `apps/integrations/llm/registry.py`

管理 LLM Provider 实例，支持租户级缓存。

#### 已注册的 Provider 类

```python
_provider_classes = {
    'openai': OpenAIProvider,
    'ollama': OllamaProvider,
    'custom': CustomProvider,
}
```

#### 缓存结构

```python
# {tenant_id: {cache_key: BaseLLMProvider}}
_instances = {
    None: {"default_openai": OpenAIProvider(...)},
}
```

#### 核心方法

| 方法 | 说明 |
|------|------|
| `register_provider(type, cls)` | 注册新 Provider 类型（类方法） |
| `create_provider(type, **kwargs)` | 创建 Provider 实例（类方法） |
| `get_provider(type, name, **kwargs)` | 获取或创建指定 Provider（实例方法） |
| `get_provider_from_config(tenant_id)` | 从数据库配置获取 Provider（类方法，推荐） |
| `get_provider_for_purpose(purpose, tenant_id)` | 按用途获取 Provider（类方法） |
| `clear_cache()` | 清除所有缓存实例 |

> **注意**: `get_default_provider()`, `get_provider_by_type()`, `get_provider_for_model()` 已移除。
> LLM Provider 必须通过 Admin 页面在数据库中配置，不再支持通过环境变量/配置文件兜底。

---

## RAG Provider 系统

### BaseRAGProvider 抽象基类

**文件**: `apps/integrations/rag/base.py`

```python
class BaseRAGProvider(ABC):
    def __init__(self, api_base='', api_key='', **kwargs): ...

    @abstractmethod
    async def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """检索相关文档。返回 [{content, score, metadata}]。"""

    @abstractmethod
    async def index(self, doc_id: str, content: str, metadata: dict = None) -> bool:
        """索引文档。"""

    @abstractmethod
    def get_provider_type(self) -> str:
        """返回 provider 类型标识符。"""
```

### search() 返回格式

```python
[
    {
        "content": "检索到的文档内容",
        "score": 0.95,
        "metadata": {"doc_id": "xxx", "source": "knowledge_base"}
    }
]
```

---

### RAG Provider 实现

> **注意**: 所有 RAG 功能统一通过 **Tool 系统**暴露。RAG Provider 被封装为 `RAGSearchTool`（`BaseTool` 子类），注册到 `ToolRegistry`，通过 Pipeline Agent 的 `execute_tool` 统一入口调用。详见 [Tool 系统](tool-guide.md)。

开源版目前未内置具体的 RAG Provider 实现，可按需基于 `BaseRAGProvider` 扩展（参见 [extension-guide.md](extension-guide.md)）。

---

## 相关文档

- Agent 如何使用 LLM → [agent-guide.md](agent-guide.md)
- 系统配置 → [index.md](index.md)
- 扩展新 Provider → [extension-guide.md](extension-guide.md)

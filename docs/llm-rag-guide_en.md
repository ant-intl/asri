# LLM + RAG Provider System

## LLM Provider System

### BaseLLMProvider Abstract Base Class

**File**: `apps/integrations/llm/base.py`

All LLM Providers must inherit from and implement the following methods:

```python
class BaseLLMProvider(ABC):
    def __init__(self, api_base='', api_key='', model_name='', **kwargs): ...

    @abstractmethod
    async def chat(
        self, messages, temperature=0.7, max_tokens=None, stream=False, **kwargs
    ) -> Dict | AsyncGenerator:
        """stream=False returns Dict, stream=True returns AsyncGenerator."""

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Generate text embedding vectors."""

    @abstractmethod
    def get_provider_type(self) -> str:
        """Return the provider type identifier."""

    def get_model_name(self) -> str:
        """Return the model name."""

    def format_messages(self, messages) -> list[dict]:
        """Format messages (overridable)."""
```

### chat() Return Format

Non-streaming (`stream=False`):

```python
{
    "content": "Response content",
    "usage": {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150
    }
}
```

Streaming (`stream=True`): yields chunk dict:

```python
{"type": "content", "content": "Partial text"}
{"type": "tool_calls", "tool_calls": [...]}        # Aggregated (returns all tool_calls at once)
{"type": "tool_calls_delta", "tool_calls": [...]}   # Incremental
```

---

### Three Provider Implementations

| Provider | Type Identifier | Description | Streaming | function_calling |
|----------|----------|------|------|------------------|
| `OpenAIProvider` | `openai` | OpenAI API compatible | Y | Y |
| `OllamaProvider` | `ollama` | Local Ollama service | Y | N |
| `CustomProvider` | `custom` | Custom OpenAI-compatible API | Y | Y |

### OpenAIProvider

**File**: `apps/integrations/llm/openai_provider.py`

Compatible with OpenAI Chat Completions API, supports streaming and tool calls.

| Config | Default | Description |
|--------|--------|------|
| `api_base` | `https://api.openai.com/v1` | API endpoint |
| `api_key` | — | API Key |
| `model_name` | `gpt-4` | Model name |
| `timeout` | `30` | Request timeout (seconds) |

### OllamaProvider

**File**: `apps/integrations/llm/ollama_provider.py`

Connects to a local Ollama service, suitable for open-source model deployment.

| Config | Default | Description |
|--------|--------|------|
| `api_base` | `http://localhost:11434` | Ollama service address |
| `model_name` | `llama2` | Model name |

### CustomProvider

**File**: `apps/integrations/llm/custom_provider.py`

Template base class, requires subclassing and implementing `chat()` and `embed()` methods. Suitable for connecting any OpenAI Chat Completions API-compatible model service.

---

### LLMRegistry

**File**: `apps/integrations/llm/registry.py`

Manages LLM Provider instances with tenant-level caching.

#### Registered Provider Classes

```python
_provider_classes = {
    'openai': OpenAIProvider,
    'ollama': OllamaProvider,
    'custom': CustomProvider,
}
```

#### Cache Structure

```python
# {tenant_id: {cache_key: BaseLLMProvider}}
_instances = {
    None: {"default_openai": OpenAIProvider(...)},
}
```

#### Core Methods

| Method | Description |
|------|------|
| `register_provider(type, cls)` | Register a new Provider type (class method) |
| `create_provider(type, **kwargs)` | Create a Provider instance (class method) |
| `get_provider(type, name, **kwargs)` | Get or create specified Provider (instance method) |
| `get_provider_from_config(tenant_id)` | Get Provider from database config (class method, recommended) |
| `get_provider_for_purpose(purpose, tenant_id)` | Get Provider by purpose (class method) |
| `clear_cache()` | Clear all cached instances |

> **Note**: `get_default_provider()`, `get_provider_by_type()`, `get_provider_for_model()` have been removed.
> LLM Providers must be configured in the database via the Admin page; fallback via environment variables or config files is no longer supported.

---

## RAG Provider System

### BaseRAGProvider Abstract Base Class

**File**: `apps/integrations/rag/base.py`

```python
class BaseRAGProvider(ABC):
    def __init__(self, api_base='', api_key='', **kwargs): ...

    @abstractmethod
    async def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """Retrieve relevant documents. Returns [{content, score, metadata}]."""

    @abstractmethod
    async def index(self, doc_id: str, content: str, metadata: dict = None) -> bool:
        """Index a document."""

    @abstractmethod
    def get_provider_type(self) -> str:
        """Return the provider type identifier."""
```

### search() Return Format

```python
[
    {
        "content": "Retrieved document content",
        "score": 0.95,
        "metadata": {"doc_id": "xxx", "source": "knowledge_base"}
    }
]
```

---

### RAG Provider Implementations

> **Note**: All RAG functionality is exposed through the **Tool System**. RAG Providers are wrapped as `RAGSearchTool` (a `BaseTool` subclass), registered with `ToolRegistry`, and called through the Pipeline Agent's unified `execute_tool` entry point. See [Tool System](tool-guide.md).

The open-source version does not include a built-in RAG Provider implementation. You can extend `BaseRAGProvider` as needed (see [extension-guide.md](extension-guide.md)).

---

## Related Documentation

- How the Agent uses LLM → [agent-guide.md](agent-guide.md)
- System Configuration → [index.md](index.md)
- Extending New Providers → [extension-guide.md](extension-guide.md)

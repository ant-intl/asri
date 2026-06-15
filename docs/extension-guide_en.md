# Extension Development Guide

This document provides complete steps and code examples for adding new components to ASRI subsystems.

---

## 1. Adding a New LLM Provider

### Steps

1. Create file `apps/integrations/llm/my_provider.py`
2. Inherit from `BaseLLMProvider`
3. Implement `chat()`, `embed()`, `get_provider_type()`
4. Register in `LLMRegistry`
5. Add configuration

### Code Example

```python
# apps/integrations/llm/my_provider.py
import httpx
from typing import List, Dict, Any, AsyncGenerator, Optional
from .base import BaseLLMProvider


class MyProvider(BaseLLMProvider):
    """Custom LLM Provider example."""

    def __init__(self, api_base: str, api_key: str, model_name: str, **kwargs):
        super().__init__(api_base=api_base, api_key=api_key, model_name=model_name, **kwargs)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs,
    ) -> Dict[str, Any] | AsyncGenerator:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens

        if stream:
            return self._stream_chat(headers, payload)

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.api_base}/chat", headers=headers, json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "content": data["choices"][0]["message"]["content"],
                "usage": data.get("usage", {}),
            }

    async def _stream_chat(self, headers, payload):
        payload["stream"] = True
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream("POST", f"{self.api_base}/chat",
                                      headers=headers, json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data:"):
                        # Parse SSE data
                        yield {"type": "content", "content": line[5:].strip()}

    async def embed(self, text: str) -> List[float]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.api_base}/embed",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"text": text},
            )
            resp.raise_for_status()
            return resp.json()["embedding"]

    def get_provider_type(self) -> str:
        return "my_provider"
```

### Registration

```python
# Add to apps/integrations/llm/registry.py
from .my_provider import MyProvider
LLMRegistry.register_provider('my_provider', MyProvider)
```

### Configuration

Add an LLM Provider configuration in the Admin page, or add it to tenant seed data:

```python
# backend/apps/tenant/seed.py
LLMProviderConfig.objects.create(
    tenant_id=tenant_id,
    name='My Provider',
    provider_type='my_provider',
    api_base='https://my-llm.example.com/v1',
    api_key='encrypted-key',
    model_name='my-model-v1',
    is_default=True,
    is_active=True,
)
```

---

## 2. Adding a New RAG Provider

### Steps

1. Create file `apps/integrations/rag/my_rag_provider.py`
2. Inherit from `BaseRAGProvider`
3. Implement `search()`, `index()`, `get_provider_type()`
4. Add retrieval method to `RAGRegistry`

### Code Example

```python
# apps/integrations/rag/my_rag_provider.py
import httpx
from typing import List, Dict, Any
from .base import BaseRAGProvider


class MyRAGProvider(BaseRAGProvider):
    """Custom RAG Provider example."""

    async def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.api_base}/search",
                json={"query": query, "top_k": top_k},
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            return [
                {
                    "content": r["text"],
                    "score": r.get("score", 0.0),
                    "metadata": r.get("metadata", {}),
                }
                for r in results
            ]

    async def index(self, doc_id: str, content: str, metadata: Dict = None) -> bool:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.api_base}/index",
                json={"doc_id": doc_id, "content": content, "metadata": metadata or {}},
            )
            return resp.status_code == 200

    def get_provider_type(self) -> str:
        return "my_rag"
```

### Registration

Add a retrieval method to `RAGRegistry` or use `register_provider()`.

---

## 3. Adding a New Tool

### Steps

1. Create a Tool class inheriting from `BaseTool`
2. Define `name` and `description`
3. Implement `execute(input_text, context)`
4. Register with `ToolRegistry`

### Code Example

```python
# apps/integrations/tool/weather_tool.py
import httpx
from typing import Any
from .base import BaseTool, ToolRegistry


class WeatherTool(BaseTool):
    """Tool for querying weather information."""
    name = 'weather'
    description = 'Query weather information for a specified city. Input format: city name'

    async def execute(self, input_text: str, context: Any) -> str:
        city = input_text.strip()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.weather.com/v1/current?city={city}",
            )
            if resp.status_code == 200:
                data = resp.json()
                return f"Weather in {city}: {data['weather']}, Temperature: {data['temp']}°C"
            return f"Unable to retrieve weather for {city}"

# Auto-register on module load
ToolRegistry.register(WeatherTool())
```

After registration, if `context.available_tools` contains `'weather'` in ChatAgent, the `execute_tool` function can be called by the LLM.

---

## 4. Adding a New Skill

### Method 1: Filesystem Skill (Recommended)

Create a subdirectory and `SKILL.md` file under the tenant's skill directory:

```
# Directory structure
{SKILLS_ROOT}/{tenant_id}/skills/{skill_name}/
└── SKILL.md
```

```markdown
<!-- data/tenant/my_tenant/skills/refund_process/SKILL.md -->
name: refund_process
description: Handle user refund-related issues, including process, timing, and status inquiry

## Refund Steps
1. Go to the order page
2. Select the order to refund
3. Click "Apply for Refund"
4. Fill in the refund reason
5. Wait for review (1-3 business days)
```

Once created, call the admin API to refresh skill registration for the current tenant:

```
POST /admin/skills/refresh/
X-Tenant-Id: my_tenant
```

### Method 2: Python Class (Legacy)

This method is only for programmatic integration scenarios and is not recommended for general use:

```python
# apps/integrations/skill/refund_skill.py
from typing import Any
from .base import BaseSkill, SkillRegistry


class RefundSkill(BaseSkill):
    name = 'refund_process'
    description = 'Handle user refund-related issues'

    async def execute(self, input_text: str, context: Any) -> str:
        return """
        # Refund Process
        ...
        """

# Manually register to a specific tenant
SkillRegistry.register(RefundSkill(), tenant_id='my_tenant')
```

---

## 5. Adding a New Prompt Mode

### Steps

1. Create file `apps/agent/prompts/my_prompt.py`
2. Inherit from `BaseSystemPrompt`
3. Implement `render()`, `parse_response()`, `format_user_prompt()`
4. Register in `_PROMPT_REGISTRY`

### Code Example

```python
# apps/agent/prompts/my_prompt.py
import json
from typing import Dict, Any
from .base import BaseSystemPrompt


MY_SYSTEM_PROMPT = """You are a professional customer service assistant.
Please reply in JSON format:
{{"answer": "Your answer", "confidence": 0.95, "sources": ["source1"]}}
"""


class MyPrompt(BaseSystemPrompt):
    """Custom Prompt mode."""

    def render(self, **kwargs) -> str:
        return MY_SYSTEM_PROMPT

    def parse_response(self, response: str) -> Dict[str, Any]:
        result = {'thought': '', 'action': '', 'action_input': '', 'raw': response}
        try:
            parsed = json.loads(response)
            result['action'] = 'FINISH'
            result['action_input'] = parsed.get('answer', response)
        except json.JSONDecodeError:
            result['action'] = 'FINISH'
            result['action_input'] = response.strip()
        return result

    def format_user_prompt(self, query: str, **kwargs) -> str:
        return f"User question: {query}"
```

### Registration

```python
# apps/agent/prompts/__init__.py
from .my_prompt import MyPrompt, MY_SYSTEM_PROMPT

_PROMPT_REGISTRY['my_mode'] = MyPrompt

__all__ = [..., 'MyPrompt', 'MY_SYSTEM_PROMPT']
```

### Usage

```python
# Via factory function
prompt = create_prompt('my_mode')

# Via configuration
CHATBOT = {'REACT_PROMPT_MODE': 'my_mode'}
```

---

## 6. Adding a New Agent Mode

### Steps

1. Create file `apps/agent/agent/my_agent.py`
2. Inherit from `BaseAgent`
3. Implement `run()` and `stream()`
4. Add branch in `ChatService._create_agent()`
5. Add `AGENT_MODE` configuration value

### Code Example

```python
# apps/agent/agent/my_agent.py
from typing import Dict, Any, List, AsyncGenerator
from .base import BaseAgent
from .context import AgentContext
from ...integrations.llm.base import BaseLLMProvider


class MyAgent(BaseAgent):
    """Custom Agent implementation."""

    def __init__(self, llm_provider: BaseLLMProvider, **kwargs):
        super().__init__(**kwargs)
        self.llm = llm_provider

    async def run(
        self, query: str,
        history: List[Dict[str, str]] = None,
        context: AgentContext = None,
    ) -> Dict[str, Any]:
        if context is None:
            context = AgentContext(current_query=query)

        messages = [
            {'role': 'system', 'content': 'You are a helpful assistant.'},
        ]
        if history:
            messages.extend(history)
        messages.append({'role': 'user', 'content': query})

        response = await self.llm.chat(messages)
        return {
            'answer': response['content'],
            'trace': context.trace,
            'prompt_tokens': response.get('usage', {}).get('prompt_tokens', 0),
            'completion_tokens': response.get('usage', {}).get('completion_tokens', 0),
            'total_tokens': response.get('usage', {}).get('total_tokens', 0),
            'model': self.llm.get_model_name(),
        }

    async def stream(
        self, query: str,
        history: List[Dict[str, str]] = None,
        context: AgentContext = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        # Streaming implementation
        messages = [{'role': 'user', 'content': query}]
        async for chunk in await self.llm.chat(messages, stream=True):
            text = chunk.get('content', '') if isinstance(chunk, dict) else chunk
            if text:
                yield {'type': 'token', 'content': text}
        yield {'type': 'done', 'content': ''}
```

### Usage in ChatService

```python
# apps/services/chat_service.py (refer to _create_agent implementation)
async def _create_agent(self, tenant_id: str | None = None) -> BaseAgent:
    llm = await self.llm_registry.get_provider_from_config(tenant_id)
    prompt_mode = get_chatbot_config('REACT_PROMPT_MODE', 'interleaved_thinking')
    return ChatAgent(llm_provider=llm, prompt_mode=prompt_mode, tenant_id=tenant_id)
```

### Tips

ChatAgent is the unified Agent implementation of ASRI. To customize behavior, you can:
- **Custom Prompt**: Create new PromptTemplate records in the database
- **Custom Tool/Skill**: Register new tool or skill implementations
- **Extend ChatAgent**: Subclass ChatAgent and override methods

---

## Extension Checklist

After adding a new component, ensure the following:

- [ ] Inherit from the correct abstract base class
- [ ] Implement all `@abstractmethod` methods
- [ ] Register in the corresponding Registry
- [ ] Add necessary configuration items
- [ ] Write unit tests
- [ ] Follow async/await asynchronous programming conventions
- [ ] Set timeouts for external API calls (no more than 30s)
- [ ] Do not introduce third-party packages beyond `requirements.txt`

---

## Related Documentation

- Agent System → [agent-guide.md](agent-guide.md)
- LLM/RAG Provider → [llm-rag-guide.md](llm-rag-guide.md)
- Tool System → [tool-guide.md](tool-guide.md)
- Skill System → [skill-guide.md](skill-guide.md)

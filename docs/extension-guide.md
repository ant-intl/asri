# 扩展开发指南

本文档提供在 ASRI 各子系统中新增组件的完整步骤和代码示例。

---

## 1. 添加新 LLM Provider

### 步骤

1. 创建文件 `apps/integrations/llm/my_provider.py`
2. 继承 `BaseLLMProvider`
3. 实现 `chat()`, `embed()`, `get_provider_type()`
4. 在 `LLMRegistry` 注册
5. 添加配置项

### 代码示例

```python
# apps/integrations/llm/my_provider.py
import httpx
from typing import List, Dict, Any, AsyncGenerator, Optional
from .base import BaseLLMProvider


class MyProvider(BaseLLMProvider):
    """自定义 LLM Provider 示例。"""

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
                        # 解析 SSE 数据
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

### 注册

```python
# apps/integrations/llm/registry.py 中添加
from .my_provider import MyProvider
LLMRegistry.register_provider('my_provider', MyProvider)
```

### 配置

在 Admin 页面添加 LLM Provider 配置，或在租户种子数据中添加：

```python
# backend/apps/tenant/seed.py 中
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

## 2. 添加新 RAG Provider

### 步骤

1. 创建文件 `apps/integrations/rag/my_rag_provider.py`
2. 继承 `BaseRAGProvider`
3. 实现 `search()`, `index()`, `get_provider_type()`
4. 在 `RAGRegistry` 添加获取方法

### 代码示例

```python
# apps/integrations/rag/my_rag_provider.py
import httpx
from typing import List, Dict, Any
from .base import BaseRAGProvider


class MyRAGProvider(BaseRAGProvider):
    """自定义 RAG Provider 示例。"""

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

### 注册

在 `RAGRegistry` 中添加获取方法或使用 `register_provider()`。

---

## 3. 添加新 Tool

### 步骤

1. 创建 Tool 类继承 `BaseTool`
2. 定义 `name` 和 `description`
3. 实现 `execute(input_text, context)`
4. 注册到 `ToolRegistry`

### 代码示例

```python
# apps/integrations/tool/weather_tool.py
import httpx
from typing import Any
from .base import BaseTool, ToolRegistry


class WeatherTool(BaseTool):
    """查询天气的工具。"""
    name = 'weather'
    description = '查询指定城市的天气信息。输入格式: 城市名称'

    async def execute(self, input_text: str, context: Any) -> str:
        city = input_text.strip()
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"https://api.weather.com/v1/current?city={city}",
            )
            if resp.status_code == 200:
                data = resp.json()
                return f"{city} 天气: {data['weather']}, 温度: {data['temp']}°C"
            return f"无法获取 {city} 的天气信息"

# 模块加载时自动注册
ToolRegistry.register(WeatherTool())
```

注册后，ChatAgent 中若 `context.available_tools` 包含 `'weather'`，则 `execute_tool` 函数工具可被 LLM 调用。

---

## 4. 添加新 Skill

### 方式一：文件系统 Skill（推荐）

在租户的技能目录下创建子目录和 `SKILL.md` 文件：

```
# 目录结构
{SKILLS_ROOT}/{tenant_id}/skills/{skill_name}/
└── SKILL.md
```

```markdown
<!-- data/tenant/my_tenant/skills/refund_process/SKILL.md -->
name: 退款流程
description: 处理用户退款相关问题，包括退款流程、退款时效、退款状态查询

## 退款步骤
1. 进入订单页面
2. 选择需要退款的订单
3. 点击"申请退款"
4. 填写退款原因
5. 等待审核（1-3个工作日）
```

创建完成后，调用管理 API 刷新当前租户的技能注册：

```
POST /admin/skills/refresh/
X-Tenant-Id: my_tenant
```

### 方式二：Python 类（旧接口）

这种方式仅用于程序化集成场景，不推荐日常使用：

```python
# apps/integrations/skill/refund_skill.py
from typing import Any
from .base import BaseSkill, SkillRegistry


class RefundSkill(BaseSkill):
    name = '退款流程'
    description = '处理用户退款相关问题'

    async def execute(self, input_text: str, context: Any) -> str:
        return """
        # 退款流程
        ...
        """

# 手动注册到指定租户
SkillRegistry.register(RefundSkill(), tenant_id='my_tenant')
```

---

## 5. 添加新 Prompt 模式

### 步骤

1. 创建文件 `apps/agent/prompts/my_prompt.py`
2. 继承 `BaseSystemPrompt`
3. 实现 `render()`, `parse_response()`, `format_user_prompt()`
4. 在 `_PROMPT_REGISTRY` 注册

### 代码示例

```python
# apps/agent/prompts/my_prompt.py
import json
from typing import Dict, Any
from .base import BaseSystemPrompt


MY_SYSTEM_PROMPT = """你是一个专业的客服助手。
请以 JSON 格式回复：
{{"answer": "你的回答", "confidence": 0.95, "sources": ["来源1"]}}
"""


class MyPrompt(BaseSystemPrompt):
    """自定义 Prompt 模式。"""

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
        return f"用户问题: {query}"
```

### 注册

```python
# apps/agent/prompts/__init__.py
from .my_prompt import MyPrompt, MY_SYSTEM_PROMPT

_PROMPT_REGISTRY['my_mode'] = MyPrompt

__all__ = [..., 'MyPrompt', 'MY_SYSTEM_PROMPT']
```

### 使用

```python
# 通过工厂函数
prompt = create_prompt('my_mode')

# 通过配置
CHATBOT = {'REACT_PROMPT_MODE': 'my_mode'}
```

---

## 6. 添加新 Agent 模式

### 步骤

1. 创建文件 `apps/agent/agent/my_agent.py`
2. 继承 `BaseAgent`
3. 实现 `run()` 和 `stream()`
4. 在 `ChatService._create_agent()` 添加分支
5. 添加 `AGENT_MODE` 配置值

### 代码示例

```python
# apps/agent/agent/my_agent.py
from typing import Dict, Any, List, AsyncGenerator
from .base import BaseAgent
from .context import AgentContext
from ...integrations.llm.base import BaseLLMProvider


class MyAgent(BaseAgent):
    """自定义 Agent 实现。"""

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
            {'role': 'system', 'content': '你是一个有用的助手。'},
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
        # 流式实现
        messages = [{'role': 'user', 'content': query}]
        async for chunk in await self.llm.chat(messages, stream=True):
            text = chunk.get('content', '') if isinstance(chunk, dict) else chunk
            if text:
                yield {'type': 'token', 'content': text}
        yield {'type': 'done', 'content': ''}
```

### 在 ChatService 使用

```python
# apps/services/chat_service.py (参考 _create_agent 实现)
async def _create_agent(self, tenant_id: str | None = None) -> BaseAgent:
    llm = await self.llm_registry.get_provider_from_config(tenant_id)
    prompt_mode = get_chatbot_config('REACT_PROMPT_MODE', 'interleaved_thinking')
    return ChatAgent(llm_provider=llm, prompt_mode=prompt_mode, tenant_id=tenant_id)
```

### 提示

ChatAgent 是 ASRI 的统一 Agent 实现。如需自定义行为，可以通过以下方式：
- **自定义 Prompt**: 在数据库中创建新的 PromptTemplate 记录
- **自定义 Tool/Skill**: 注册新的工具或技能实现
- **继承 ChatAgent**: 子类化 ChatAgent 并重写方法

---

## 扩展检查清单

添加新组件后，确保完成以下事项：

- [ ] 继承正确的抽象基类
- [ ] 实现所有 `@abstractmethod` 方法
- [ ] 在对应的 Registry 中注册
- [ ] 添加必要的配置项
- [ ] 编写单元测试
- [ ] 遵循 async/await 异步编程规范
- [ ] 外部 API 调用设置超时（不超过 30s）
- [ ] 不引入 `requirements.txt` 之外的第三方包

---

## 相关文档

- Agent 系统 → [agent-guide.md](agent-guide.md)
- LLM/RAG Provider → [llm-rag-guide.md](llm-rag-guide.md)
- Tool 系统 → [tool-guide.md](tool-guide.md)
- Skill 系统 → [skill-guide.md](skill-guide.md)

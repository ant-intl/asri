# 如何关闭思考模式（Thinking Mode）

## 问题说明

支持 Reasoning/Thinking 的模型（如 Qwen、DeepSeek-R1 等）默认会在输出中包含思考过程，以 `<think>...</think>` 标签包裹。ASRI 的 `interleaved_thinking` Prompt 模式会解析并展示这些标签。如果不需要显示思考过程，有以下几种关闭方式。

---

## 方法 1：通过 Prompt 模式切换

最简单的方式是将 `PromptTemplate.name` 改为 `pipeline`（原生 function_calling，无思考标签解析）或 `react`（标准文本格式）。

在 Admin 页面将租户的 Prompt 模式从 `interleaved_thinking` 改为 `pipeline`，Agent 将不再输出或解析 `<think>` 内容。

---

## 方法 2：通过 `llm_params` 传递参数（模型级关闭）

对于支持 `enable_thinking` 参数的模型，可以在调用时通过 `llm_params` 直接关闭模型端的思考输出。

### 2a：直接调用 Provider

```python
import asyncio
from apps.integrations.llm.registry import LLMRegistry

async def chat_without_thinking():
    registry = LLMRegistry()
    provider = await registry.get_provider_from_config(tenant_id=None)

    result = await provider.chat(
        messages=[
            {'role': 'system', 'content': 'You are a helpful assistant.'},
            {'role': 'user', 'content': '你好，请介绍一下自己'}
        ],
        chat_template_kwargs={
            'enable_thinking': False  # 关闭模型端思考输出
        }
    )

    print(result['content'])

asyncio.run(chat_without_thinking())
```

### 2b：通过 HTTP API

在请求体中添加 `llm_params` 字段：

```bash
curl -X POST http://localhost:8000/chatbot/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "session-123",
    "message": "你好",
    "user_id": "user-456",
    "llm_params": {
      "chat_template_kwargs": {
        "enable_thinking": false
      }
    }
  }'
```

---

## 方法 3：通过 `extractor_config` 忽略思考标签

如果模型仍然输出 `<think>` 但不希望前端展示，可在 `PromptTemplate.extractor_config` 中移除 `think_keys` 映射：

```json
{
  "extractor": {
    "type": "xml_tags",
    "default_type": "token"
  },
  "mapper": {
    "tool_keys": ["tool_call"],
    "think_keys": [],
    "answer_keys": ["answer"]
  }
}
```

`think_keys` 设为空数组后，`<think>` 标签内容将作为普通 token 流式输出，不触发思考面板。

---

## 参数说明

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `chat_template_kwargs.enable_thinking` | bool | true | 是否启用模型端思考输出 |
| `chat_template_kwargs.thinking_budget` | int | — | 思考 token 预算（部分模型支持） |

> **注意**：`enable_thinking` 仅对支持该参数的模型有效（如 Qwen3、DeepSeek-R1 等），传给不支持此参数的模型（如标准 GPT-4o）会被忽略。

---

## 验证效果

### 检查响应内容

**开启思考（默认）**：
```
<think>用户想要我介绍自己，提供简洁友好的自我介绍。</think>
你好！我是 AI 助手...
```

**关闭思考后**：
```
你好！我是 AI 助手...
```

### 开启 DEBUG 日志

```python
# config/settings/base.py 或本地覆盖
LOGGING['loggers']['apps']['level'] = 'DEBUG'
```

日志中将显示 LLM 请求 payload，可确认 `enable_thinking` 参数是否成功传递。

---

## 相关文档

- [LLM/RAG 配置指南](llm-rag-guide.md)
- [Agent 系统](agent-guide.md)

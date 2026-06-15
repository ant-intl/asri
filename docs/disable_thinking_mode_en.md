# How to Disable Thinking Mode

## Problem Description

Models that support Reasoning/Thinking (e.g., Qwen, DeepSeek-R1) output their reasoning process wrapped in `<think>...</think>` tags. ASRI's `interleaved_thinking` prompt mode parses and displays these tags. If you don't need to show the thinking process, the following methods can disable it.

---

## Method 1: Switch Prompt Mode

The simplest approach is to change the `PromptTemplate.name` to `pipeline` (native function_calling, no thinking tag parsing) or `react` (standard text format).

In the Admin page, change the tenant's Prompt mode from `interleaved_thinking` to `pipeline`. The Agent will no longer output or parse `<think>` content.

---

## Method 2: Pass Parameters via `llm_params` (Model-Level Disable)

For models that support the `enable_thinking` parameter, you can disable thinking output at the model level by passing `llm_params`.

### 2a: Direct Provider Call

```python
import asyncio
from apps.integrations.llm.registry import LLMRegistry

async def chat_without_thinking():
    registry = LLMRegistry()
    provider = await registry.get_provider_from_config(tenant_id=None)

    result = await provider.chat(
        messages=[
            {'role': 'system', 'content': 'You are a helpful assistant.'},
            {'role': 'user', 'content': 'Hello, please introduce yourself'}
        ],
        chat_template_kwargs={
            'enable_thinking': False  # Disable model-level thinking output
        }
    )

    print(result['content'])

asyncio.run(chat_without_thinking())
```

### 2b: Via HTTP API

Add the `llm_params` field to the request body:

```bash
curl -X POST http://localhost:8000/chatbot/api/chat/ \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "session-123",
    "message": "Hello",
    "user_id": "user-456",
    "llm_params": {
      "chat_template_kwargs": {
        "enable_thinking": false
      }
    }
  }'
```

---

## Method 3: Ignore Thinking Tags via `extractor_config`

If the model still outputs `<think>` but you don't want the frontend to display it, remove the `think_keys` mapping from `PromptTemplate.extractor_config`:

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

With `think_keys` set to an empty array, `<think>` tag content will be streamed as regular tokens and will not trigger the thinking panel.

---

## Parameter Reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `chat_template_kwargs.enable_thinking` | bool | true | Whether to enable model-level thinking output |
| `chat_template_kwargs.thinking_budget` | int | — | Thinking token budget (supported by some models) |

> **Note**: `enable_thinking` only works with models that support this parameter (e.g., Qwen3, DeepSeek-R1). Passing it to unsupported models (e.g., standard GPT-4o) will be ignored.

---

## Verifying the Effect

### Check Response Content

**Thinking enabled (default)**:
```
<think>The user wants me to introduce myself. I should provide a concise and friendly introduction.</think>
Hello! I am an AI assistant...
```

**Thinking disabled**:
```
Hello! I am an AI assistant...
```

### Enable DEBUG Logging

```python
# config/settings/base.py or local override
LOGGING['loggers']['apps']['level'] = 'DEBUG'
```

The logs will show the LLM request payload, confirming whether the `enable_thinking` parameter was successfully passed.

---

## Related Documentation

- [LLM/RAG Configuration Guide](llm-rag-guide_en.md)
- [Agent System](agent-guide_en.md)

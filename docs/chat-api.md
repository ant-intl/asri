# ASRI Chat API 接入文档

本文档描述 ASRI 智能对话服务的 HTTP API 接口，供外部系统接入使用。
涵盖 SSE 流式对话、Long Polling 模式、会话管理和消息历史接口。

---

## 基本信息

| 项目 | 说明 |
|------|------|
| Base URL | `https://{host}/chatbot/api/` |
| 协议 | HTTPS |
| 认证方式 | Bearer Token |
| 内容类型 | `application/json` |

---

## 认证

所有 API 请求需在 HTTP Header 中携带 Bearer Token：

```
Authorization: Bearer <your-token>
```

可选 Header：

| Header | 说明 |
|--------|------|
| `X-User-ID` | 用户标识，用于会话归属和隔离。未提供时默认为 `anonymous` |

> Token 由管理员分配，每个 Token 关联一个租户（tenant）。不同租户的数据完全隔离。

**错误响应（401）**：

```json
{"error": "Authentication required"}
```

---

## 通用响应格式

**成功**：HTTP 200/201，返回 JSON 数据。

**错误**：

```json
{"error": "错误描述信息"}
```

| HTTP 状态码 | 说明 |
|-------------|------|
| 400 | 请求参数错误（缺少必填字段、JSON 格式错误） |
| 401 | 认证失败（缺少或无效的 Bearer Token） |
| 403 | 权限不足（访问不属于自己的会话） |
| 404 | 资源不存在（会话或消息未找到） |
| 500 | 服务器内部错误 |

---

## 1. 会话管理

### 1.1 创建会话

发起对话前**必须**先创建会话。

```
POST /chatbot/api/sessions/
```

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| title | string | 否 | 会话标题 |
| user_context | object | 否 | 用户上下文信息，会注入到 Agent prompt 中 |
| external_source | string | 否 | 外部系统来源标识（如 `"dingtalk"`、`"feishu"`） |
| external_session_id | string | 否 | 外部系统的会话 ID，用于关联外部会话 |

**示例请求**

```bash
curl -X POST https://host/chatbot/api/sessions/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user_001" \
  -d '{
    "title": "咨询技术问题",
    "user_context": {"department": "engineering"},
    "external_source": "dingtalk",
    "external_session_id": "dt_session_123"
  }'
```

**Response 201**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "external_source": "dingtalk",
  "external_session_id": "dt_session_123",
  "title": "咨询技术问题",
  "status": "active",
  "metadata": {},
  "gmt_create": "2026-04-20T10:00:00.000000+08:00"
}
```

---

### 1.2 获取会话列表

```
GET /chatbot/api/sessions/
```

**Query Parameters**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| status | string | `active` | 会话状态过滤（`active` / `archived`） |
| page | int | 1 | 页码 |
| page_size | int | 20 | 每页数量 |

**Response 200**

```json
{
  "sessions": [
    {
      "session_id": "550e8400-e29b-41d4-a716-446655440000",
      "external_source": "dingtalk",
      "external_session_id": "dt_session_123",
      "title": "咨询技术问题",
      "status": "active",
      "agent_type": "pipeline",
      "gmt_create": "2026-04-20T10:00:00.000000+08:00",
      "gmt_modified": "2026-04-20T10:05:00.000000+08:00"
    }
  ],
  "total": 1,
  "page": 1,
  "page_size": 20
}
```

---

### 1.3 获取会话详情

```
GET /chatbot/api/sessions/{session_id}/
```

**Response 200**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "external_source": "dingtalk",
  "external_session_id": "dt_session_123",
  "user_id": "user_001",
  "title": "咨询技术问题",
  "status": "active",
  "agent_type": "pipeline",
  "metadata": {},
  "gmt_create": "2026-04-20T10:00:00.000000+08:00",
  "gmt_modified": "2026-04-20T10:05:00.000000+08:00"
}
```

---

### 1.4 更新会话

```
PUT /chatbot/api/sessions/{session_id}/
```

**Request Body（所有字段可选）**

| 字段 | 类型 | 说明 |
|------|------|------|
| title | string | 更新标题 |
| status | string | 更新状态（`active` / `archived`） |
| metadata | object | 更新元数据 |

**Response 200**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "新标题",
  "status": "active",
  "gmt_modified": "2026-04-20T10:10:00.000000+08:00"
}
```

---

### 1.5 删除会话

```
DELETE /chatbot/api/sessions/{session_id}/
```

**Response 200**

```json
{"success": true}
```

---

## 2. 聊天接口（SSE 流式）

### 2.1 发送消息

支持 **流式（SSE）** 和 **非流式（JSON）** 两种模式。

```
POST /chatbot/api/chat/
```

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话 ID（需先创建会话） |
| message | string | 是 | 用户消息内容 |
| user_id | string | 否 | 用户标识，默认 `"anonymous"` |
| stream | boolean | 否 | 是否启用 SSE 流式返回，默认 `false` |

---

### 2.2 非流式模式（stream=false）

**示例请求**

```bash
curl -X POST https://host/chatbot/api/chat/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "message": "帮我查一下今天的天气",
    "stream": false
  }'
```

**Response 200**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "external_session_id": "dt_session_123",
  "message_id": "msg_uuid_001",
  "content": "根据查询结果，杭州今天天气晴朗，气温25°C。",
  "trace": [
    {"type": "think", "content": "用户需要查询天气...", "timestamp": 1713585600000},
    {"type": "tool_call", "status": "calling", "tool_name": "weather", "parameters": {"city": "杭州"}, "tool_call_id": "call_abc", "timestamp": 1713585601000},
    {"type": "tool_result", "status": "success", "tool_name": "weather", "result": "杭州晴 25°C", "tool_call_id": "call_abc", "timestamp": 1713585602000}
  ],
  "usage": {}
}
```

---

### 2.3 SSE 流式模式（stream=true）

**示例请求**

```bash
curl -N -X POST https://host/chatbot/api/chat/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "message": "帮我查一下今天的天气",
    "stream": true
  }'
```

**Response HTTP Headers**

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

**Response Body（SSE 事件流）**

每个事件以 `data: ` 开头，以双换行 `\n\n` 分隔：

```
data: {"type":"think","content":"用户需要查询天气，我应该调用天气工具...","timestamp":1713585600000}

data: {"type":"tool_call","status":"calling","tool_name":"weather_query","parameters":{"city":"杭州"},"tool_call_id":"call_abc123","timestamp":1713585601000}

data: {"type":"tool_result","status":"success","tool_name":"weather_query","result":"杭州今天晴，25°C","tool_call_id":"call_abc123","timestamp":1713585602000}

data: {"type":"answer","content":"根据","timestamp":1713585603000}

data: {"type":"answer","content":"查询结果，","timestamp":1713585603100}

data: {"type":"answer","content":"杭州今天天气晴朗，气温25°C。","timestamp":1713585603200}

data: {"type":"done","content":"","message_id":"msg_uuid_001","trace":[...],"metadata":{}}

data: [DONE]
```

> **最终回复内容** = 所有 `type=answer` 的 `content` 拼接。
> 收到 `data: [DONE]` 表示流结束，客户端应关闭连接。

---

### 2.4 SSE 事件类型详解

| type | 说明 | 关键字段 |
|------|------|----------|
| `think` | Agent 内部推理/思考过程 | `content` |
| `tool_call` | 开始调用外部工具 | `tool_name`, `parameters`, `tool_call_id`, `status` |
| `tool_result` | 工具调用返回结果 | `tool_name`, `result`, `status`, `tool_call_id` |
| `answer` | AI 回复的 token 片段（增量拼接） | `content` |
| `llm_start` | LLM 请求开始 | `model`, `provider` |
| `llm_end` | LLM 请求结束 | `duration_ms`, `prompt_tokens`, `completion_tokens` |
| `done` | 流结束标记 | `message_id`, `trace` |
| `error` | 错误 | `content`（错误描述） |

**各 chunk 结构：**

```jsonc
// think - Agent 思考过程（可选展示给用户）
{"type": "think", "content": "思考内容...", "timestamp": 1713585600000}

// tool_call - 工具调用开始
{
  "type": "tool_call",
  "status": "calling",
  "tool_name": "weather_query",
  "parameters": {"city": "杭州"},
  "tool_call_id": "call_abc123",
  "timestamp": 1713585601000
}

// tool_result - 工具调用结果
{
  "type": "tool_result",
  "status": "success",            // success | error | timeout | cancelled
  "tool_name": "weather_query",
  "result": "杭州今天晴，25°C",
  "tool_call_id": "call_abc123",
  "error_message": "",            // 仅 status=error 时有值
  "timestamp": 1713585602000
}

// answer - AI 回复 token（增量）
{"type": "answer", "content": "部分文本", "timestamp": 1713585603000}

// llm_start - LLM 调用开始（可用于展示"正在思考"）
{"type": "llm_start", "llm_id": "llm_1", "model": "gpt-4", "provider": "openai", "timestamp": 1713585600000}

// llm_end - LLM 调用结束（含 token 用量）
{
  "type": "llm_end",
  "llm_id": "llm_1",
  "duration_ms": 2500,
  "prompt_tokens": 1200,
  "completion_tokens": 350,
  "total_tokens": 1550,
  "timestamp": 1713585603000
}

// done - 流结束
{
  "type": "done",
  "content": "",
  "message_id": "msg_uuid_001",
  "trace": [...],               // 完整执行追踪数组
  "metadata": {}
}
```

---

### 2.5 打断正在生成的回复

当 AI 正在流式输出时，可以发送打断请求终止当前生成。

```
POST /chatbot/api/chat/interrupt/
```

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 要打断的会话 ID |
| interrupt_message | string | 否 | 打断时附带的消息 |

**Response 200**

```json
{
  "interrupted": true,
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "external_session_id": "dt_session_123"
}
```

---

### 2.6 批量消息（多问一答）

一次发送多条消息，AI 综合处理后返回一个回复。

```
POST /chatbot/api/chat/batch/
```

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话 ID |
| messages | string[] | 是 | 多条用户消息数组 |
| user_id | string | 否 | 用户标识 |
| group_id | string | 否 | 消息分组 ID，不传则自动生成 |

**Response 200**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "external_session_id": "dt_session_123",
  "group_id": "batch_001",
  "message_id": "msg_uuid_002",
  "content": "关于你的两个问题：...",
  "trace": [],
  "usage": {}
}
```

---

## 3. Long Polling 模式

对于**不支持 SSE** 的客户端环境（如部分移动端 SDK、企业内网代理），提供 HTTP Long Polling 方式实现流式效果。

### 3.1 交互流程

```
客户端                                    服务端
  │                                         │
  │──── POST /poll/chat/init/ ─────────────>│  发送消息，启动后台任务
  │<─── {user_message_id, status} ──────────│
  │                                         │
  │──── POST /poll/chat/chunks/ ───────────>│  轮询（阻塞等待最多30s）
  │<─── {chunks: [...], offset, status} ────│
  │                                         │
  │──── POST /poll/chat/chunks/ ───────────>│  继续轮询（传入 last_offset）
  │<─── {chunks: [...], offset, status} ────│
  │                                         │
  │     ... 循环直到 status="done" ...       │
```

---

### 3.2 初始化轮询任务

```
POST /chatbot/api/poll/chat/init/
```

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| session_id | string | 是 | 会话 ID |
| message | string | 是 | 用户消息 |
| user_id | string | 否 | 用户标识 |

**Response 200**

```json
{
  "user_message_id": "msg_uuid_user_001",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "external_session_id": "dt_session_123",
  "status": "running"
}
```

---

### 3.3 轮询获取 Chunk

循环调用此接口获取增量数据。服务端采用 **long polling** 机制 —— 无新数据时请求阻塞等待（最多 `timeout` 秒），有新数据立即返回。

```
POST /chatbot/api/poll/chat/chunks/
```

**Request Body**

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| user_message_id | string | 是 | 初始化返回的 `user_message_id` |
| last_offset | int | 否 | 上次响应中的 `offset` 值，默认 0 |
| timeout | int | 否 | 最大阻塞等待秒数，默认 30 |

**Response 200**

```json
{
  "user_message_id": "msg_uuid_user_001",
  "status": "running",
  "offset": 5,
  "chunks": [
    {"type": "answer", "content": "根据", "timestamp": 1713585603000},
    {"type": "answer", "content": "查询结果", "timestamp": 1713585603100}
  ]
}
```

**status 取值：**

| 值 | 说明 | 客户端行为 |
|----|------|-----------|
| `running` | 任务进行中 | 继续轮询 |
| `done` | 任务完成 | 停止轮询 |
| `error` | 任务出错 | 停止轮询，展示错误 |

**任务完成时的响应：**

```json
{
  "user_message_id": "msg_uuid_user_001",
  "status": "done",
  "offset": 10,
  "chunks": [],
  "trace": [...],
  "assistant_message_id": "msg_uuid_assistant_001"
}
```

**超时无新数据时的响应：**

```json
{
  "user_message_id": "msg_uuid_user_001",
  "status": "running",
  "offset": 5,
  "chunks": []
}
```

> `chunks` 数组中每个元素的结构与 SSE 模式的 chunk 完全相同（参见 2.4 节）。

---

### 3.4 取消轮询任务

```
POST /chatbot/api/poll/chat/cancel/{user_message_id}/
```

**Response 200**

```json
{
  "user_message_id": "msg_uuid_user_001",
  "cancelled": true
}
```

---

## 4. 消息历史

### 4.1 获取会话消息列表

```
GET /chatbot/api/sessions/{session_id}/messages/
```

**Query Parameters**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| page | int | 1 | 页码 |
| page_size | int | 50 | 每页数量 |

**Response 200**

```json
{
  "messages": [
    {
      "message_id": "msg_uuid_user_001",
      "role": "user",
      "content": "帮我查一下天气",
      "message_type": "text",
      "parent_message_id": null,
      "group_id": null,
      "token_count": 10,
      "metadata": {},
      "gmt_create": "2026-04-20T10:00:00.000000+08:00"
    },
    {
      "message_id": "msg_uuid_assistant_001",
      "role": "assistant",
      "content": "杭州今天天气晴朗，气温25°C。",
      "message_type": "text",
      "parent_message_id": "msg_uuid_user_001",
      "group_id": null,
      "token_count": 25,
      "metadata": {
        "stream_status": "completed",
        "trace": [...]
      },
      "gmt_create": "2026-04-20T10:00:05.000000+08:00"
    }
  ],
  "total": 2,
  "page": 1,
  "page_size": 50
}
```

---

### 4.2 获取单条消息详情

```
GET /chatbot/api/messages/{message_id}/
```

**Response 200**

```json
{
  "message_id": "msg_uuid_assistant_001",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "role": "assistant",
  "content": "杭州今天天气晴朗，气温25°C。",
  "message_type": "text",
  "parent_message_id": "msg_uuid_user_001",
  "group_id": null,
  "token_count": 25,
  "metadata": {"stream_status": "completed", "trace": [...]},
  "gmt_create": "2026-04-20T10:00:05.000000+08:00"
}
```

---

### 4.3 删除消息

```
DELETE /chatbot/api/messages/{message_id}/
```

**Response 200**

```json
{"success": true}
```

---

## 5. 接入示例

### Python - SSE 流式

```python
import requests
import json

BASE_URL = "https://your-host/chatbot/api"
HEADERS = {
    "Authorization": "Bearer <your-token>",
    "Content-Type": "application/json",
    "X-User-ID": "user_001",
}

# 1. 创建会话
resp = requests.post(f"{BASE_URL}/sessions/", headers=HEADERS, json={
    "title": "测试会话",
    "external_source": "my_app",
    "external_session_id": "ext_123",
})
session_id = resp.json()["session_id"]

# 2. 发送消息（SSE 流式）
resp = requests.post(
    f"{BASE_URL}/chat/",
    headers=HEADERS,
    json={"session_id": session_id, "message": "你好", "stream": True},
    stream=True,
)

full_answer = ""
for line in resp.iter_lines(decode_unicode=True):
    if not line or not line.startswith("data: "):
        continue
    data = line[6:]
    if data == "[DONE]":
        break

    chunk = json.loads(data)
    if chunk["type"] == "answer":
        full_answer += chunk["content"]
        print(chunk["content"], end="", flush=True)
    elif chunk["type"] == "done":
        print(f"\n\nMessage ID: {chunk['message_id']}")

print(f"\n完整回复: {full_answer}")
```

### Python - Long Polling

```python
import requests
import json

BASE_URL = "https://your-host/chatbot/api"
HEADERS = {
    "Authorization": "Bearer <your-token>",
    "Content-Type": "application/json",
}

session_id = "<your-session-id>"

# 1. 初始化
resp = requests.post(f"{BASE_URL}/poll/chat/init/", headers=HEADERS, json={
    "session_id": session_id,
    "message": "你好",
})
task = resp.json()
user_message_id = task["user_message_id"]
last_offset = 0

# 2. 轮询
full_answer = ""
while True:
    resp = requests.post(f"{BASE_URL}/poll/chat/chunks/", headers=HEADERS, json={
        "user_message_id": user_message_id,
        "last_offset": last_offset,
        "timeout": 30,
    })
    result = resp.json()

    for chunk in result["chunks"]:
        if chunk["type"] == "answer":
            full_answer += chunk["content"]
            print(chunk["content"], end="", flush=True)

    last_offset = result["offset"]

    if result["status"] in ("done", "error"):
        if result["status"] == "error":
            print(f"\n错误: {result.get('error', 'unknown')}")
        break

print(f"\n完整回复: {full_answer}")
```

### JavaScript - SSE 流式（fetch）

```javascript
const BASE_URL = "https://your-host/chatbot/api";
const TOKEN = "your-bearer-token";

async function streamChat(sessionId, message) {
  const response = await fetch(`${BASE_URL}/chat/`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      session_id: sessionId,
      message: message,
      stream: true,
    }),
  });

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let fullAnswer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop(); // 保留未完成的行

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const data = line.slice(6);
      if (data === "[DONE]") return fullAnswer;

      const chunk = JSON.parse(data);
      switch (chunk.type) {
        case "answer":
          fullAnswer += chunk.content;
          // 实时更新 UI
          break;
        case "think":
          // 展示思考过程（可选）
          break;
        case "tool_call":
          // 展示工具调用状态
          break;
        case "tool_result":
          // 展示工具结果
          break;
        case "done":
          // 流结束，chunk.message_id 为助手消息 ID
          break;
      }
    }
  }
  return fullAnswer;
}
```

---

## 6. 接口端点汇总

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chatbot/api/sessions/` | 创建会话 |
| GET | `/chatbot/api/sessions/` | 会话列表 |
| GET | `/chatbot/api/sessions/{session_id}/` | 会话详情 |
| PUT | `/chatbot/api/sessions/{session_id}/` | 更新会话 |
| DELETE | `/chatbot/api/sessions/{session_id}/` | 删除会话 |
| POST | `/chatbot/api/chat/` | 发送消息（SSE 流式 / 非流式） |
| POST | `/chatbot/api/chat/interrupt/` | 打断正在生成的回复 |
| POST | `/chatbot/api/chat/batch/` | 批量消息（多问一答） |
| POST | `/chatbot/api/poll/chat/init/` | Long Polling - 初始化 |
| POST | `/chatbot/api/poll/chat/chunks/` | Long Polling - 获取增量数据 |
| POST | `/chatbot/api/poll/chat/cancel/{user_message_id}/` | Long Polling - 取消 |
| GET | `/chatbot/api/sessions/{session_id}/messages/` | 消息历史 |
| GET | `/chatbot/api/messages/{message_id}/` | 消息详情 |
| DELETE | `/chatbot/api/messages/{message_id}/` | 删除消息 |

---

## 7. 注意事项

1. **会话必须先创建**：所有聊天接口都要求传入 `session_id`，不会自动创建会话。
2. **会话复用**：同一个 `session_id` 下的多次对话共享上下文记忆。如需开始新话题，请创建新会话。
3. **并发限制**：同一会话同一时刻只能有一个进行中的 AI 生成请求。如需终止当前生成，使用打断接口。
4. **超时建议**：
   - SSE 流式连接客户端超时建议设为 **120 秒**
   - Long Polling 单次 `/chunks/` 请求最长 **30 秒**
5. **重连恢复**：SSE 连接意外断开后，可通过消息历史接口获取已生成的内容，无需重发。
6. **外部会话关联**：通过 `external_source` + `external_session_id` 可在两个系统间关联会话，便于查询和追踪。

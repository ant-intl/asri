# ASRI Chat API Integration Guide

This document describes the HTTP API interfaces of the ASRI conversational AI service for external system integration.
It covers SSE streaming chat, Long Polling mode, session management, and message history APIs.

---

## Basic Information

| Item | Description |
|------|-------------|
| Base URL | `https://{host}/chatbot/api/` |
| Protocol | HTTPS |
| Authentication | Bearer Token |
| Content Type | `application/json` |

---

## Authentication

All API requests must include a Bearer Token in the HTTP Header:

```
Authorization: Bearer <your-token>
```

Optional Headers:

| Header | Description |
|--------|-------------|
| `X-User-ID` | User identifier for session ownership and isolation. Defaults to `anonymous` |

> Tokens are assigned by the administrator. Each token is associated with a tenant. Data from different tenants is fully isolated.

**Error Response (401)**:

```json
{"error": "Authentication required"}
```

---

## Common Response Format

**Success**: HTTP 200/201, returns JSON data.

**Error**:

```json
{"error": "Error description"}
```

| HTTP Status | Description |
|-------------|-------------|
| 400 | Bad request (missing required fields, invalid JSON) |
| 401 | Authentication failed (missing or invalid Bearer Token) |
| 403 | Insufficient permissions (accessing a session not owned by the user) |
| 404 | Resource not found (session or message not found) |
| 500 | Internal server error |

---

## 1. Session Management

### 1.1 Create Session

A session **must** be created before starting a conversation.

```
POST /chatbot/api/sessions/
```

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| title | string | No | Session title |
| user_context | object | No | User context information, injected into the Agent prompt |
| external_source | string | No | External system source identifier (e.g., `"dingtalk"`, `"feishu"`) |
| external_session_id | string | No | External system session ID for association |

**Example Request**

```bash
curl -X POST https://host/chatbot/api/sessions/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -H "X-User-ID: user_001" \
  -d '{
    "title": "Technical Inquiry",
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
  "title": "Technical Inquiry",
  "status": "active",
  "metadata": {},
  "gmt_create": "2026-04-20T10:00:00.000000+08:00"
}
```

---

### 1.2 List Sessions

```
GET /chatbot/api/sessions/
```

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| status | string | `active` | Session status filter (`active` / `archived`) |
| page | int | 1 | Page number |
| page_size | int | 20 | Items per page |

**Response 200**

```json
{
  "sessions": [
    {
      "session_id": "550e8400-e29b-41d4-a716-446655440000",
      "external_source": "dingtalk",
      "external_session_id": "dt_session_123",
      "title": "Technical Inquiry",
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

### 1.3 Get Session Details

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
  "title": "Technical Inquiry",
  "status": "active",
  "agent_type": "pipeline",
  "metadata": {},
  "gmt_create": "2026-04-20T10:00:00.000000+08:00",
  "gmt_modified": "2026-04-20T10:05:00.000000+08:00"
}
```

---

### 1.4 Update Session

```
PUT /chatbot/api/sessions/{session_id}/
```

**Request Body (all fields optional)**

| Field | Type | Description |
|-------|------|-------------|
| title | string | Update title |
| status | string | Update status (`active` / `archived`) |
| metadata | object | Update metadata |

**Response 200**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "title": "New Title",
  "status": "active",
  "gmt_modified": "2026-04-20T10:10:00.000000+08:00"
}
```

---

### 1.5 Delete Session

```
DELETE /chatbot/api/sessions/{session_id}/
```

**Response 200**

```json
{"success": true}
```

---

## 2. Chat API (SSE Streaming)

### 2.1 Send Message

Supports both **streaming (SSE)** and **non-streaming (JSON)** modes.

```
POST /chatbot/api/chat/
```

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| session_id | string | Yes | Session ID (must be created first) |
| message | string | Yes | User message content |
| user_id | string | No | User identifier, defaults to `"anonymous"` |
| stream | boolean | No | Enable SSE streaming, defaults to `false` |

---

### 2.2 Non-Streaming Mode (stream=false)

**Example Request**

```bash
curl -X POST https://host/chatbot/api/chat/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "message": "What is the weather today?",
    "stream": false
  }'
```

**Response 200**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "external_session_id": "dt_session_123",
  "message_id": "msg_uuid_001",
  "content": "According to the search results, Hangzhou is sunny today with a temperature of 25°C.",
  "trace": [
    {"type": "think", "content": "User wants to check the weather...", "timestamp": 1713585600000},
    {"type": "tool_call", "status": "calling", "tool_name": "weather", "parameters": {"city": "Hangzhou"}, "tool_call_id": "call_abc", "timestamp": 1713585601000},
    {"type": "tool_result", "status": "success", "tool_name": "weather", "result": "Hangzhou Sunny 25°C", "tool_call_id": "call_abc", "timestamp": 1713585602000}
  ],
  "usage": {}
}
```

---

### 2.3 SSE Streaming Mode (stream=true)

**Example Request**

```bash
curl -N -X POST https://host/chatbot/api/chat/ \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "message": "What is the weather today?",
    "stream": true
  }'
```

**Response HTTP Headers**

```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

**Response Body (SSE Event Stream)**

Each event starts with `data: ` and is separated by double newlines `\n\n`:

```
data: {"type":"think","content":"User wants to check the weather, I should call the weather tool...","timestamp":1713585600000}

data: {"type":"tool_call","status":"calling","tool_name":"weather_query","parameters":{"city":"Hangzhou"},"tool_call_id":"call_abc123","timestamp":1713585601000}

data: {"type":"tool_result","status":"success","tool_name":"weather_query","result":"Hangzhou is sunny today, 25°C","tool_call_id":"call_abc123","timestamp":1713585602000}

data: {"type":"answer","content":"According","timestamp":1713585603000}

data: {"type":"answer","content":"to the search","timestamp":1713585603100}

data: {"type":"answer","content":"results, Hangzhou is sunny today at 25°C.","timestamp":1713585603200}

data: {"type":"done","content":"","message_id":"msg_uuid_001","trace":[...],"metadata":{}}

data: [DONE]
```

> **Final reply content** = concatenation of all `type=answer` `content` fields.
> Receiving `data: [DONE]` indicates the stream has ended; the client should close the connection.

---

### 2.4 SSE Event Types

| type | Description | Key Fields |
|------|-------------|------------|
| `think` | Agent internal reasoning/thinking process | `content` |
| `tool_call` | External tool invocation started | `tool_name`, `parameters`, `tool_call_id`, `status` |
| `tool_result` | Tool execution result returned | `tool_name`, `result`, `status`, `tool_call_id` |
| `answer` | AI reply token fragment (incremental concatenation) | `content` |
| `llm_start` | LLM request started | `model`, `provider` |
| `llm_end` | LLM request ended | `duration_ms`, `prompt_tokens`, `completion_tokens` |
| `done` | Stream end marker | `message_id`, `trace` |
| `error` | Error | `content` (error description) |

**Chunk Structures:**

```jsonc
// think - Agent thinking process (optionally displayed to user)
{"type": "think", "content": "Thinking content...", "timestamp": 1713585600000}

// tool_call - Tool invocation start
{
  "type": "tool_call",
  "status": "calling",
  "tool_name": "weather_query",
  "parameters": {"city": "Hangzhou"},
  "tool_call_id": "call_abc123",
  "timestamp": 1713585601000
}

// tool_result - Tool invocation result
{
  "type": "tool_result",
  "status": "success",            // success | error | timeout | cancelled
  "tool_name": "weather_query",
  "result": "Hangzhou is sunny today, 25°C",
  "tool_call_id": "call_abc123",
  "error_message": "",            // Only present when status=error
  "timestamp": 1713585602000
}

// answer - AI reply token (incremental)
{"type": "answer", "content": "Partial text", "timestamp": 1713585603000}

// llm_start - LLM call started (useful for showing "thinking...")
{"type": "llm_start", "llm_id": "llm_1", "model": "gpt-4", "provider": "openai", "timestamp": 1713585600000}

// llm_end - LLM call ended (with token usage)
{
  "type": "llm_end",
  "llm_id": "llm_1",
  "duration_ms": 2500,
  "prompt_tokens": 1200,
  "completion_tokens": 350,
  "total_tokens": 1550,
  "timestamp": 1713585603000
}

// done - Stream ended
{
  "type": "done",
  "content": "",
  "message_id": "msg_uuid_001",
  "trace": [...],               // Complete execution trace array
  "metadata": {}
}
```

---

### 2.5 Interrupting a Response

When the AI is streaming output, you can send an interrupt request to terminate the generation.

```
POST /chatbot/api/chat/interrupt/
```

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| session_id | string | Yes | Session ID to interrupt |
| interrupt_message | string | No | Message to accompany the interrupt |

**Response 200**

```json
{
  "interrupted": true,
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "external_session_id": "dt_session_123"
}
```

---

### 2.6 Batch Messages (Multi-query Single Answer)

Send multiple messages at once; the AI processes them together and returns a single reply.

```
POST /chatbot/api/chat/batch/
```

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| session_id | string | Yes | Session ID |
| messages | string[] | Yes | Array of user messages |
| user_id | string | No | User identifier |
| group_id | string | No | Message group ID, auto-generated if not provided |

**Response 200**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "external_session_id": "dt_session_123",
  "group_id": "batch_001",
  "message_id": "msg_uuid_002",
  "content": "Regarding your two questions: ...",
  "trace": [],
  "usage": {}
}
```

---

## 3. Long Polling Mode

For client environments that **do not support SSE** (e.g., some mobile SDKs, enterprise intranet proxies), HTTP Long Polling provides streaming-like functionality.

### 3.1 Interaction Flow

```
Client                                    Server
  │                                         │
  │──── POST /poll/chat/init/ ─────────────>│  Send message, start background task
  │<─── {user_message_id, status} ──────────│
  │                                         │
  │──── POST /poll/chat/chunks/ ───────────>│  Poll (blocking wait up to 30s)
  │<─── {chunks: [...], offset, status} ────│
  │                                         │
  │──── POST /poll/chat/chunks/ ───────────>│  Continue polling (pass last_offset)
  │<─── {chunks: [...], offset, status} ────│
  │                                         │
  │     ... loop until status="done" ...     │
```

---

### 3.2 Initialize Polling Task

```
POST /chatbot/api/poll/chat/init/
```

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| session_id | string | Yes | Session ID |
| message | string | Yes | User message |
| user_id | string | No | User identifier |

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

### 3.3 Poll for Chunks

Call this endpoint in a loop to get incremental data. The server uses **long polling** — when no new data is available, the request blocks until data arrives (up to `timeout` seconds).

```
POST /chatbot/api/poll/chat/chunks/
```

**Request Body**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| user_message_id | string | Yes | `user_message_id` returned from init |
| last_offset | int | No | `offset` value from last response, defaults to 0 |
| timeout | int | No | Maximum blocking wait in seconds, defaults to 30 |

**Response 200**

```json
{
  "user_message_id": "msg_uuid_user_001",
  "status": "running",
  "offset": 5,
  "chunks": [
    {"type": "answer", "content": "According", "timestamp": 1713585603000},
    {"type": "answer", "content": "to the search", "timestamp": 1713585603100}
  ]
}
```

**status values:**

| Value | Description | Client Behavior |
|-------|-------------|-----------------|
| `running` | Task in progress | Continue polling |
| `done` | Task completed | Stop polling |
| `error` | Task failed | Stop polling, show error |

**Response when task completes:**

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

**Response on timeout with no new data:**

```json
{
  "user_message_id": "msg_uuid_user_001",
  "status": "running",
  "offset": 5,
  "chunks": []
}
```

> The structure of each element in the `chunks` array is identical to the SSE chunk format (see Section 2.4).

---

### 3.4 Cancel Polling Task

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

## 4. Message History

### 4.1 List Session Messages

```
GET /chatbot/api/sessions/{session_id}/messages/
```

**Query Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| page | int | 1 | Page number |
| page_size | int | 50 | Items per page |

**Response 200**

```json
{
  "messages": [
    {
      "message_id": "msg_uuid_user_001",
      "role": "user",
      "content": "Check the weather",
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
      "content": "Hangzhou is sunny today at 25°C.",
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

### 4.2 Get Single Message

```
GET /chatbot/api/messages/{message_id}/
```

**Response 200**

```json
{
  "message_id": "msg_uuid_assistant_001",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "role": "assistant",
  "content": "Hangzhou is sunny today at 25°C.",
  "message_type": "text",
  "parent_message_id": "msg_uuid_user_001",
  "group_id": null,
  "token_count": 25,
  "metadata": {"stream_status": "completed", "trace": [...]},
  "gmt_create": "2026-04-20T10:00:05.000000+08:00"
}
```

---

### 4.3 Delete Message

```
DELETE /chatbot/api/messages/{message_id}/
```

**Response 200**

```json
{"success": true}
```

---

## 5. Integration Examples

### Python - SSE Streaming

```python
import requests
import json

BASE_URL = "https://your-host/chatbot/api"
HEADERS = {
    "Authorization": "Bearer <your-token>",
    "Content-Type": "application/json",
    "X-User-ID": "user_001",
}

# 1. Create session
resp = requests.post(f"{BASE_URL}/sessions/", headers=HEADERS, json={
    "title": "Test Session",
    "external_source": "my_app",
    "external_session_id": "ext_123",
})
session_id = resp.json()["session_id"]

# 2. Send message (SSE streaming)
resp = requests.post(
    f"{BASE_URL}/chat/",
    headers=HEADERS,
    json={"session_id": session_id, "message": "Hello", "stream": True},
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

print(f"\nFull reply: {full_answer}")
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

# 1. Initialize
resp = requests.post(f"{BASE_URL}/poll/chat/init/", headers=HEADERS, json={
    "session_id": session_id,
    "message": "Hello",
})
task = resp.json()
user_message_id = task["user_message_id"]
last_offset = 0

# 2. Poll
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
            print(f"\nError: {result.get('error', 'unknown')}")
        break

print(f"\nFull reply: {full_answer}")
```

### JavaScript - SSE Streaming (fetch)

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
    buffer = lines.pop(); // Keep incomplete line

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const data = line.slice(6);
      if (data === "[DONE]") return fullAnswer;

      const chunk = JSON.parse(data);
      switch (chunk.type) {
        case "answer":
          fullAnswer += chunk.content;
          // Update UI in real-time
          break;
        case "think":
          // Display thinking process (optional)
          break;
        case "tool_call":
          // Display tool call status
          break;
        case "tool_result":
          // Display tool result
          break;
        case "done":
          // Stream ended, chunk.message_id is the assistant message ID
          break;
      }
    }
  }
  return fullAnswer;
}
```

---

## 6. API Endpoint Summary

| Method | Path | Description |
|--------|------|-------------|
| POST | `/chatbot/api/sessions/` | Create session |
| GET | `/chatbot/api/sessions/` | List sessions |
| GET | `/chatbot/api/sessions/{session_id}/` | Session details |
| PUT | `/chatbot/api/sessions/{session_id}/` | Update session |
| DELETE | `/chatbot/api/sessions/{session_id}/` | Delete session |
| POST | `/chatbot/api/chat/` | Send message (SSE streaming / non-streaming) |
| POST | `/chatbot/api/chat/interrupt/` | Interrupt ongoing generation |
| POST | `/chatbot/api/chat/batch/` | Batch messages (multi-query single answer) |
| POST | `/chatbot/api/poll/chat/init/` | Long Polling - Initialize |
| POST | `/chatbot/api/poll/chat/chunks/` | Long Polling - Get incremental data |
| POST | `/chatbot/api/poll/chat/cancel/{user_message_id}/` | Long Polling - Cancel |
| GET | `/chatbot/api/sessions/{session_id}/messages/` | Message history |
| GET | `/chatbot/api/messages/{message_id}/` | Message details |
| DELETE | `/chatbot/api/messages/{message_id}/` | Delete message |

---

## 7. Notes

1. **Session must be created first**: All chat endpoints require a `session_id`; sessions are not auto-created.
2. **Session reuse**: Multiple conversations under the same `session_id` share context memory. Create a new session for a new topic.
3. **Concurrency limit**: Only one active AI generation request per session at a time. Use the interrupt endpoint to stop ongoing generation.
4. **Timeout recommendations**:
   - SSE streaming client timeout: **120 seconds**
   - Long Polling single `/chunks/` request: max **30 seconds**
5. **Reconnection recovery**: If an SSE connection drops unexpectedly, use the message history API to retrieve generated content without resending.
6. **External session association**: Use `external_source` + `external_session_id` to associate sessions between systems for easy lookup and tracking.

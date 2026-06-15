// Chat related types

// Chat request
export interface ChatRequest {
  session_id: string;
  message: string;
  user_id?: string;
  stream?: boolean;
  snapshot_id?: string;
  llm_params?: Record<string, unknown>;
  interrupt_message?: string;
  config?: Record<string, unknown>;
}

// Chat response (non-streaming)
export interface ChatResponse {
  session_id: string;
  message_id: string;
  content: string;
  trace?: TraceItem[];
  usage?: TokenUsage;
}

// Trace item types (from new API)
// Support both 'thinking' and 'think' for compatibility
// Include 'answer' for filtering purposes (not displayed)
// llm_start/llm_end for LLM call tracing
export type TraceType = 'thinking' | 'think' | 'llm_start' | 'llm_end' | 'tool_call' | 'tool_result' | 'answer';

// WebSocket / SSE message types
export type WebSocketMessageType =
  | 'connected'
  | 'ack'
  | 'token'
  | 'answer'
  | 'think'
  | 'thinking'
  | 'tool_call'
  | 'tool_result'
  | 'llm_start'
  | 'llm_end'
  | 'card'
  | 'done'
  | 'error'
  | 'stopped'
  | 'interrupted'
  | 'tool_confirm_request'
  | 'tool_confirm_response';

export interface TraceItem {
  type: TraceType;
  timestamp: number;
  // thinking type
  content?: string;
  // llm_start type
  llm_id?: string;
  model?: string;
  provider?: string;
  // llm_end type
  duration_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cached_tokens?: number;
  finish_reason?: string;
  // tool_call/tool_result type
  status?: 'calling' | 'success' | 'error';
  tool_name?: string;
  parameters?: Record<string, unknown>;
  tool_call_id?: string;
  result?: unknown;
}

// Token usage
export interface TokenUsage {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cached_tokens?: number;
}

// Streaming response chunk (SSE)
// Support both 'thinking' and 'think' for compatibility
export interface StreamChunk {
  type: 'thinking' | 'think' | 'llm_start' | 'llm_end' | 'tool_call' | 'tool_result' | 'answer' | 'card' | 'done' | 'error';
  content?: string;
  timestamp?: number;
  card_data?: Record<string, unknown>;
  // llm fields
  llm_id?: string;
  model?: string;
  provider?: string;
  duration_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cached_tokens?: number;
  finish_reason?: string;
  // tool_call/tool_result fields
  status?: 'calling' | 'success' | 'error';
  tool_name?: string;
  parameters?: Record<string, unknown>;
  tool_call_id?: string;
  result?: unknown;
}

// WebSocket message types (duplicate type removed from above)
// Complete set of message types from backend (output_collector.py, chat_consumer.py)
export type WebSocketMessageType =
  | 'connected'      // connection confirmation (chat_consumer.py)
  | 'ack'           // message acknowledgment (chat_consumer.py)
  | 'thinking'       // thinking process (output_collector.py)
  | 'think'          // thinking process alias (output_collector.py)
  | 'llm_start'      // LLM call start (output_collector.py)
  | 'llm_end'        // LLM call end (output_collector.py)
  | 'tool_call'      // tool call (output_collector.py)
  | 'tool_result'    // tool execution result (output_collector.py)
  | 'answer'         // final answer (output_collector.py)
  | 'card'           // card data (output_collector.py)
  | 'done'           // completion signal (output_collector.py)
  | 'error'          // error (multiple places)
  | 'interrupted'    // interrupt signal (chat_consumer.py)
  | 'stopped'        // stop signal (chat_consumer.py)
  | 'tool_confirm_request';   // tool execution confirmation request (chat_service.py)

export interface WebSocketMessage {
  type: WebSocketMessageType;
  session_id?: string;
  message?: string;
  content?: string;
  timestamp?: number;
  message_id?: string;
  // message acknowledgment fields
  message_received?: boolean;
  // LLM fields
  llm_id?: string;
  model?: string;
  provider?: string;
  duration_ms?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  cached_tokens?: number;
  finish_reason?: string;
  // tool_call/tool_result fields
  status?: 'calling' | 'success' | 'error';
  tool_name?: string;
  parameters?: Record<string, unknown>;
  tool_call_id?: string;
  result?: unknown;
  // Card data from output_collector
  card_data?: Record<string, unknown>;
  // Metadata from backend
  metadata?: {
    interrupt_message?: string;
    message_received?: boolean;
    trace?: TraceItem[];
    [key: string]: unknown;
  };
}

// Message for display
export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  message_type: 'text' | 'thought' | 'action' | 'observation';
  timestamp: string;
  metadata?: Record<string, unknown>;
  trace?: TraceItem[];
  usage?: TokenUsage;
}

// Connection type
export type ConnectionType = 'http' | 'websocket';

// Agent type
export type AgentType = 'react' | 'pipeline';

// Session config for creating new session
export interface SessionConfig {
  title?: string;
  user_id?: string;
  agent_type?: AgentType;
  llm_provider_id?: number;
  metadata?: Record<string, unknown>;
  token?: string;
  connectionType?: ConnectionType;
  isStream?: boolean;
}

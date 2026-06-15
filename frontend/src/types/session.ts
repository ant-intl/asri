// Session related types

// Session status
export type SessionStatus = 'active' | 'archived' | 'deleted';

// Session from API
export interface Session {
  session_id: string;
  user_id?: string;
  title: string;
  status: SessionStatus;
  agent_type: string;
  llm_provider_id?: number;
  metadata?: Record<string, unknown>;
  gmt_create: string;
  gmt_modified: string;
}

// Session list response
export interface SessionListResponse {
  sessions: Session[];
  total: number;
  page: number;
  page_size: number;
}

// Create session request
export interface CreateSessionRequest {
  title?: string;
  user_id?: string;
  agent_type?: string;
  llm_provider_id?: number;
  metadata?: Record<string, unknown>;
  user_context?: Record<string, unknown>;
}

// Message from API
export interface Message {
  message_id: string;
  session_id?: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  message_type: 'text' | 'thought' | 'action' | 'observation';
  parent_message_id?: string;
  group_id?: string;
  token_count?: number;
  metadata?: Record<string, unknown>;
  gmt_create: string;
}

// Message list response
export interface MessageListResponse {
  messages: Message[];
  total: number;
  page: number;
  page_size: number;
}

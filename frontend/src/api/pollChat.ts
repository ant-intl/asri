import { baseClient } from './client';
import type { StreamChunk } from '@/types/chat';

// Types for HTTP Long Polling
export interface PollChatInitRequest {
  session_id: string;
  message: string;
  user_id?: string;
}

export interface PollChatInitResponse {
  user_message_id: string;
  session_id: string;
  status: string;
}

export interface PollChatChunksRequest {
  last_offset?: number;
  timeout?: number;
}

export interface PollChatChunksResponse {
  user_message_id: string;
  status: 'running' | 'done' | 'error' | 'cancelled';
  offset: number;
  chunks: StreamChunk[];
  trace?: Array<Record<string, any>>;
  assistant_message_id?: string;
  usage?: Record<string, any>;
  error?: string;
}

export interface PollChatCancelResponse {
  user_message_id: string;
  cancelled: boolean;
}

/**
 * Initiate a new polling chat session.
 * Returns user_message_id for subsequent polling requests.
 */
export const initPollChat = async (
  data: PollChatInitRequest,
  token?: string,
): Promise<PollChatInitResponse> => {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await baseClient.post<PollChatInitResponse>(
    '/chatbot/api/admin/poll/chat/init/',
    data,
    { headers },
  );
  return response.data;
};

/**
 * Poll for incremental chunks from a running polling task.
 * Blocks for up to `timeout` seconds if no new chunks are available.
 */
export const pollChatChunks = async (
  user_message_id: string,
  data: PollChatChunksRequest = {},
  token?: string,
): Promise<PollChatChunksResponse> => {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await baseClient.post<PollChatChunksResponse>(
    '/chatbot/api/admin/poll/chat/chunks/',
    { user_message_id, ...data },
    { headers },
  );
  return response.data;
};

/**
 * Cancel a running polling task.
 */
export const cancelPollChat = async (
  user_message_id: string,
  token?: string,
): Promise<PollChatCancelResponse> => {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const response = await baseClient.post<PollChatCancelResponse>(
    `/chatbot/api/admin/poll/chat/cancel/${user_message_id}/`,
    {},
    { headers },
  );
  return response.data;
};

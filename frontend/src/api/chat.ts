import { baseClient } from './client';
import type { ChatRequest, ChatResponse, StreamChunk, WebSocketMessage } from '@/types/chat';

// Helper to create headers with optional token
const createHeaders = (token?: string): Record<string, string> => {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
};

// Send chat message (non-streaming)
export const sendChat = async (data: ChatRequest, token?: string): Promise<ChatResponse> => {
  const response = await baseClient.post<ChatResponse>('/chatbot/api/admin/chat/', data, {
    headers: createHeaders(token),
  });
  return response.data;
};

// Send chat message with SSE streaming
export const sendChatStream = (
  data: ChatRequest,
  token: string | undefined,
  onMessage: (chunk: StreamChunk) => void,
  onDone: () => void,
  onError: (error: Error) => void,
): { abort: () => void; promise: Promise<void> } => {
  const baseUrl = import.meta.env.VITE_API_BASE || window.location.origin;
  const url = new URL('/chatbot/api/admin/chat/', baseUrl);

  // For POST-based SSE, we need to use fetch instead
  const controller = new AbortController();

  // Build headers: include X-Tenant-Id for tenant context (bypasses axios interceptor)
  const headers: Record<string, string> = createHeaders(token);
  const tenantId = localStorage.getItem('asri_tenant_id');
  if (tenantId) {
    headers['X-Tenant-Id'] = tenantId;
  }

  const promise = fetch(url.toString(), {
    method: 'POST',
    headers,
    body: JSON.stringify({
      ...data,
      stream: true,
    }),
    signal: controller.signal,
  })
    .then(async (response) => {
      if (!response.body) {
        throw new Error('No response body');
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        // { stream: true } handles multi-byte UTF-8 split correctly
        const text = decoder.decode(value, { stream: true });
        buffer += text;

        // Split by double newline to get complete SSE events.
        // Incomplete events stay in buffer for the next iteration.
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (const part of parts) {
          for (const line of part.split('\n')) {
            const trimmed = line.trim();
            if (!trimmed.startsWith('data: ')) continue;

            const data = trimmed.slice(6);
            if (data === '[DONE]') {
              onDone();
              return;
            }
            try {
              const parsed: StreamChunk = JSON.parse(data);
              onMessage(parsed);
            } catch {
              // Skip malformed events. Incomplete JSON should not reach
              // here because we split by \n\n — only complete events
              // (with trailing \n\n) are processed.
            }
          }
        }
      }
      onDone();
    })
    .catch((error) => {
      if (error.name !== 'AbortError') {
        onError(error);
      }
    });

  return {
    abort: () => controller.abort(),
    promise,
  };
};

// Interrupt an active streaming session
export const interruptChat = async (
  sessionId: string,
  interruptMessage: string,
  token?: string
): Promise<{ interrupted: boolean; session_id: string }> => {
  const response = await baseClient.post<{ interrupted: boolean; session_id: string }>(
    '/chatbot/api/admin/chat/interrupt/',
    {
      session_id: sessionId,
      interrupt_message: interruptMessage,
    },
    {
      headers: createHeaders(token),
    }
  );
  return response.data;
};

// WebSocket chat
export const createWebSocketChat = (
  sessionId: string,
  token?: string
): WebSocket => {
  const baseUrl = import.meta.env.VITE_API_BASE || window.location.origin;
  const wsBaseUrl = baseUrl.replace('http', 'ws');
  const wsUrl = new URL(`/ws/chat/${sessionId}/`, wsBaseUrl);

  if (token) {
    wsUrl.searchParams.set('token', token);
  }

  return new WebSocket(wsUrl.toString());
};

// Parse WebSocket message
export const parseWebSocketMessage = (data: string): WebSocketMessage | null => {
  try {
    return JSON.parse(data) as WebSocketMessage;
  } catch {
    return null;
  }
};

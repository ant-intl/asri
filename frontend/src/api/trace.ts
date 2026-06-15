/**
 * Trace API - Session trace observation endpoints.
 */

import { baseClient } from './client';
import type { TraceItem } from '@/types/chat';

export interface ConversationTrace {
  user_message_id: string | null;
  user_content: string;
  assistant_message_id: string;
  stream_status: 'streaming' | 'completed' | 'interrupted';
  trace: TraceItem[];
  gmt_create: string;
}

export interface SessionTraceResponse {
  session_id: string;
  session_title: string;
  is_streaming: boolean;
  conversations: ConversationTrace[];
  last_message_id: string | null;
}

/**
 * Get trace data for a session.
 *
 * Admin endpoint, no auth token required.
 * Supports incremental polling via afterId parameter.
 */
export const getSessionTrace = async (
  sessionId: string,
  afterId?: string,
): Promise<SessionTraceResponse> => {
  const params: Record<string, string> = {};
  if (afterId) {
    params.after_id = afterId;
  }
  const response = await baseClient.get<SessionTraceResponse>(
    `/chatbot/api/admin/sessions/${sessionId}/trace/`,
    { params },
  );
  return response.data;
};

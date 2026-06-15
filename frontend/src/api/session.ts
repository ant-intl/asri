import { baseClient } from './client';
import type { Session, SessionListResponse, CreateSessionRequest, MessageListResponse } from '@/types/session';

// Helper to create headers with optional token
const createHeaders = (token?: string): Record<string, string> => {
  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
};

// Get session list
export const getSessions = async (
  params?: {
    user_id?: string;
    status?: string;
    page?: number;
    page_size?: number;
  },
  token?: string
): Promise<SessionListResponse> => {
  const response = await baseClient.get<SessionListResponse>('/chatbot/api/admin/sessions/', {
    params,
    headers: createHeaders(token),
  });
  return response.data;
};

// Get single session
export const getSession = async (sessionId: string, token?: string): Promise<Session> => {
  const response = await baseClient.get<Session>(`/chatbot/api/admin/sessions/${sessionId}/`, {
    headers: createHeaders(token),
  });
  return response.data;
};

// Create session
export const createSession = async (
  data: CreateSessionRequest,
  token?: string
): Promise<Session> => {
  const response = await baseClient.post<Session>('/chatbot/api/admin/sessions/', data, {
    headers: createHeaders(token),
  });
  return response.data;
};

// Update session
export const updateSession = async (
  sessionId: string,
  data: Partial<CreateSessionRequest>,
  token?: string
): Promise<Session> => {
  const response = await baseClient.put<Session>(`/chatbot/api/admin/sessions/${sessionId}/`, data, {
    headers: createHeaders(token),
  });
  return response.data;
};

// Delete session (archive)
export const deleteSession = async (sessionId: string, token?: string): Promise<void> => {
  await baseClient.delete(`/chatbot/api/admin/sessions/${sessionId}/`, {
    headers: createHeaders(token),
  });
};

// Get session messages
export const getSessionMessages = async (
  sessionId: string,
  params?: {
    page?: number;
    page_size?: number;
  },
  token?: string
): Promise<MessageListResponse> => {
  const response = await baseClient.get<MessageListResponse>(
    `/chatbot/api/admin/sessions/${sessionId}/messages/`,
    { params, headers: createHeaders(token) }
  );
  return response.data;
};

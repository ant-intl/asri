import { apiClient } from './client';
import type {
  HookConfig,
  HookConfigListResponse,
  CreateHookConfigRequest,
} from '../types/hook';

// ── Hook CRUD ────────────────────────────────────────────────────

export const getHookConfigs = async (): Promise<HookConfigListResponse> => {
  const { data } = await apiClient.get('/chatbot/api/admin/hooks/');
  return data;
};

export const createHookConfig = async (
  req: CreateHookConfigRequest
): Promise<HookConfig> => {
  const { data } = await apiClient.post('/chatbot/api/admin/hooks/', req);
  return data;
};

export const updateHookConfig = async (
  id: number,
  req: Partial<CreateHookConfigRequest>
): Promise<HookConfig> => {
  const { data } = await apiClient.put(`/chatbot/api/admin/hooks/${id}/`, req);
  return data;
};

export const deleteHookConfig = async (id: number): Promise<void> => {
  await apiClient.delete(`/chatbot/api/admin/hooks/${id}/`);
};

export const toggleHookConfig = async (id: number): Promise<HookConfig> => {
  const { data } = await apiClient.post(
    `/chatbot/api/admin/hooks/${id}/toggle/`
  );
  return data;
};

// ── Tool Confirmation ────────────────────────────────────────────

export const confirmTool = async (
  confirmationId: string,
  approved: boolean
): Promise<void> => {
  await apiClient.post('/chatbot/api/admin/chat/confirm/', {
    confirmation_id: confirmationId,
    approved,
  });
};

import { baseClient } from './client';
import type {
  VoiceAgentConfig,
  VoiceAgentConfigListResponse,
  CreateVoiceAgentConfigRequest,
} from '@/types/voiceAgentConfig';

// List all voice agent configs
export const getVoiceAgentConfigs = async (): Promise<VoiceAgentConfigListResponse> => {
  const response = await baseClient.get<VoiceAgentConfigListResponse>(
    '/chatbot/api/admin/voice-agent-config/'
  );
  return response.data;
};

// Get single voice agent config
export const getVoiceAgentConfig = async (id: number): Promise<VoiceAgentConfig> => {
  const response = await baseClient.get<VoiceAgentConfig>(
    `/chatbot/api/admin/voice-agent-config/${id}/`
  );
  return response.data;
};

// Create voice agent config
export const createVoiceAgentConfig = async (
  data: CreateVoiceAgentConfigRequest
): Promise<VoiceAgentConfig> => {
  const response = await baseClient.post<VoiceAgentConfig>(
    '/chatbot/api/admin/voice-agent-config/',
    data
  );
  return response.data;
};

// Update voice agent config
export const updateVoiceAgentConfig = async (
  id: number,
  data: Partial<CreateVoiceAgentConfigRequest>
): Promise<VoiceAgentConfig> => {
  const response = await baseClient.put<VoiceAgentConfig>(
    `/chatbot/api/admin/voice-agent-config/${id}/`,
    data
  );
  return response.data;
};

// Delete (deactivate) voice agent config
export const deleteVoiceAgentConfig = async (id: number): Promise<void> => {
  await baseClient.delete(`/chatbot/api/admin/voice-agent-config/${id}/`);
};

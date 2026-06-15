/**
 * Prompt Template API client
 */
import { baseClient } from './client';
import type {
  PromptTemplate,
  PromptTemplateListResponse,
  CreatePromptTemplateRequest,
  EnablePromptTemplateResponse,
} from '@/types/promptTemplate';

// API base paths
const API_BASE = '/chatbot/api/admin/prompt-templates/';

export const getPromptTemplates = async (): Promise<PromptTemplateListResponse> => {
  const response = await baseClient.get<PromptTemplateListResponse>(API_BASE);
  return response.data;
};

export const getPromptTemplate = async (id: string): Promise<PromptTemplate> => {
  const response = await baseClient.get<PromptTemplate>(`${API_BASE}${id}/`);
  return response.data;
};

export const createPromptTemplate = async (
  data: CreatePromptTemplateRequest
): Promise<PromptTemplate> => {
  const response = await baseClient.post<PromptTemplate>(API_BASE, data);
  return response.data;
};

export const updatePromptTemplate = async (
  id: string,
  data: Partial<CreatePromptTemplateRequest>
): Promise<PromptTemplate> => {
  const response = await baseClient.put<PromptTemplate>(
    `${API_BASE}${id}/`,
    data
  );
  return response.data;
};

export const deletePromptTemplate = async (id: string): Promise<void> => {
  await baseClient.delete(`${API_BASE}${id}/`);
};

// Enable prompt template (syncs to tenant config)
export const enablePromptTemplate = async (id: string): Promise<EnablePromptTemplateResponse> => {
  const response = await baseClient.post<EnablePromptTemplateResponse>(`${API_BASE}${id}/enable/`);
  return response.data;
};

// Disable prompt template (syncs to tenant config)
export const disablePromptTemplate = async (id: string): Promise<{
  success: boolean;
  id: string;
  name: string;
  message: string;
}> => {
  const response = await baseClient.post(`${API_BASE}${id}/disable/`);
  return response.data;
};

import { baseClient } from './client';
import type { LLMProvider, LLMProviderListResponse, CreateLLMProviderRequest } from '@/types/llmProvider';

// Get all LLM providers
export const getLLMProviders = async (): Promise<LLMProviderListResponse> => {
  const response = await baseClient.get<LLMProviderListResponse>('/chatbot/api/admin/llm-providers/');
  return response.data;
};

// Get single LLM provider
export const getLLMProvider = async (id: number): Promise<LLMProvider> => {
  const response = await baseClient.get<LLMProvider>(`/chatbot/api/admin/llm-providers/${id}/`);
  return response.data;
};

// Create LLM provider
export const createLLMProvider = async (data: CreateLLMProviderRequest): Promise<LLMProvider> => {
  const response = await baseClient.post<LLMProvider>('/chatbot/api/admin/llm-providers/', data);
  return response.data;
};

// Update LLM provider
export const updateLLMProvider = async (id: number, data: Partial<CreateLLMProviderRequest>): Promise<LLMProvider> => {
  const response = await baseClient.put<LLMProvider>(`/chatbot/api/admin/llm-providers/${id}/`, data);
  return response.data;
};

// Delete LLM provider
export const deleteLLMProvider = async (id: number): Promise<void> => {
  await baseClient.delete(`/chatbot/api/admin/llm-providers/${id}/`);
};

// Enable LLM provider
export const enableLLMProvider = async (id: number): Promise<{ success: boolean; id: number; name: string; message: string }> => {
  const response = await baseClient.post(`/chatbot/api/admin/llm-providers/${id}/enable/`);
  return response.data;
};

// Disable LLM provider
export const disableLLMProvider = async (id: number): Promise<{ success: boolean; id: number; name: string; message: string }> => {
  const response = await baseClient.post(`/chatbot/api/admin/llm-providers/${id}/disable/`);
  return response.data;
};

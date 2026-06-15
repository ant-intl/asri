import { baseClient } from './client';
import type { Tool, ToolListResponse, CreateToolRequest, BuiltInToolToggleRequest, BuiltInToolToggleResponse } from '@/types/tool';

// Get all tools (including built-in tools)
export const getTools = async (): Promise<ToolListResponse> => {
  const response = await baseClient.get<ToolListResponse>('/chatbot/api/admin/tools/');
  return response.data;
};

// Get single tool
export const getTool = async (id: number): Promise<Tool> => {
  const response = await baseClient.get<Tool>(`/chatbot/api/admin/tools/${id}/`);
  return response.data;
};

// Create tool
export const createTool = async (data: CreateToolRequest): Promise<Tool> => {
  const response = await baseClient.post<Tool>('/chatbot/api/admin/tools/', data);
  return response.data;
};

// Update tool
export const updateTool = async (id: number, data: Partial<CreateToolRequest>): Promise<Tool> => {
  const response = await baseClient.put<Tool>(`/chatbot/api/admin/tools/${id}/`, data);
  return response.data;
};

// Delete tool
export const deleteTool = async (id: number): Promise<void> => {
  await baseClient.delete(`/chatbot/api/admin/tools/${id}/`);
};

// Enable tool
export const enableTool = async (id: number): Promise<{ success: boolean; id: number; name: string; message: string }> => {
  const response = await baseClient.post(`/chatbot/api/admin/tools/${id}/enable/`);
  return response.data;
};

// Disable tool
export const disableTool = async (id: number): Promise<{ success: boolean; id: number; name: string; message: string }> => {
  const response = await baseClient.post(`/chatbot/api/admin/tools/${id}/disable/`);
  return response.data;
};

// Toggle built-in tool
export const toggleBuiltInTool = async (name: string, enable: boolean): Promise<BuiltInToolToggleResponse> => {
  const data: BuiltInToolToggleRequest = { enable };
  const response = await baseClient.post<BuiltInToolToggleResponse>(`/chatbot/api/admin/builtin-tools/${name}/toggle/`, data);
  return response.data;
};

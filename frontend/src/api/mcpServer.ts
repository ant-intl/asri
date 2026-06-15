import { baseClient } from './client';
import type {
  McpServer,
  McpServerListResponse,
  CreateMcpServerRequest,
  UpdateMcpServerRequest,
  McpToolMockConfig,
} from '@/types/mcpServer';

// Get all MCP servers
export const getMcpServers = async (): Promise<McpServerListResponse> => {
  const response = await baseClient.get<McpServerListResponse>('/chatbot/api/admin/mcp-servers/');
  return response.data;
};

// Get single MCP server
export const getMcpServer = async (serverId: string): Promise<McpServer> => {
  const response = await baseClient.get<McpServer>(`/chatbot/api/admin/mcp-servers/${serverId}/`);
  return response.data;
};

// Create MCP server
export const createMcpServer = async (data: CreateMcpServerRequest): Promise<McpServer> => {
  const response = await baseClient.post<McpServer>('/chatbot/api/admin/mcp-servers/', data);
  return response.data;
};

// Update MCP server
export const updateMcpServer = async (serverId: string, data: UpdateMcpServerRequest): Promise<McpServer> => {
  const response = await baseClient.put<McpServer>(`/chatbot/api/admin/mcp-servers/${serverId}/`, data);
  return response.data;
};

// Delete MCP server
export const deleteMcpServer = async (serverId: string): Promise<void> => {
  await baseClient.delete(`/chatbot/api/admin/mcp-servers/${serverId}/`);
};

// Toggle MCP server active status
export const toggleMcpServer = async (serverId: string): Promise<McpServer> => {
  const response = await baseClient.patch<McpServer>(`/chatbot/api/admin/mcp-servers/${serverId}/toggle/`);
  return response.data;
};

// Get tool mock configuration
export const getToolMockConfig = async (serverId: string, toolName: string): Promise<McpToolMockConfig> => {
  const response = await baseClient.get<McpToolMockConfig>(
    `/chatbot/api/admin/mcp-servers/${serverId}/tools/${toolName}/mock/`
  );
  return response.data;
};

// Update tool mock configuration
export const updateToolMockConfig = async (
  serverId: string,
  toolName: string,
  data: McpToolMockConfig
): Promise<McpToolMockConfig> => {
  const response = await baseClient.put<McpToolMockConfig>(
    `/chatbot/api/admin/mcp-servers/${serverId}/tools/${toolName}/mock/`,
    data
  );
  return response.data;
};

// Toggle tool mock enabled status
export const toggleToolMock = async (serverId: string, toolName: string): Promise<McpToolMockConfig> => {
  const response = await baseClient.patch<McpToolMockConfig>(
    `/chatbot/api/admin/mcp-servers/${serverId}/tools/${toolName}/mock/toggle/`
  );
  return response.data;
};

// Refresh tools list from MCP server
export const refreshMcpServerTools = async (serverId: string): Promise<McpServer> => {
  const response = await baseClient.post<McpServer>(
    `/chatbot/api/admin/mcp-servers/${serverId}/refresh-tools/`
  );
  return response.data;
};

// Execute MCP tool
export const executeMcpTool = async (
  serverId: string,
  toolName: string,
  toolArguments: Record<string, unknown>
): Promise<{ success: boolean; result: unknown }> => {
  const response = await baseClient.post<{ success: boolean; result: unknown }>(
    `/chatbot/api/admin/mcp-servers/${serverId}/tools/${toolName}/execute/`,
    { arguments: toolArguments }
  );
  return response.data;
};
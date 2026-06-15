export type MockMode = 'fixed' | 'random' | 'manual';
export type McpClientType = 'stdio' | 'http' | 'custom';

export interface MockPair {
  id: string;
  input: Record<string, unknown>;
  output: unknown;
}

export interface McpToolMock {
  enabled?: boolean;
  mode?: MockMode;
  pairs?: MockPair[];
  randomOutputs?: unknown[];
  manualInput?: Record<string, unknown>;
  manualOutput?: unknown;
}

export interface McpTool {
  name: string;
  description: string;
  inputSchema: {
    type: string;
    properties: Record<string, {
      type: string;
      description?: string;
    }>;
    required?: string[];
  };
  mock?: McpToolMock;
}

export interface McpServer {
  id: string;
  name: string;
  description?: string;
  clientType?: McpClientType;
  // Stdio fields
  command: string;
  args: string[];
  env?: Record<string, string>;
  // Client-specific configuration
  config?: Record<string, unknown>;
  // Common
  isActive: boolean;
  tools?: McpTool[];
  createdAt?: string;
  updatedAt?: string;
}

export interface McpServerListResponse {
  providers: McpServer[];
}

export interface CreateMcpServerRequest {
  id?: string;
  name: string;
  description?: string;
  clientType?: McpClientType;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  config?: Record<string, unknown>;
  isActive?: boolean;
  tools?: McpTool[];
}

export interface UpdateMcpServerRequest extends Partial<CreateMcpServerRequest> {}

export interface McpToolMockConfig {
  toolName: string;
  mock: McpToolMock;
}

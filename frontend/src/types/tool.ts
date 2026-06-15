// Tool related types

export type ToolType = 'tool' | 'rag';

export interface Tool {
  id?: number;  // Built-in tools don't have id
  name: string;
  tool_type: ToolType;
  description?: string;
  parameters_schema?: Record<string, unknown>;
  config_json?: Record<string, unknown>;
  is_active: boolean;
  is_builtin: boolean;  // Whether this is a built-in tool
  gmt_create?: string;
  gmt_modified?: string;
}

export interface ToolListResponse {
  tools: Tool[];
}

export interface CreateToolRequest {
  name: string;
  tool_type?: ToolType;
  description?: string;
  parameters_schema?: Record<string, unknown>;
  config_json?: Record<string, unknown>;
  is_active?: boolean;
}

export interface BuiltInToolToggleRequest {
  enable: boolean;
}

export interface BuiltInToolToggleResponse {
  success: boolean;
  name: string;
  is_enabled: boolean;
  message: string;
}

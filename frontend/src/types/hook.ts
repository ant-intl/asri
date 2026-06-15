// Hook configuration types

export interface HookConfig {
  id: number;
  tenant_id: string;
  hook_type: string;
  hook_name: string;
  description: string;
  is_active: boolean;
  config_json: Record<string, unknown>;
  gmt_create: string;
  gmt_modified?: string;
}

export interface CreateHookConfigRequest {
  hook_type: string;
  hook_name: string;
  description?: string;
  is_active?: boolean;
  config_json?: Record<string, unknown>;
}

export interface HookConfigListResponse {
  hooks: HookConfig[];
}

export interface ToolConfirmRequest {
  type: 'tool_confirm_request';
  confirmation_id: string;
  tool_name: string;
  arguments: string;
  timeout: number;
  timestamp: number;
}

export interface ToolConfirmResponse {
  confirmation_id: string;
  approved: boolean;
}

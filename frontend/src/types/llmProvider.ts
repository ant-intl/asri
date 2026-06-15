// LLM Provider related types

export type ProviderType = 'openai' | 'ollama' | 'asri_gateway';
export type ModelPurpose = 'chatbot';

export interface LLMProvider {
  id: number;
  name: string;
  provider_type: ProviderType;
  api_base?: string;
  api_key?: string;
  model_name: string;
  is_default: boolean;
  is_active: boolean;
  purpose?: ModelPurpose;
  config_json?: Record<string, unknown>;
  gmt_create: string;
  gmt_modified?: string;
}

export interface LLMProviderListResponse {
  providers: LLMProvider[];
}

export interface CreateLLMProviderRequest {
  name: string;
  provider_type: ProviderType;
  api_base?: string;
  api_key?: string;
  model_name: string;
  purpose?: ModelPurpose;
  config_json?: Record<string, unknown>;
  is_default?: boolean;
  is_active?: boolean;
}

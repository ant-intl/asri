/**
 * Prompt Template types
 */

export type LayerTarget = 'system' | 'user';
export type LayerStrategy = 'always' | 'first_turn';

/** A single layer dict stored in PromptTemplate.layers JSON array */
export interface PromptLayer {
  id: string;
  name: string;
  description?: string;
  target: LayerTarget;
  strategy: LayerStrategy;
  template: string;
  order: number;
  is_active: boolean;
}

export interface PromptTemplate {
  id: string;
  name: string;
  description?: string;
  system_template: string;
  user_template_mode: 'generic' | 'custom';
  user_template?: string;
  extractor_config: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  /** Prompt layers (JSON array stored on the model) */
  layers: PromptLayer[];
}

export interface PromptTemplateListResponse {
  templates: PromptTemplate[];
  total: number;
}

export interface CreatePromptTemplateRequest {
  name: string;
  description?: string;
  system_template: string;
  user_template_mode: 'generic' | 'custom';
  user_template?: string;
  extractor_config?: Record<string, unknown>;
  is_active?: boolean;
  layers?: PromptLayer[];
}

export interface EnablePromptTemplateResponse {
  success: boolean;
  id: string;
  name: string;
  message: string;
  disabled_template?: {
    id: string;
    name: string;
  };
}

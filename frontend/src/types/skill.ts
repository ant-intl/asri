// Skill related types

export interface Skill {
  skill_id: string;
  name: string;
  description?: string;
  content: string;
  is_active: boolean;
  metadata?: Record<string, unknown>;
  gmt_create: string;
  gmt_modified?: string;
}

export interface SkillListResponse {
  skills: Skill[];
  total: number;
  page: number;
  page_size: number;
}

export interface CreateSkillRequest {
  name: string;
  content: string;
  description?: string;
  is_active?: boolean;
  metadata?: Record<string, unknown>;
}


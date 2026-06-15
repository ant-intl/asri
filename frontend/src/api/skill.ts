import { baseClient } from './client';
import type {
  Skill,
  SkillListResponse,
  CreateSkillRequest,
} from '@/types/skill';

// Get all skills
export const getSkills = async (page = 1, pageSize = 20, isActive?: boolean): Promise<SkillListResponse> => {
  const params = new URLSearchParams();
  params.append('page', page.toString());
  params.append('page_size', pageSize.toString());
  if (isActive !== undefined) {
    params.append('is_active', isActive.toString());
  }
  const response = await baseClient.get<SkillListResponse>(`/chatbot/api/admin/skills/?${params.toString()}`);
  return response.data;
};

// Get single skill
export const getSkill = async (skillId: string): Promise<Skill> => {
  const response = await baseClient.get<Skill>(`/chatbot/api/admin/skills/${skillId}/`);
  return response.data;
};

// Create skill
export const createSkill = async (data: CreateSkillRequest): Promise<Skill> => {
  const response = await baseClient.post<Skill>('/chatbot/api/admin/skills/', data);
  return response.data;
};

// Update skill
export const updateSkill = async (skillId: string, data: Partial<CreateSkillRequest>): Promise<Skill> => {
  const response = await baseClient.put<Skill>(`/chatbot/api/admin/skills/${skillId}/`, data);
  return response.data;
};

// Delete skill
export const deleteSkill = async (skillId: string): Promise<{ success: boolean }> => {
  const response = await baseClient.delete<{ success: boolean }>(`/chatbot/api/admin/skills/${skillId}/`);
  return response.data;
};

// Refresh skill cache
export const refreshSkill = async (skillId: string): Promise<void> => {
  await baseClient.post(`/chatbot/api/admin/skills/${skillId}/refresh/`);
};

// Enable skill
export const enableSkill = async (skillId: string): Promise<{ success: boolean; skill_id: string; message: string }> => {
  const response = await baseClient.post<{ success: boolean; skill_id: string; message: string }>(
    `/chatbot/api/admin/skills/${skillId}/enable/`
  );
  return response.data;
};

// Disable skill
export const disableSkill = async (skillId: string): Promise<{ success: boolean; skill_id: string; message: string }> => {
  const response = await baseClient.post<{ success: boolean; skill_id: string; message: string }>(
    `/chatbot/api/admin/skills/${skillId}/disable/`
  );
  return response.data;
};

// Upload skill zip package
export const uploadSkillZip = async (file: File): Promise<{ success: boolean; skill_id: string; name: string; message: string }> => {
  const formData = new FormData();
  formData.append('file', file);
  const response = await baseClient.post<{ success: boolean; skill_id: string; name: string; message: string }>(
    '/chatbot/api/admin/skills/upload/',
    formData,
    {
      headers: {
        'Content-Type': undefined,
      },
    },
  );
  return response.data;
};


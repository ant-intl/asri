/**
 * Version Snapshot API client
 */
import { baseClient } from './client';
import type {
  VersionSnapshot,
  VersionListResponse,
  CreateVersionRequest,
  UpdateVersionRequest,
  VersionDiffResponse,
  ActivateVersionResponse,
  EntityType,
} from '@/types/version';

const API_BASE = '/chatbot/api/admin/versions/';

export const getVersions = async (
  entityType: EntityType,
  entityId: string,
  page: number = 1,
  pageSize: number = 20,
): Promise<VersionListResponse> => {
  const response = await baseClient.get<VersionListResponse>(API_BASE, {
    params: { entity_type: entityType, entity_id: entityId, page, page_size: pageSize },
  });
  return response.data;
};

export const getVersion = async (versionId: string): Promise<VersionSnapshot> => {
  const response = await baseClient.get<VersionSnapshot>(`${API_BASE}${versionId}/`);
  return response.data;
};

export const createVersion = async (data: CreateVersionRequest): Promise<VersionSnapshot> => {
  const response = await baseClient.post<VersionSnapshot>(API_BASE, data);
  return response.data;
};

export const updateVersion = async (
  versionId: string,
  data: UpdateVersionRequest,
): Promise<VersionSnapshot> => {
  const response = await baseClient.put<VersionSnapshot>(`${API_BASE}${versionId}/`, data);
  return response.data;
};

export const deleteVersion = async (versionId: string): Promise<void> => {
  await baseClient.delete(`${API_BASE}${versionId}/`);
};

export const activateVersion = async (versionId: string): Promise<ActivateVersionResponse> => {
  const response = await baseClient.post<ActivateVersionResponse>(`${API_BASE}${versionId}/activate/`);
  return response.data;
};

export const getVersionDiff = async (
  versionIdA: string,
  versionIdB: string,
): Promise<VersionDiffResponse> => {
  const response = await baseClient.get<VersionDiffResponse>(`${API_BASE}diff/`, {
    params: { version_a: versionIdA, version_b: versionIdB },
  });
  return response.data;
};

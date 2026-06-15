/**
 * Session Snapshot API client
 */
import { baseClient } from './client';
import type {
  SessionSnapshot,
  SnapshotListResponse,
  CreateSnapshotRequest,
  UpdateSnapshotRequest,
  SnapshotConfigPreview,
} from '@/types/snapshot';

const API_BASE = '/chatbot/api/admin/snapshots/';

/** List snapshots with pagination */
export const getSnapshots = async (
  page: number = 1,
  pageSize: number = 20,
): Promise<SnapshotListResponse> => {
  const response = await baseClient.get<SnapshotListResponse>(API_BASE, {
    params: { page, page_size: pageSize },
  });
  return response.data;
};

/** Get a single snapshot by ID */
export const getSnapshot = async (id: string): Promise<SessionSnapshot> => {
  const response = await baseClient.get<SessionSnapshot>(`${API_BASE}${id}/`);
  return response.data;
};

/** Create a snapshot from a session */
export const createSnapshot = async (data: CreateSnapshotRequest): Promise<{ id: string; name: string }> => {
  const response = await baseClient.post<{ id: string; name: string }>(API_BASE, data);
  return response.data;
};

/** Update snapshot name/description */
export const updateSnapshot = async (
  id: string,
  data: UpdateSnapshotRequest,
): Promise<SessionSnapshot> => {
  const response = await baseClient.put<SessionSnapshot>(`${API_BASE}${id}/`, data);
  return response.data;
};

/** Soft-delete a snapshot */
export const deleteSnapshot = async (id: string): Promise<void> => {
  await baseClient.delete(`${API_BASE}${id}/`);
};

/** Preview resolved configuration for a snapshot */
export const getSnapshotConfigPreview = async (id: string): Promise<SnapshotConfigPreview> => {
  const response = await baseClient.get<SnapshotConfigPreview>(`${API_BASE}${id}/config/`);
  return response.data;
};

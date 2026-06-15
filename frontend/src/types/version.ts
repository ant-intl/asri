/**
 * Version snapshot types for prompt template and skill version management.
 */

export type EntityType = 'prompt_template' | 'skill';

export interface VersionSnapshot {
  id: string;
  entity_type: EntityType;
  entity_id: string;
  version_number: number;
  label: string;
  description: string;
  snapshot_data: Record<string, unknown>;
  is_active: boolean;
  created_by: string;
  gmt_create: string;
  gmt_modified: string;
}

export interface VersionListResponse {
  versions: VersionSnapshot[];
  total: number;
}

export interface CreateVersionRequest {
  entity_type: EntityType;
  entity_id: string;
  label?: string;
  description?: string;
  created_by?: string;
}

export interface UpdateVersionRequest {
  label?: string;
  description?: string;
}

export interface DiffLine {
  type: 'added' | 'removed' | 'unchanged';
  content: string;
  line_a: number | null;
  line_b: number | null;
}

export interface FieldDiff {
  type: 'text' | 'json';
  lines: DiffLine[];
}

export interface VersionDiffResponse {
  version_a: { id: string; version_number: number; label: string };
  version_b: { id: string; version_number: number; label: string };
  fields: Record<string, FieldDiff>;
}

export interface ActivateVersionResponse {
  success: boolean;
  message: string;
  version: VersionSnapshot;
}

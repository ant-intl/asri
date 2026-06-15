/**
 * Session Snapshot types.
 *
 * A snapshot freezes the complete agent configuration at a point in time,
 * enabling session recreation and playground comparisons.
 */

/** LLM provider reference stored in snapshot_data */
export interface SnapshotLLMProviderRef {
  provider_config_id: number;
  provider_type: string;
  model_name: string;
  name: string;
}

/** Prompt configuration stored in snapshot_data */
export interface SnapshotPrompt {
  prompt_id: string | null;
  name: string;
  mode: string;
  system_template: string | null;
  user_template: string | null;
  user_template_mode: string;
  layers: unknown[];
  extractor_config: Record<string, unknown> | null;
}

/** Skill reference stored in snapshot_data */
export interface SnapshotSkill {
  skill_id: string;
  name: string;
  description?: string;
  content?: string;
  metadata?: Record<string, unknown>;
}

/** Tool reference stored in snapshot_data */
export interface SnapshotTool {
  id: number;
  name: string;
  tool_type?: string;
  description?: string;
  parameters_schema?: Record<string, unknown>;
  config_json?: Record<string, unknown>;
}

/** RAG provider reference stored in snapshot_data */
export interface SnapshotRAGProvider {
  id: number;
  name: string;
  provider_type: string;
  api_base?: string;
  config_json?: Record<string, unknown>;
}

/** Runtime settings frozen in snapshot (connection, interrupt, etc.) */
export interface SnapshotSettings {
  interruptionLogic?: string;
  toolInterruptStrategy?: string;
  connectionType?: 'http' | 'websocket';
  httpStreamingMode?: 'sse' | 'polling' | 'none';
}

/** Complete snapshot_data payload */
export interface SnapshotData {
  agent_type: string;
  llm_provider_ref: SnapshotLLMProviderRef | null;
  prompt: SnapshotPrompt | null;
  skills: SnapshotSkill[];
  tools: SnapshotTool[];
  rag_providers: SnapshotRAGProvider[];
  settings?: SnapshotSettings;
}

/** SessionSnapshot model */
export interface SessionSnapshot {
  id: string;
  name: string;
  description: string;
  source_session_id: string | null;
  snapshot_data: SnapshotData;
  tags: string[];
  is_active: boolean;
  created_by: string;
  gmt_create: string | null;
  gmt_modified: string | null;
}

/** Paginated list response */
export interface SnapshotListResponse {
  items: SessionSnapshot[];
  total: number;
}

/** Request to create a snapshot from a session */
export interface CreateSnapshotRequest {
  session_id: string;
  name: string;
  description?: string;
  settings?: Record<string, unknown>;
}

/** Request to update a snapshot */
export interface UpdateSnapshotRequest {
  name?: string;
  description?: string;
}

/** Resolved LLM provider info in config preview */
export interface ResolvedLLMInfo {
  id?: number;
  provider_type?: string;
  model_name?: string;
  name?: string;
  error?: string;
}

/** Snapshot config preview response */
export interface SnapshotConfigPreview {
  id: string;
  name: string;
  description: string;
  source_session_id: string | null;
  snapshot_data: SnapshotData;
  resolved_llm: ResolvedLLMInfo | null;
  gmt_create: string | null;
}

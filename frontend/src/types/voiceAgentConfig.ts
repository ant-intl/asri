// Voice Agent Configuration types

export interface VoiceSettings {
  stt?: {
    backend?: string;
    asr_backend?: string;
    url?: string;
    api_key?: string;
    model?: string;
    language?: string;
    language_code?: string;
    timeout?: number;
    block_duration_ms?: number;
    voice_id?: string;
    output_format?: string;
    [key: string]: unknown;
  };
  tts?: {
    backend?: string;
    base_url?: string;
    api_key?: string;
    model?: string;
    voice?: string;
    voice_id?: string;
    speed?: number;
    timeout?: number;
    sample_rate?: number;
    num_step?: number;
    output_format?: string;
    blocksize?: number;
    [key: string]: unknown;
  };
  vad?: {
    thresh?: number;
    min_silence_ms?: number;
    min_speech_ms?: number;
    speech_pad_ms?: number;
    sample_rate?: number;
  };
  enable_barge_in?: boolean;
  enable_heartbeat_interaction?: boolean;
  heartbeat?: {
    mode?: string;
    model_name?: string;
    base_url?: string;
    api_key?: string;
    asr_backend?: string;
    sensevoice_url?: string;
    sensevoice_timeout?: number;
    qwen3_asr_base_url?: string;
    qwen3_asr_model_name?: string;
    qwen3_asr_timeout?: number;
    dashscope_asr_api_key?: string;
    dashscope_asr_model?: string;
    dashscope_asr_language_hints?: string;
    whisper_asr_url?: string;
    whisper_asr_api_key?: string;
    whisper_asr_model?: string;
    whisper_asr_language?: string;
    block_duration_ms?: number;
    request_timeout_s?: number;
    max_heartbeat_entries?: number;
    prompt_version?: string;
    disable_thinking?: boolean;
    blocking?: boolean;
    max_concurrent?: number;
    [key: string]: unknown;
  };
}

export interface VoiceAgentConfig {
  id: number;
  name: string;
  tenant_id: string;
  is_active: boolean;
  voice_settings: VoiceSettings;
  gmt_create: string;
  gmt_modified: string;
}

export interface VoiceAgentConfigListResponse {
  configs: VoiceAgentConfig[];
}

export interface CreateVoiceAgentConfigRequest {
  name?: string;
  is_active?: boolean;
  voice_settings?: VoiceSettings;
}

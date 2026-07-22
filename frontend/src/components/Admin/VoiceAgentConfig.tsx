import React, { useEffect, useState, useCallback } from 'react';
import {
  Form,
  Select,
  Switch,
  InputNumber,
  Input,
  Button,
  Card,
  Space,
  Typography,
  Tooltip,
  message,
  Spin,
  Divider,
  Tag,
  Tabs,
} from 'antd';
import {
  SaveOutlined,
  PlusOutlined,
  DeleteOutlined,
  AudioOutlined,
  ControlOutlined,
  ClockCircleOutlined,
  QuestionCircleOutlined,
} from '@ant-design/icons';
import type { VoiceAgentConfig as VoiceAgentConfigType, VoiceSettings } from '@/types/voiceAgentConfig';
import {
  getVoiceAgentConfigs,
  createVoiceAgentConfig,
  updateVoiceAgentConfig,
  deleteVoiceAgentConfig,
} from '@/api/voiceAgentConfig';

const { Title } = Typography;

/** Helper: renders a label with a tooltip question mark. */
const labelWithTip = (label: string, tip: string) => (
  <span>
    {label}&nbsp;
    <Tooltip title={tip}>
      <QuestionCircleOutlined style={{ color: '#999', fontSize: 12 }} />
    </Tooltip>
  </span>
);

const DEFAULT_VOICE_SETTINGS: VoiceSettings = {
  stt: { backend: 'openai_whisper', url: '', api_key: '', model: 'whisper-1', language: 'zh', timeout: 30 },
  tts: { backend: 'openai_tts', base_url: '', api_key: '', model: 'tts-1', voice: 'alloy', speed: 1.0, timeout: 30, sample_rate: 16000 },
  vad: { thresh: 0.5, min_silence_ms: 500, min_speech_ms: 200, speech_pad_ms: 300, sample_rate: 16000 },
  enable_barge_in: true,
  enable_heartbeat_interaction: true,
  heartbeat: {
    mode: 'streaming_asr',
    request_timeout_s: 30,
    max_heartbeat_entries: 99,
    prompt_version: 'asri-generic-v0',
    disable_thinking: true,
    blocking: false,
    max_concurrent: 8,
  },
};

const VoiceAgentConfig: React.FC = () => {
  const [configs, setConfigs] = useState<VoiceAgentConfigType[]>([]);
  const [currentConfig, setCurrentConfig] = useState<VoiceAgentConfigType | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();

  // Watch STT/TTS backend selection for conditional fields
  const sttBackend = Form.useWatch('stt.backend', form);
  const ttsBackend = Form.useWatch('tts.backend', form);
  const hbAsrBackend = Form.useWatch('hb.asr_backend', form);

  const loadConfigs = useCallback(async () => {
    setLoading(true);
    try {
      const configResp = await getVoiceAgentConfigs();
      setConfigs(configResp.configs || []);

      const active = configResp.configs?.find((c) => c.is_active) || configResp.configs?.[0];
      if (active) {
        setCurrentConfig(active);
        form.setFieldsValue(flattenConfig(active));
      }
    } catch (err) {
      message.error('Failed to load voice agent configs');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, [form]);

  useEffect(() => {
    loadConfigs();
  }, [loadConfigs]);

  const flattenConfig = (config: VoiceAgentConfigType) => {
    const vs = config.voice_settings || {};
    const hb = vs.heartbeat || {};
    const stt = vs.stt as Record<string, unknown> | undefined;
    const tts = vs.tts as Record<string, unknown> | undefined;
    return {
      name: config.name,
      is_active: config.is_active,
      // STT: support both old-format (vadasr_*) and new-format (openai_whisper_* / elevenlabs_*)
      'stt.backend': stt?.backend,
      'stt.asr_backend': stt?.asr_backend ?? stt?.vadasr_asr_backend ?? 'sensevoice',
      'stt.url': stt?.url ?? stt?.vadasr_url,
      'stt.api_key': stt?.api_key ?? stt?.openai_whisper_stt_api_key ?? stt?.elevenlabs_stt_api_key ?? stt?.dashscope_stt_api_key,
      'stt.model': stt?.model ?? stt?.openai_whisper_stt_model ?? stt?.elevenlabs_stt_model ?? stt?.dashscope_stt_model ?? 'whisper-1',
      'stt.language': stt?.language ?? stt?.openai_whisper_stt_language ?? 'zh',
      'stt.language_code': stt?.language_code ?? stt?.elevenlabs_stt_language_code ?? '',
      'stt.timeout': stt?.timeout ?? stt?.vadasr_timeout ?? stt?.openai_whisper_stt_timeout ?? stt?.elevenlabs_stt_timeout ?? stt?.dashscope_stt_timeout ?? 30,
      'stt.block_duration_ms': stt?.block_duration_ms ?? stt?.vadasr_block_duration_ms ?? 500,
      'stt.sample_rate': stt?.sample_rate ?? stt?.dashscope_stt_sample_rate ?? 16000,
      'stt.language_hints': stt?.language_hints ?? stt?.dashscope_stt_language_hints ?? 'zh,en',
      'stt.voice_id': stt?.voice_id ?? stt?.elevenlabs_tts_voice_id ?? '21m00Tcm4TlvDq8ikWAM',
      'stt.output_format': stt?.output_format ?? stt?.elevenlabs_tts_output_format ?? 'pcm_16000',
      // TTS: support both old-format (omnivoice_tts_*) and new-format (openai_tts_* / elevenlabs_*)
      'tts.backend': tts?.backend,
      'tts.base_url': tts?.base_url ?? tts?.omnivoice_tts_base_url ?? tts?.openai_tts_base_url,
      'tts.api_key': tts?.api_key ?? tts?.openai_tts_api_key ?? tts?.elevenlabs_tts_api_key ?? tts?.dashscope_tts_api_key,
      'tts.model': tts?.model ?? tts?.openai_tts_model ?? tts?.elevenlabs_tts_model ?? tts?.dashscope_tts_model ?? 'tts-1',
      'tts.voice': tts?.voice ?? tts?.openai_tts_voice ?? tts?.dashscope_tts_voice ?? 'alloy',
      'tts.voice_id': tts?.voice_id ?? tts?.elevenlabs_tts_voice_id ?? '21m00Tcm4TlvDq8ikWAM',
      'tts.speed': tts?.speed ?? tts?.openai_tts_speed ?? 1.0,
      'tts.timeout': tts?.timeout ?? tts?.openai_tts_timeout ?? tts?.elevenlabs_tts_timeout ?? tts?.dashscope_tts_timeout ?? 30,
      'tts.sample_rate': tts?.sample_rate ?? tts?.openai_tts_sample_rate ?? 16000,
      'tts.num_step': tts?.num_step ?? tts?.omnivoice_tts_num_step,
      'tts.output_format': tts?.output_format ?? tts?.elevenlabs_tts_output_format ?? 'pcm_16000',
      'tts.blocksize': tts?.blocksize ?? tts?.elevenlabs_tts_blocksize ?? tts?.dashscope_tts_blocksize ?? 512,
      'vad.thresh': vs.vad?.thresh,
      'vad.min_silence_ms': vs.vad?.min_silence_ms,
      'vad.min_speech_ms': vs.vad?.min_speech_ms,
      'vad.speech_pad_ms': vs.vad?.speech_pad_ms,
      'vad.sample_rate': vs.vad?.sample_rate ?? 16000,
      enable_barge_in: vs.enable_barge_in,
      enable_heartbeat_interaction: vs.enable_heartbeat_interaction,
      'hb.mode': hb.mode,
      'hb.asr_backend': hb.asr_backend ?? 'sensevoice',
      'hb.model_name': hb.model_name,
      'hb.base_url': hb.base_url,
      'hb.api_key': hb.api_key,
      'hb.sensevoice_url': hb.sensevoice_url,
      'hb.sensevoice_timeout': hb.sensevoice_timeout,
      'hb.qwen3_asr_base_url': hb.qwen3_asr_base_url,
      'hb.qwen3_asr_model_name': hb.qwen3_asr_model_name,
      'hb.qwen3_asr_timeout': hb.qwen3_asr_timeout,
      'hb.dashscope_asr_api_key': hb.dashscope_asr_api_key,
      'hb.dashscope_asr_model': hb.dashscope_asr_model ?? 'paraformer-realtime-v2',
      'hb.dashscope_asr_language_hints': hb.dashscope_asr_language_hints ?? 'zh,en',
      'hb.whisper_asr_url': hb.whisper_asr_url,
      'hb.whisper_asr_api_key': hb.whisper_asr_api_key,
      'hb.whisper_asr_model': hb.whisper_asr_model ?? 'whisper-1',
      'hb.whisper_asr_language': hb.whisper_asr_language ?? 'zh',
      'hb.block_duration_ms': hb.block_duration_ms,
      'hb.request_timeout_s': hb.request_timeout_s,
      'hb.max_heartbeat_entries': hb.max_heartbeat_entries,
      'hb.prompt_version': hb.prompt_version,
      'hb.disable_thinking': hb.disable_thinking,
      'hb.blocking': hb.blocking,
      'hb.max_concurrent': hb.max_concurrent,
    };
  };

  const unflattenConfig = (values: Record<string, unknown>): Partial<VoiceAgentConfigType> => {
    const sttBackend = values['stt.backend'] as string;
    const ttsBackend = values['tts.backend'] as string;
    const voiceSettings: VoiceSettings = {
      stt: {
        backend: sttBackend,
        asr_backend: values['stt.asr_backend'] as string,
        url: values['stt.url'] as string,
        api_key: values['stt.api_key'] as string,
        model: values['stt.model'] as string,
        language: values['stt.language'] as string,
        language_code: values['stt.language_code'] as string,
        timeout: values['stt.timeout'] as number,
        block_duration_ms: values['stt.block_duration_ms'] as number,
        sample_rate: values['stt.sample_rate'] as number,
        language_hints: values['stt.language_hints'] as string,
        voice_id: values['stt.voice_id'] as string,
        output_format: values['stt.output_format'] as string,
      },
      tts: {
        backend: ttsBackend,
        base_url: values['tts.base_url'] as string,
        api_key: values['tts.api_key'] as string,
        model: values['tts.model'] as string,
        voice: values['tts.voice'] as string,
        voice_id: values['tts.voice_id'] as string,
        speed: values['tts.speed'] as number,
        timeout: values['tts.timeout'] as number,
        sample_rate: values['tts.sample_rate'] as number,
        num_step: values['tts.num_step'] as number,
        output_format: values['tts.output_format'] as string,
        blocksize: values['tts.blocksize'] as number,
      },
      vad: {
        thresh: values['vad.thresh'] as number,
        min_silence_ms: values['vad.min_silence_ms'] as number,
        min_speech_ms: values['vad.min_speech_ms'] as number,
        speech_pad_ms: values['vad.speech_pad_ms'] as number,
        sample_rate: values['vad.sample_rate'] as number,
      },
      enable_barge_in: values.enable_barge_in as boolean,
      enable_heartbeat_interaction: values.enable_heartbeat_interaction as boolean,
      heartbeat: {
        mode: values['hb.mode'] as string,
        asr_backend: values['hb.asr_backend'] as string,
        model_name: values['hb.model_name'] as string,
        base_url: values['hb.base_url'] as string,
        api_key: values['hb.api_key'] as string,
        sensevoice_url: values['hb.sensevoice_url'] as string,
        sensevoice_timeout: values['hb.sensevoice_timeout'] as number,
        qwen3_asr_base_url: values['hb.qwen3_asr_base_url'] as string,
        qwen3_asr_model_name: values['hb.qwen3_asr_model_name'] as string,
        qwen3_asr_timeout: values['hb.qwen3_asr_timeout'] as number,
        dashscope_asr_api_key: values['hb.dashscope_asr_api_key'] as string,
        dashscope_asr_model: values['hb.dashscope_asr_model'] as string,
        dashscope_asr_language_hints: values['hb.dashscope_asr_language_hints'] as string,
        whisper_asr_url: values['hb.whisper_asr_url'] as string,
        whisper_asr_api_key: values['hb.whisper_asr_api_key'] as string,
        whisper_asr_model: values['hb.whisper_asr_model'] as string,
        whisper_asr_language: values['hb.whisper_asr_language'] as string,
        block_duration_ms: values['hb.block_duration_ms'] as number,
        request_timeout_s: values['hb.request_timeout_s'] as number,
        max_heartbeat_entries: values['hb.max_heartbeat_entries'] as number,
        prompt_version: values['hb.prompt_version'] as string,
        disable_thinking: values['hb.disable_thinking'] as boolean,
        blocking: values['hb.blocking'] as boolean,
        max_concurrent: values['hb.max_concurrent'] as number,
      },
    };
    return {
      name: values.name as string,
      is_active: values.is_active as boolean,
      voice_settings: voiceSettings,
    };
  };

  const handleSave = async () => {
    try {
      const values = await form.validateFields();
      setSaving(true);
      const payload = unflattenConfig(values);
      if (currentConfig) {
        await updateVoiceAgentConfig(currentConfig.id, payload);
        message.success('Voice agent config updated');
      } else {
        const created = await createVoiceAgentConfig(payload as never);
        message.success('Voice agent config created');
        setCurrentConfig(created);
      }
      await loadConfigs();
    } catch (err) {
      if (err && typeof err === 'object' && 'errorFields' in err) return;
      message.error('Failed to save voice agent config');
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const handleCreateNew = () => {
    setCurrentConfig(null);
    form.setFieldsValue(flattenConfig({
      id: 0,
      name: 'default',
      tenant_id: 'default',
      is_active: true,
      voice_settings: DEFAULT_VOICE_SETTINGS,
      gmt_create: '',
      gmt_modified: '',
    }));
  };

  const handleDelete = async () => {
    if (!currentConfig) return;
    try {
      setSaving(true);
      await deleteVoiceAgentConfig(currentConfig.id);
      message.success('Voice agent config deactivated');
      setCurrentConfig(null);
      await loadConfigs();
    } catch (err) {
      message.error('Failed to delete config');
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const handleSelectConfig = (id: number) => {
    const config = configs.find((c) => c.id === id);
    if (config) {
      setCurrentConfig(config);
      form.setFieldsValue(flattenConfig(config));
    }
  };

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" />
      </div>
    );
  }

  const tabItems = [
    {
      key: 'asr_tts',
      label: (
        <span>
          <AudioOutlined /> ASR / TTS
        </span>
      ),
      forceRender: true,
      children: (
        <>
          <Divider orientation="left">STT (Speech-to-Text)</Divider>
          <Form.Item
            name="stt.backend"
            label={labelWithTip('STT Backend', '语音识别后端引擎。openai_whisper 兼容 OpenAI Whisper API（推荐）；elevenlabs 为 ElevenLabs STT；vadasr 基于 VAD+ASR 分段识别；qwen3_asr 为 Qwen3 流式识别。')}
          >
            <Select
              options={[
                { value: 'openai_whisper', label: 'OpenAI Whisper (推荐)' },
                { value: 'dashscope', label: '阿里百炼 (DashScope)' },
                { value: 'elevenlabs', label: 'ElevenLabs' },
                { value: 'vadasr', label: 'VADASR (SenseVoice)' },
                { value: 'qwen3_asr', label: 'Qwen3 ASR' },
                { value: 'qwen3_asr_streaming', label: 'Qwen3 ASR Streaming' },
              ]}
            />
          </Form.Item>

          {/* ElevenLabs STT specific fields */}
          {sttBackend === 'elevenlabs' && (
            <>
              <Form.Item
                name="stt.api_key"
                label={labelWithTip('API Key', 'ElevenLabs API Key（xi-api-key）。在 https://elevenlabs.io/app/settings/api-keys 获取。')}
              >
                <Input.Password placeholder="sk_..." />
              </Form.Item>
              <Form.Item
                name="stt.model"
                label={labelWithTip('Model', 'ElevenLabs STT 模型，例如 scribe_v1。')}
              >
                <Input placeholder="scribe_v1" />
              </Form.Item>
              <Form.Item
                name="stt.language_code"
                label={labelWithTip('Language Code', '语言代码提示（可选），例如 zh、en、ms。留空自动检测。')}
              >
                <Input placeholder="（留空自动检测）" />
              </Form.Item>
              <Form.Item
                name="stt.timeout"
                label={labelWithTip('Timeout (s)', '单次 STT 识别请求的超时时间（秒）。')}
              >
                <InputNumber min={1} max={60} step={1} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          {/* DashScope STT specific fields */}
          {sttBackend === 'dashscope' && (
            <>
              <Form.Item
                name="stt.api_key"
                label={labelWithTip('API Key', 'DashScope API Key。在 https://dashscope.console.aliyun.com/apiKey 获取。')}
              >
                <Input.Password placeholder="sk-..." />
              </Form.Item>
              <Form.Item
                name="stt.model"
                label={labelWithTip('Model', 'Paraformer 模型名称。推荐 paraformer-realtime-v2。')}
              >
                <Input placeholder="paraformer-realtime-v2" />
              </Form.Item>
              <Form.Item
                name="stt.sample_rate"
                label={labelWithTip('Sample Rate (Hz)', '音频采样率。默认 16000。')}
              >
                <InputNumber min={8000} max={48000} step={8000} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item
                name="stt.language_hints"
                label={labelWithTip('Language Hints', '逗号分隔的语言代码，例如 zh,en。仅 paraformer-realtime-v2 支持。')}
              >
                <Input placeholder="zh,en" />
              </Form.Item>
              <Form.Item
                name="stt.timeout"
                label={labelWithTip('Timeout (s)', '单次 STT 识别请求的超时时间（秒）。')}
              >
                <InputNumber min={1} max={60} step={1} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          {/* OpenAI Whisper specific fields */}
          {sttBackend === 'openai_whisper' && (
            <>
              <Form.Item
                name="stt.url"
                label={labelWithTip('Whisper API URL', 'OpenAI Whisper API 端点地址，例如 https://api.openai.com/v1/audio/transcriptions')}
              >
                <Input placeholder="https://api.openai.com/v1/audio/transcriptions" />
              </Form.Item>
              <Form.Item
                name="stt.api_key"
                label={labelWithTip('API Key', 'OpenAI Whisper API 密钥（自部署服务可留空）。')}
              >
                <Input.Password placeholder="sk-..." />
              </Form.Item>
              <Form.Item
                name="stt.model"
                label={labelWithTip('Model', 'Whisper 模型名称，例如 whisper-1 或 whisper-large-v3。')}
              >
                <Input placeholder="whisper-1" />
              </Form.Item>
              <Form.Item
                name="stt.language"
                label={labelWithTip('Language', '默认语言代码，例如 zh（中文）或 en（英文）。')}
              >
                <Input placeholder="zh" />
              </Form.Item>
              <Form.Item
                name="stt.timeout"
                label={labelWithTip('Timeout (s)', '单次 ASR 识别请求的超时时间（秒）。')}
              >
                <InputNumber min={1} max={60} step={1} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          {/* VADASR / SenseVoice specific fields */}
          {(sttBackend === 'vadasr' || !sttBackend) && (
            <>
              <Form.Item
                name="stt.asr_backend"
                label={labelWithTip('ASR Backend', 'VADASR 模式下使用的 ASR 引擎：sensevoice 或 qwen3。')}
              >
                <Select
                  options={[
                    { value: 'sensevoice', label: 'SenseVoice' },
                    { value: 'qwen3', label: 'Qwen3 ASR' },
                  ]}
                />
              </Form.Item>
              <Form.Item
                name="stt.url"
                label={labelWithTip('ASR URL', 'SenseVoice ASR 服务的 HTTP 接口地址。')}
              >
                <Input placeholder="https://..." />
              </Form.Item>
              <Form.Item
                name="stt.timeout"
                label={labelWithTip('ASR Timeout (s)', '单次 ASR 识别请求的超时时间（秒）。超过此时间未响应将放弃当前片段。')}
              >
                <InputNumber min={1} max={60} step={1} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item
                name="stt.block_duration_ms"
                label={labelWithTip('ASR Block Duration (ms)', 'ASR 触发间隔（毫秒），每积累此时长的新音频触发一次识别。')}
              >
                <InputNumber min={100} max={2000} step={100} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          <Divider orientation="left">TTS (Text-to-Speech)</Divider>
          <Form.Item
            name="tts.backend"
            label={labelWithTip('TTS Backend', '语音合成后端引擎。openai_tts 兼容 OpenAI TTS API（推荐）；elevenlabs 为 ElevenLabs TTS；omnivoice 为本地 OmniVoice 服务；qwen3_tts 为 Qwen3 TTS。')}
          >
            <Select
              options={[
                { value: 'openai_tts', label: 'OpenAI TTS (推荐)' },
                { value: 'dashscope', label: '阿里百炼 (DashScope)' },
                { value: 'elevenlabs', label: 'ElevenLabs' },
                { value: 'omnivoice', label: 'OmniVoice' },
                { value: 'qwen3_tts', label: 'Qwen3 TTS' },
                { value: 'qwen3_tts_streaming', label: 'Qwen3 TTS Streaming' },
              ]}
            />
          </Form.Item>

          {/* ElevenLabs TTS specific fields */}
          {ttsBackend === 'elevenlabs' && (
            <>
              <Form.Item
                name="tts.api_key"
                label={labelWithTip('API Key', 'ElevenLabs API Key（xi-api-key）。在 https://elevenlabs.io/app/settings/api-keys 获取。')}
              >
                <Input.Password placeholder="sk_..." />
              </Form.Item>
              <Form.Item
                name="tts.voice_id"
                label={labelWithTip('Voice ID', 'ElevenLabs 声音 ID。在 https://elevenlabs.io/app/voice-library 选择声音，URL 中的 ID 即是。默认 Rachel。')}
              >
                <Input placeholder="21m00Tcm4TlvDq8ikWAM" />
              </Form.Item>
              <Form.Item
                name="tts.model"
                label={labelWithTip('Model', 'ElevenLabs TTS 模型，例如 eleven_multilingual_v2（支持中文）、eleven_turbo_v2_5（更快）。')}
              >
                <Input placeholder="eleven_multilingual_v2" />
              </Form.Item>
              <Form.Item
                name="tts.output_format"
                label={labelWithTip('Output Format', '输出音频格式。pcm_16000 与管线匹配；pcm_22050/24000/44100 为更高采样率。')}
              >
                <Select
                  options={[
                    { value: 'pcm_16000', label: 'PCM 16000 Hz (推荐)' },
                    { value: 'pcm_22050', label: 'PCM 22050 Hz' },
                    { value: 'pcm_24000', label: 'PCM 24000 Hz' },
                    { value: 'pcm_44100', label: 'PCM 44100 Hz' },
                  ]}
                />
              </Form.Item>
              <Form.Item
                name="tts.timeout"
                label={labelWithTip('Timeout (s)', 'TTS 请求超时时间（秒）。')}
              >
                <InputNumber min={1} max={120} step={1} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item
                name="tts.blocksize"
                label={labelWithTip('Blocksize', '音频流式输出的块大小（采样数），影响播放平滑度。')}
              >
                <InputNumber min={128} max={4096} step={128} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          {/* DashScope TTS specific fields */}
          {ttsBackend === 'dashscope' && (
            <>
              <Form.Item
                name="tts.api_key"
                label={labelWithTip('API Key', 'DashScope API Key。在 https://dashscope.console.aliyun.com/apiKey 获取。')}
              >
                <Input.Password placeholder="sk-..." />
              </Form.Item>
              <Form.Item
                name="tts.model"
                label={labelWithTip('Model', 'CosyVoice 模型名称。推荐 cosyvoice-v1。')}
              >
                <Input placeholder="cosyvoice-v1" />
              </Form.Item>
              <Form.Item
                name="tts.voice"
                label={labelWithTip('Voice', '音色名称。例如 longxiaochun（女声）、longxiaoxia、longxiaofei 等。')}
              >
                <Input placeholder="longxiaochun" />
              </Form.Item>
              <Form.Item
                name="tts.sample_rate"
                label={labelWithTip('Sample Rate (Hz)', '输出音频采样率。默认 16000。')}
              >
                <InputNumber min={8000} max={48000} step={8000} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item
                name="tts.timeout"
                label={labelWithTip('Timeout (s)', 'TTS 请求超时时间（秒）。')}
              >
                <InputNumber min={1} max={120} step={1} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item
                name="tts.blocksize"
                label={labelWithTip('Blocksize', '音频流式输出的块大小（采样数），影响播放平滑度。')}
              >
                <InputNumber min={128} max={4096} step={128} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          {/* OpenAI TTS specific fields */}
          {ttsBackend === 'openai_tts' && (
            <>
              <Form.Item
                name="tts.base_url"
                label={labelWithTip('TTS Base URL', 'OpenAI TTS API 基础地址，例如 https://api.openai.com/v1')}
              >
                <Input placeholder="https://api.openai.com/v1" />
              </Form.Item>
              <Form.Item
                name="tts.api_key"
                label={labelWithTip('API Key', 'OpenAI TTS API 密钥（自部署服务可留空）。')}
              >
                <Input.Password placeholder="sk-..." />
              </Form.Item>
              <Form.Item
                name="tts.model"
                label={labelWithTip('Model', 'TTS 模型名称，例如 tts-1 或 tts-1-hd。')}
              >
                <Input placeholder="tts-1" />
              </Form.Item>
              <Form.Item
                name="tts.voice"
                label={labelWithTip('Voice', '语音名称，例如 alloy, echo, fable, onyx, nova, shimmer。')}
              >
                <Input placeholder="alloy" />
              </Form.Item>
              <Form.Item
                name="tts.speed"
                label={labelWithTip('Speed', '语速倍数（0.25 到 4.0）。')}
              >
                <InputNumber min={0.25} max={4.0} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item
                name="tts.timeout"
                label={labelWithTip('Timeout (s)', 'TTS 请求超时时间（秒）。')}
              >
                <InputNumber min={1} max={120} step={1} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item
                name="tts.sample_rate"
                label={labelWithTip('Sample Rate (Hz)', '输出音频采样率（Hz）。')}
              >
                <InputNumber min={8000} max={48000} step={1000} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          {/* OmniVoice specific fields */}
          {(ttsBackend === 'omnivoice' || !ttsBackend) && (
            <>
              <Form.Item
                name="tts.base_url"
                label={labelWithTip('TTS Base URL', 'OmniVoice TTS 服务的 HTTP 接口地址。')}
              >
                <Input placeholder="http://localhost:8864" />
              </Form.Item>
              <Form.Item
                name="tts.num_step"
                label={labelWithTip('TTS Num Steps', '语音合成的推理步数。步数越多合成质量越高但延迟越大，推荐 32。')}
              >
                <InputNumber min={1} max={256} step={1} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          {/* Qwen3 TTS specific fields */}
          {(ttsBackend === 'qwen3_tts' || ttsBackend === 'qwen3_tts_streaming') && (
            <>
              <Form.Item
                name="tts.base_url"
                label={labelWithTip('TTS Base URL', 'Qwen3 TTS 服务的 OpenAI 兼容接口地址。')}
              >
                <Input placeholder="http://..." />
              </Form.Item>
            </>
          )}
        </>
      ),
    },
    {
      key: 'vad',
      label: (
        <span>
          <ControlOutlined /> VAD
        </span>
      ),
      forceRender: true,
      children: (
        <>
          <Form.Item
            name="vad.thresh"
            label={labelWithTip('Threshold', '语音检测阈值（0-1）。值越低越灵敏，容易检测到轻微声音；值越高要求更大音量才判定为语音。')}
          >
            <InputNumber min={0} max={1} step={0.1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="vad.min_silence_ms"
            label={labelWithTip('Min Silence (ms)', '判定用户说话结束所需的最小静音时长。静音超过此时间后触发 ASR 识别。')}
          >
            <InputNumber min={100} max={5000} step={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="vad.min_speech_ms"
            label={labelWithTip('Min Speech (ms)', '判定为有效语音的最短时长。短于此值的音频片段将被忽略，用于过滤噪声。')}
          >
            <InputNumber min={50} max={2000} step={50} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="vad.speech_pad_ms"
            label={labelWithTip('Speech Pad (ms)', '语音片段前后填充的静音时长。确保 ASR 能获取完整语音上下文。')}
          >
            <InputNumber min={0} max={1000} step={50} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="vad.sample_rate"
            label={labelWithTip('Sample Rate (Hz)', '音频采样率（Hz）。默认 16000，通常不需要修改。')}
          >
            <InputNumber min={8000} max={48000} step={1000} style={{ width: '100%' }} />
          </Form.Item>
        </>
      ),
    },
    {
      key: 'behavior',
      label: 'Behavior',
      forceRender: true,
      children: (
        <>
          <Form.Item
            name="enable_barge_in"
            label={labelWithTip('Enable Barge-in', '允许用户在 AI 回复播放过程中直接说话打断 AI，立即进入新一轮对话。')}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="enable_heartbeat_interaction"
            label={labelWithTip('Enable Heartbeat Interaction', '启用心跳交互：在用户说话的间隙，AI 主动生成简短回应（如"嗯"、"好的"），让对话更自然。')}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
        </>
      ),
    },
    {
      key: 'heartbeat',
      label: (
        <span>
          <ClockCircleOutlined /> Heartbeat
        </span>
      ),
      forceRender: true,
      children: (
        <>
          <Form.Item
            name="hb.mode"
            label={labelWithTip('Mode', '心跳交互模式。streaming_asr 为流式 ASR 模式，在用户说话过程中实时生成心跳回应。')}
          >
            <Select
              options={[
                { value: 'streaming_asr', label: 'Streaming ASR' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="hb.model_name"
            label={labelWithTip('Model Name', '心跳交互使用的 LLM 模型名称，可与主对话模型不同。')}
          >
            <Input placeholder="Qwen3.5-122B-A10B" />
          </Form.Item>
          <Form.Item
            name="hb.base_url"
            label={labelWithTip('Base URL', '心跳 LLM 服务的 API 地址。可指向与主对话不同的模型服务。')}
          >
            <Input placeholder="https://..." />
          </Form.Item>
          <Form.Item
            name="hb.api_key"
            label={labelWithTip('API Key', '心跳 LLM 服务的 API 密钥。')}
          >
            <Input.Password placeholder="sk-..." />
          </Form.Item>
          <Form.Item
            name="hb.asr_backend"
            label={labelWithTip('ASR Backend', '心跳 ASR 后端服务。需与已部署的 ASR 服务匹配。')}
          >
            <Select
              options={[
                { value: 'sensevoice', label: 'SenseVoice' },
                { value: 'qwen3', label: 'Qwen3-ASR (vLLM)' },
                { value: 'dashscope', label: 'DashScope Paraformer' },
                { value: 'openai_whisper', label: 'OpenAI Whisper' },
              ]}
            />
          </Form.Item>

          {/* SenseVoice fields */}
          {(hbAsrBackend === 'sensevoice' || !hbAsrBackend) && (
            <>
              <Form.Item
                name="hb.sensevoice_url"
                label={labelWithTip('SenseVoice URL', '心跳 ASR 使用的 SenseVoice 服务地址，用于心跳期间的快速语音识别。')}
              >
                <Input placeholder="https://..." />
              </Form.Item>
              <Form.Item
                name="hb.sensevoice_timeout"
                label={labelWithTip('SenseVoice Timeout (s)', '心跳 ASR 识别的超时时间（秒）。')}
              >
                <InputNumber min={1} max={60} step={1} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          {/* Qwen3-ASR fields */}
          {hbAsrBackend === 'qwen3' && (
            <>
              <Form.Item
                name="hb.qwen3_asr_base_url"
                label={labelWithTip('Qwen3 Base URL', 'Qwen3-ASR vLLM 服务地址。')}
              >
                <Input placeholder="http://localhost:8901" />
              </Form.Item>
              <Form.Item
                name="hb.qwen3_asr_model_name"
                label={labelWithTip('Qwen3 Model', 'Qwen3-ASR 模型名称。')}
              >
                <Input placeholder="Qwen3-ASR-1.7B" />
              </Form.Item>
              <Form.Item
                name="hb.qwen3_asr_timeout"
                label={labelWithTip('Qwen3 Timeout (s)', 'Qwen3-ASR 请求超时时间（秒）。')}
              >
                <InputNumber min={1} max={120} step={1} style={{ width: '100%' }} />
              </Form.Item>
            </>
          )}

          {/* DashScope fields */}
          {hbAsrBackend === 'dashscope' && (
            <>
              <Form.Item
                name="hb.dashscope_asr_api_key"
                label={labelWithTip('DashScope API Key', 'DashScope (阿里百炼) API 密钥。')}
              >
                <Input.Password placeholder="sk-..." />
              </Form.Item>
              <Form.Item
                name="hb.dashscope_asr_model"
                label={labelWithTip('DashScope Model', 'DashScope Paraformer 模型名称。')}
              >
                <Input placeholder="paraformer-realtime-v2" />
              </Form.Item>
              <Form.Item
                name="hb.dashscope_asr_language_hints"
                label={labelWithTip('Language Hints', '识别语言提示，逗号分隔。')}
              >
                <Input placeholder="zh,en" />
              </Form.Item>
            </>
          )}

          {/* OpenAI Whisper fields */}
          {hbAsrBackend === 'openai_whisper' && (
            <>
              <Form.Item
                name="hb.whisper_asr_url"
                label={labelWithTip('Whisper URL', 'OpenAI Whisper / 兼容转录 API 地址。')}
              >
                <Input placeholder="https://api.openai.com/v1/audio/transcriptions" />
              </Form.Item>
              <Form.Item
                name="hb.whisper_asr_api_key"
                label={labelWithTip('Whisper API Key', 'API 密钥。')}
              >
                <Input.Password placeholder="sk-..." />
              </Form.Item>
              <Form.Item
                name="hb.whisper_asr_model"
                label={labelWithTip('Whisper Model', '模型名称。')}
              >
                <Input placeholder="whisper-1" />
              </Form.Item>
              <Form.Item
                name="hb.whisper_asr_language"
                label={labelWithTip('Whisper Language', '识别语言代码。')}
              >
                <Input placeholder="zh" />
              </Form.Item>
            </>
          )}
          <Form.Item
            name="hb.block_duration_ms"
            label={labelWithTip('Block Duration (ms)', '心跳 ASR 音频块大小（毫秒），影响识别粒度和延迟。')}
          >
            <InputNumber min={100} max={2000} step={100} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="hb.request_timeout_s"
            label={labelWithTip('Request Timeout (s)', '心跳 LLM 请求的超时时间（秒）。心跳需要快速响应，建议 3-5 秒。')}
          >
            <InputNumber min={1} max={30} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="hb.max_heartbeat_entries"
            label={labelWithTip('Max Heartbeat Entries', '保留的最大心跳历史条目数。超过后自动淘汰最早记录。')}
          >
            <InputNumber min={1} max={999} step={1} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item
            name="hb.prompt_version"
            label={labelWithTip('Prompt Version', '心跳使用的 Prompt 模板版本标识，对应 configs/ 目录下的 prompt 文件。')}
          >
            <Input placeholder="asri-v0" />
          </Form.Item>
          <Form.Item
            name="hb.disable_thinking"
            label={labelWithTip('Disable Thinking', '禁用 LLM 的 thinking/推理模式。心跳需要低延迟，建议开启。')}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="hb.blocking"
            label={labelWithTip('Blocking', '心跳是否以阻塞模式运行。阻塞模式会等待心跳完成后再继续主流程；非阻塞模式并行执行。')}
            valuePropName="checked"
          >
            <Switch />
          </Form.Item>
          <Form.Item
            name="hb.max_concurrent"
            label={labelWithTip('Max Concurrent', '心跳最大并发数。达到上限时，新的音频 block 会被立即丢弃，避免请求积压。')}
          >
            <InputNumber min={1} max={20} step={1} style={{ width: '100%' }} />
          </Form.Item>
        </>
      ),
    },
  ];

  return (
    <div style={{ maxWidth: 800 }}>
      <Card
        title={
          <Space>
            <Title level={5} style={{ margin: 0 }}>
              Voice Agent Configuration
            </Title>
            {currentConfig?.is_active && <Tag color="green">Active</Tag>}
          </Space>
        }
        extra={
          <Space>
            <Select
              style={{ width: 240 }}
              placeholder="Select config..."
              value={currentConfig?.id}
              onChange={handleSelectConfig}
              options={configs.map((c) => ({
                value: c.id,
                label: `${c.name}${c.is_active ? ' (active)' : ''}`,
              }))}
            />
            <Button icon={<PlusOutlined />} onClick={handleCreateNew}>
              New
            </Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical" initialValues={flattenConfig({
          id: 0,
          name: 'default',
          tenant_id: 'default',
          is_active: true,
          voice_settings: DEFAULT_VOICE_SETTINGS,
          gmt_create: '',
          gmt_modified: '',
        })}>
          <Form.Item name="name" label="Config Name" rules={[{ required: true }]}>
            <Input placeholder="default" />
          </Form.Item>
          <Form.Item name="is_active" label="Active" valuePropName="checked">
            <Switch />
          </Form.Item>

          <Tabs items={tabItems} />

          <Divider />

          <Space>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              loading={saving}
              onClick={handleSave}
            >
              {currentConfig ? 'Update' : 'Create'}
            </Button>
            {currentConfig && (
              <Button
                danger
                icon={<DeleteOutlined />}
                loading={saving}
                onClick={handleDelete}
              >
                Deactivate
              </Button>
            )}
          </Space>
        </Form>
      </Card>
    </div>
  );
};

export default VoiceAgentConfig;

from dataclasses import dataclass, field


@dataclass
class Qwen3LocalTTSHandlerArguments:
    qwen3_local_model_name: str = field(
        default="Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        metadata={"help": "The Qwen3-TTS model to use."},
    )
    qwen3_local_device: str = field(
        default="cuda",
        metadata={"help": "Device to run Qwen3-TTS on. Default is 'cuda'."},
    )
    qwen3_local_dtype: str = field(
        default="auto",
        metadata={"help": "Data type for inference. Default is 'auto'."},
    )
    qwen3_local_attn_implementation: str = field(
        default="eager",
        metadata={"help": "Attention implementation. Default is 'eager'."},
    )
    qwen3_local_ref_audio: str = field(
        default="handlers/tts/ref_audio.wav",
        metadata={"help": "Path to reference audio file for voice cloning."},
    )
    qwen3_local_ref_text: str = field(
        default="I'm confused why some people have super short timelines, yet at the same time are bullish on scaling up reinforcement learning atop LLMs. If we're actually close to a human-like learner, then this whole approach of training on verifiable outcomes.",
        metadata={"help": "Transcription of the reference audio."},
    )
    qwen3_local_speaker: str = field(
        default=None,
        metadata={"help": "Speaker name for CustomVoice models (optional)."},
    )
    qwen3_local_instruct: str = field(
        default=None,
        metadata={"help": "Instruction text for VoiceDesign models (optional)."},
    )
    qwen3_local_xvec_only: bool = field(
        default=False,
        metadata={"help": "Use x-vector only voice cloning mode. Default is False."},
    )
    qwen3_local_parity_mode: bool = field(
        default=False,
        metadata={"help": "Disable CUDA-graph streaming path. Default is False."},
    )
    qwen3_local_language: str = field(
        default="English",
        metadata={"help": "Target language for synthesis. Default is 'English'."},
    )
    qwen3_local_streaming_chunk_size: int = field(
        default=8,
        metadata={"help": "Codec steps per streaming chunk. Default is 8."},
    )
    qwen3_local_max_new_tokens: int = field(
        default=360,
        metadata={"help": "Maximum codec tokens to generate. Default is 360."},
    )
    qwen3_local_blocksize: int = field(
        default=512,
        metadata={"help": "Audio chunk size in samples. Default is 512."},
    )


@dataclass
class OmniVoiceTTSHandlerArguments:
    omnivoice_tts_base_url: str = field(
        default="http://localhost:8864",
        metadata={"help": "OmniVoice TTS service base URL."},
    )
    omnivoice_tts_ref_audio_path: str = field(
        default="",  # 从 Django Admin 配置读取
        metadata={"help": "Path to reference audio file for voice cloning."},
    )
    omnivoice_tts_ref_text: str = field(
        default="",  # 从 Django Admin 配置读取
        metadata={"help": "Reference text matching the reference audio."},
    )
    omnivoice_tts_num_step: int = field(
        default=None,
        metadata={"help": "Number of inference steps (None for server default)."},
    )
    omnivoice_tts_sample_rate: int = field(
        default=24000,
        metadata={"help": "Output audio sample rate in Hz."},
    )
    omnivoice_tts_device: str = field(
        default="cpu",
        metadata={"help": "Unused, kept for interface consistency."},
    )
    omnivoice_tts_blocksize: int = field(
        default=512,
        metadata={"help": "Audio chunk size in samples for streaming output."},
    )


@dataclass
class VoxCPM2TTSHandlerArguments:
    voxcpm2_tts_base_url: str = field(
        default=None,
        metadata={"help": "VoxCPM2/vLLM Omni OpenAI-compatible service base URL."},
    )
    voxcpm2_tts_model: str = field(
        default="openbmb/VoxCPM2",
        metadata={"help": "Model name sent to /v1/audio/speech."},
    )
    voxcpm2_tts_voice: str = field(
        default="customer_female_7_omnivoice",
        metadata={"help": "Precomputed voice name used by the VoxCPM2 service."},
    )
    voxcpm2_tts_api_key: str = field(
        default=None,
        metadata={"help": "Optional bearer token for the VoxCPM2 service."},
    )
    voxcpm2_tts_speed: float = field(
        default=1.0,
        metadata={"help": "Speech speed sent to /v1/audio/speech."},
    )
    voxcpm2_tts_timeout: float = field(
        default=60.0,
        metadata={"help": "HTTP timeout in seconds."},
    )
    voxcpm2_tts_sample_rate: int = field(
        default=16000,
        metadata={"help": "Pipeline output sample rate."},
    )
    voxcpm2_tts_blocksize: int = field(
        default=512,
        metadata={"help": "Audio chunk size in samples for pipeline output."},
    )
    voxcpm2_tts_warmup: bool = field(
        default=True,
        metadata={"help": "Run one startup request to verify the precomputed voice is loaded."},
    )
    voxcpm2_tts_warmup_text: str = field(
        default="你好，我是语音助手。",
        metadata={"help": "Warmup text used at startup."},
    )
    voxcpm2_tts_precompute_voice: bool = field(
        default=True,
        metadata={"help": "Register the configured voice through POST /v1/audio/voices if missing."},
    )
    voxcpm2_tts_require_precomputed_voice: bool = field(
        default=True,
        metadata={"help": "Fail startup when voxcpm2_tts_voice is not listed by /v1/audio/voices."},
    )
    voxcpm2_tts_ref_audio: str = field(
        default="",  # 从 Django Admin 配置读取
        metadata={"help": "Reference audio used to create the precomputed voice, or for explicit per-request cloning."},
    )
    voxcpm2_tts_ref_text: str = field(
        default=None,
        metadata={"help": "Optional reference transcript for per-request cloning."},
    )
    voxcpm2_tts_voice_consent: str = field(
        default="I have permission to use this voice sample.",
        metadata={"help": "Consent text required by the vLLM Omni voice upload API."},
    )
    voxcpm2_tts_speaker_description: str = field(
        default=None,
        metadata={"help": "Optional speaker description for voice registration."},
    )
    voxcpm2_tts_use_ref_audio_each_request: bool = field(
        default=False,
        metadata={"help": "Send ref_audio/ref_text on every request. Default false: use the precomputed voice name."},
    )


@dataclass
class Qwen3TTSHandlerArguments:
    qwen3_tts_base_url: str = field(
        default=None,
        metadata={"help": "Qwen3-TTS/vLLM Omni OpenAI-compatible service base URL."},
    )
    qwen3_tts_model: str = field(
        default=None,
        metadata={"help": "Model id returned by the Qwen3-TTS service /v1/models endpoint."},
    )
    qwen3_tts_voice: str = field(
        default="customer_female_7_omnivoice",
        metadata={"help": "Precomputed voice name used by the Qwen3-TTS service."},
    )
    qwen3_tts_api_key: str = field(
        default=None,
        metadata={"help": "Optional bearer token for the Qwen3-TTS service."},
    )
    qwen3_tts_speed: float = field(
        default=1.0,
        metadata={"help": "Speech speed sent to /v1/audio/speech."},
    )
    qwen3_tts_timeout: float = field(
        default=120.0,
        metadata={"help": "HTTP timeout in seconds."},
    )
    qwen3_tts_sample_rate: int = field(
        default=16000,
        metadata={"help": "Pipeline output sample rate."},
    )
    qwen3_tts_blocksize: int = field(
        default=512,
        metadata={"help": "Audio chunk size in samples for pipeline output."},
    )
    qwen3_tts_warmup: bool = field(
        default=True,
        metadata={"help": "Run one startup request to verify the precomputed voice is loaded."},
    )
    qwen3_tts_warmup_text: str = field(
        default="你好。",
        metadata={"help": "Warmup text used at startup."},
    )
    qwen3_tts_precompute_voice: bool = field(
        default=True,
        metadata={"help": "Register the configured voice through POST /v1/audio/voices if missing."},
    )
    qwen3_tts_require_precomputed_voice: bool = field(
        default=True,
        metadata={"help": "Fail startup when qwen3_tts_voice is not listed by /v1/audio/voices."},
    )
    qwen3_tts_ref_audio: str = field(
        default="",  # 从 Django Admin 配置读取
        metadata={"help": "Reference audio used to create the precomputed voice, or for explicit per-request cloning."},
    )
    qwen3_tts_ref_text: str = field(
        default=None,
        metadata={"help": "Optional reference transcript for voice registration or per-request cloning."},
    )
    qwen3_tts_voice_consent: str = field(
        default="I have permission to use this voice sample.",
        metadata={"help": "Consent text required by the vLLM Omni voice upload API."},
    )
    qwen3_tts_speaker_description: str = field(
        default=None,
        metadata={"help": "Optional speaker description for voice registration."},
    )
    qwen3_tts_use_ref_audio_each_request: bool = field(
        default=False,
        metadata={"help": "Send ref_audio/ref_text on every request. Default false: use the precomputed voice name."},
    )
    qwen3_tts_task_type: str = field(
        default="Base",
        metadata={"help": "Qwen3-TTS task type sent to /v1/audio/speech."},
    )
    qwen3_tts_language: str = field(
        default="Auto",
        metadata={"help": "Qwen3-TTS language hint sent to /v1/audio/speech."},
    )
    qwen3_tts_instructions: str = field(
        default=None,
        metadata={"help": "Optional style/emotion instruction sent to /v1/audio/speech."},
    )


@dataclass
class Qwen3TTSStreamingHandlerArguments:
    qwen3_tts_streaming_base_url: str = field(
        default=None,
        metadata={"help": "Qwen3-TTS/vLLM Omni OpenAI-compatible service base URL."},
    )
    qwen3_tts_streaming_model: str = field(
        default=None,
        metadata={"help": "Model id returned by the Qwen3-TTS service /v1/models endpoint."},
    )
    qwen3_tts_streaming_voice: str = field(
        default="customer_female_7_omnivoice",
        metadata={"help": "Precomputed voice name used by the Qwen3-TTS service."},
    )
    qwen3_tts_streaming_api_key: str = field(
        default=None,
        metadata={"help": "Optional bearer token for the Qwen3-TTS service."},
    )
    qwen3_tts_streaming_speed: float = field(
        default=1.0,
        metadata={"help": "Speech speed. Not sent by default in streaming mode because vLLM-Omni Qwen3-TTS does not support speed while streaming."},
    )
    qwen3_tts_streaming_timeout: float = field(
        default=120.0,
        metadata={"help": "HTTP timeout in seconds."},
    )
    qwen3_tts_streaming_sample_rate: int = field(
        default=16000,
        metadata={"help": "Pipeline output sample rate after streaming resampling."},
    )
    qwen3_tts_streaming_source_sample_rate: int = field(
        default=24000,
        metadata={"help": "Raw PCM sample rate produced by Qwen3-TTS streaming endpoint."},
    )
    qwen3_tts_streaming_blocksize: int = field(
        default=512,
        metadata={"help": "Audio chunk size in samples for pipeline output."},
    )
    qwen3_tts_streaming_network_chunk_bytes: int = field(
        default=4096,
        metadata={"help": "HTTP streaming read chunk size in bytes."},
    )
    qwen3_tts_streaming_idle_timeout: float = field(
        default=3.0,
        metadata={"help": "End a streaming TTS response after this many seconds without new audio, once audio has started."},
    )
    qwen3_tts_streaming_send_speed: bool = field(
        default=False,
        metadata={"help": "Send speed in streaming requests. Default false because vLLM-Omni docs say speed is unsupported for Qwen3-TTS streaming."},
    )
    qwen3_tts_streaming_warmup: bool = field(
        default=True,
        metadata={"help": "Run one startup request to verify the precomputed voice is loaded."},
    )
    qwen3_tts_streaming_warmup_text: str = field(
        default="你好。",
        metadata={"help": "Warmup text used at startup."},
    )
    qwen3_tts_streaming_precompute_voice: bool = field(
        default=True,
        metadata={"help": "Register the configured voice through POST /v1/audio/voices if missing."},
    )
    qwen3_tts_streaming_require_precomputed_voice: bool = field(
        default=True,
        metadata={"help": "Fail startup when qwen3_tts_streaming_voice is not listed by /v1/audio/voices."},
    )
    qwen3_tts_streaming_ref_audio: str = field(
        default="",  # 从 Django Admin 配置读取
        metadata={"help": "Reference audio used to create the precomputed voice, or for explicit per-request cloning."},
    )
    qwen3_tts_streaming_ref_text: str = field(
        default=None,
        metadata={"help": "Optional reference transcript for voice registration or per-request cloning."},
    )
    qwen3_tts_streaming_voice_consent: str = field(
        default="I have permission to use this voice sample.",
        metadata={"help": "Consent text required by the vLLM Omni voice upload API."},
    )
    qwen3_tts_streaming_speaker_description: str = field(
        default=None,
        metadata={"help": "Optional speaker description for voice registration."},
    )
    qwen3_tts_streaming_use_ref_audio_each_request: bool = field(
        default=False,
        metadata={"help": "Send ref_audio/ref_text on every request. Default false: use the precomputed voice name."},
    )
    qwen3_tts_streaming_task_type: str = field(
        default="Base",
        metadata={"help": "Qwen3-TTS task type sent to /v1/audio/speech."},
    )
    qwen3_tts_streaming_language: str = field(
        default="Auto",
        metadata={"help": "Qwen3-TTS language hint sent to /v1/audio/speech."},
    )
    qwen3_tts_streaming_instructions: str = field(
        default=None,
        metadata={"help": "Optional style/emotion instruction sent to /v1/audio/speech."},
    )

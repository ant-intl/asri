from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ModuleArguments:
    device: Optional[str] = field(
        default=None,
        metadata={"help": "If specified, overrides the device for all handlers."},
    )
    mode: Optional[str] = field(
        default="socket",
        metadata={
            "help": "The mode to run the pipeline in. Either 'local', 'socket', 'websocket', or 'realtime'. Default is 'socket'."
        },
    )
    local_mac_optimal_settings: bool = field(
        default=False,
        metadata={
            "help": "If specified, sets the optimal settings for Mac OS. Sets SenseVoice for STT, MLX LM for language model, and OmniVoice for TTS, with MPS device and local mode."
        },
    )
    stt: Optional[str] = field(
        default="whisper",
        metadata={
            "help": "The STT to use. Either 'whisper', 'whisper-mlx', 'mlx-audio-whisper', 'faster-whisper', 'parakeet-tdt', 'paraformer', 'sensevoice', 'qwen3', 'vadasr' (fake-streaming ASR, progressive during VAD), 'qwen3-asr-streaming' (native Qwen3-ASR streaming service), or 'allm' (replaces both STT and LLM with Qwen3-Omni). Default is 'whisper'."
        },
    )
    llm: Optional[str] = field(
        default="transformers",
        metadata={
            "help": "The LLM to use. Either 'transformers' or 'mlx-lm'. Default is 'transformers'"
        },
    )
    tts: Optional[str] = field(
        default=None,
        metadata={
            "help": "The TTS to use. Either 'omnivoice', 'qwen3_local', 'qwen3_tts', 'qwen3_tts_streaming', or 'voxcpm2'. Default is 'omnivoice'."
        },
    )
    log_level: str = field(
        default="info",
        metadata={
            "help": "Provide logging level. Example --log_level debug, default=info."
        },
    )
    enable_live_transcription: bool = field(
        default=False,
        metadata={
            "help": "Enable live transcription display while user is speaking (only works with parakeet-tdt on MLX/MPS)"
        },
    )
    live_transcription_update_interval: float = field(
        default=0.25,
        metadata={
            "help": "Update interval for live transcription in seconds (default: 0.25s = 250ms)"
        },
    )
    live_transcription_min_silence_ms: int = field(
        default=500,
        metadata={
            "help": "Minimum silence duration (ms) before ending speech when live transcription is enabled (default: 500ms)"
        },
    )
    enable_barge_in: bool = field(
        default=False,
        metadata={
            "help": "Enable barge-in (interruption detection during playback). Requires echo cancellation or headphones. Default is False."
        },
    )
    input_device: Optional[int] = field(
        default=None,
        metadata={
            "help": "Audio input device ID for local mode (see sounddevice query_devices). Default is system default."
        },
    )
    output_device: Optional[int] = field(
        default=None,
        metadata={
            "help": "Audio output device ID for local mode (see sounddevice query_devices). Default is system default."
        },
    )
    tools_module: Optional[str] = field(
        default=None,
        metadata={
            "help": "Python module path for server-side tool registration. The module must define a register_tools(registry) function. Example: 'tools.epos_tools'. When set, the agent loop is enabled: server-side tools are executed automatically without client round-trips."
        },
    )
    system_prompt_file: Optional[str] = field(
        default=None,
        metadata={
            "help": "Path to a text file containing the system prompt. When set, the file content overrides open_api_init_chat_prompt. Useful for keeping long prompts out of YAML."
        },
    )
    enable_heartbeat_interaction: bool = field(
        default=False,
        metadata={
            "help": "Enable the HeartBeat Interaction side-branch. When true, the heartbeat worker runs in parallel with STT and stores same-turn thinking/tool results for the main response."
        },
    )

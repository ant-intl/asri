from dataclasses import dataclass, field


@dataclass
class HeartbeatInteractionArguments:
    heartbeat_interaction_mode: str = field(
        default="omni",
        metadata={"help": "HeartBeat Interaction mode: 'omni' (audio model) or 'streaming_asr' (ASR + text LLM)."},
    )
    heartbeat_interaction_model_name: str = field(
        default="Qwen3-Omni-8B",
        metadata={"help": "Model name for the HeartBeat Interaction model."},
    )
    heartbeat_interaction_base_url: str = field(
        default="http://localhost:8906/v1",
        metadata={"help": "Base URL of the HeartBeat Interaction model API."},
    )
    heartbeat_interaction_api_key: str = field(
        default="dummy",
        metadata={"help": "API key for the HeartBeat Interaction model."},
    )
    heartbeat_interaction_block_duration_ms: int = field(
        default=500,
        metadata={"help": "Block duration in milliseconds for audio chunking."},
    )
    heartbeat_interaction_request_timeout_s: float = field(
        default=5.0,
        metadata={"help": "Request timeout in seconds for the HeartBeat Interaction model API call."},
    )
    heartbeat_interaction_max_heartbeat_entries: int = field(
        default=2,
        metadata={"help": "Maximum number of HeartBeat thinking entries cached per turn."},
    )
    heartbeat_interaction_prompt_version: str = field(
        default="asri-v0",
        metadata={"help": "Prompt template version. The current repository keeps only asri-v0."},
    )
    heartbeat_interaction_sensevoice_url: str = field(
        default="",
        metadata={"help": "SenseVoice ASR endpoint URL (streaming_asr mode)."},
    )
    heartbeat_interaction_sensevoice_timeout: float = field(
        default=10.0,
        metadata={"help": "SenseVoice ASR request timeout in seconds."},
    )
    heartbeat_interaction_asr_backend: str = field(
        default="sensevoice",
        metadata={"help": "ASR backend for streaming ASR handler: 'sensevoice' or 'qwen3'."},
    )
    heartbeat_interaction_qwen3_asr_base_url: str = field(
        default="",
        metadata={"help": "Qwen3-ASR vLLM endpoint base URL."},
    )
    heartbeat_interaction_qwen3_asr_model_name: str = field(
        default="",
        metadata={"help": "Qwen3-ASR model name/path for vLLM."},
    )
    heartbeat_interaction_qwen3_asr_timeout: float = field(
        default=30.0,
        metadata={"help": "Qwen3-ASR HTTP request timeout in seconds."},
    )
    heartbeat_interaction_interim_window_s: float = field(
        default=10.0,
        metadata={"help": "Sliding window size in seconds for streaming ASR interim calls."},
    )
    heartbeat_interaction_disable_thinking: bool = field(
        default=True,
        metadata={"help": "Disable thinking/reasoning in the text LLM (streaming_asr mode)."},
    )
    heartbeat_interaction_blocking: bool = field(
        default=True,
        metadata={
            "help": "Execution mode for both omni and streaming_asr: True = blocking "
                    "(synchronous model call per audio/text block); False = non-blocking "
                    "(worker threads + ordered-insert cache, recommended for throughput)."
        },
    )
    heartbeat_interaction_max_concurrent: int = field(
        default=8,
        metadata={
            "help": "Non-blocking mode only: maximum number of in-flight predict HTTP requests. "
                    "Acts as a client-side concurrency cap (Semaphore) so bursts of audio/text "
                    "blocks don't flood the upstream endpoint. New blocks are dropped immediately "
                    "when the cap is reached instead of waiting in a backlog."
        },
    )
    heartbeat_interaction_fd_mode: bool = field(
        default=False,
        metadata={
            "help": "Enable full-duplex-specific interrupt metadata in HeartBeat prompts. "
                    "When disabled, no interrupt metadata is injected."
        },
    )

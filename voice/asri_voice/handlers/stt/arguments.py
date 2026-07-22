from dataclasses import dataclass, field


@dataclass
class SenseVoiceSTTHandlerArguments:
    sensevoice_stt_url: str = field(
        default="",  # 从 Django Admin 配置或环境变量读取
        metadata={"help": "SenseVoice ASR API endpoint URL."},
    )
    sensevoice_stt_language: str = field(
        default="zh",
        metadata={"help": "Default language code for SenseVoice ASR output."},
    )
    sensevoice_stt_timeout: float = field(
        default=30.0,
        metadata={"help": "HTTP request timeout in seconds."},
    )


@dataclass
class Qwen3ASRArguments:
    qwen3_asr_base_url: str = field(
        default="",  # 从 Django Admin 配置或环境变量读取
        metadata={"help": "Qwen3-ASR vLLM endpoint base URL."},
    )
    qwen3_asr_model_name: str = field(
        default="",  # 从 Django Admin 配置或环境变量读取
        metadata={"help": "Qwen3-ASR model name/path for vLLM."},
    )
    qwen3_asr_timeout: float = field(
        default=30.0,
        metadata={"help": "HTTP request timeout in seconds."},
    )


@dataclass
class StreamingSenseVoiceHandlerArguments:
    vadasr_asr_backend: str = field(
        default="sensevoice",
        metadata={"help": "ASR backend for VADASR mode: 'sensevoice' or 'qwen3'."},
    )
    vadasr_url: str = field(
        default="",  # 从 Django Admin 配置或环境变量读取
        metadata={"help": "SenseVoice ASR endpoint URL (sensevoice backend)."},
    )
    vadasr_timeout: float = field(
        default=10.0,
        metadata={"help": "ASR request timeout in seconds (sensevoice backend)."},
    )
    vadasr_qwen3_asr_base_url: str = field(
        default="",  # 从 Django Admin 配置或环境变量读取
        metadata={"help": "Qwen3-ASR vLLM endpoint base URL (qwen3 backend)."},
    )
    vadasr_qwen3_asr_model_name: str = field(
        default="",  # 从 Django Admin 配置或环境变量读取
        metadata={"help": "Qwen3-ASR model name/path for vLLM."},
    )
    vadasr_qwen3_asr_timeout: float = field(
        default=30.0,
        metadata={"help": "HTTP request timeout in seconds (qwen3 backend)."},
    )
    vadasr_block_duration_ms: int = field(
        default=500,
        metadata={"help": "How often to trigger ASR (in ms of new audio)."},
    )
    vadasr_language: str = field(
        default="zh",
        metadata={"help": "Default language code for ASR output."},
    )


@dataclass
class Qwen3ASRStreamingArguments:
    qwen3_asr_streaming_base_url: str = field(
        default="http://127.0.0.1:8000",
        metadata={"help": "Qwen3-ASR native streaming service base URL."},
    )
    qwen3_asr_streaming_timeout: float = field(
        default=30.0,
        metadata={"help": "HTTP read timeout in seconds for Qwen3-ASR streaming requests."},
    )
    qwen3_asr_streaming_connect_timeout: float = field(
        default=5.0,
        metadata={"help": "HTTP connect timeout in seconds for Qwen3-ASR streaming requests."},
    )
    qwen3_asr_streaming_feed_duration_ms: int = field(
        default=500,
        metadata={"help": "How much new audio to send per native streaming chunk."},
    )
    qwen3_asr_streaming_final_reuse_interim_tail_ms: int = field(
        default=350,
        metadata={"help": "Reuse last interim transcript on TURN_END when unsent tail is no longer than this many milliseconds."},
    )
    qwen3_asr_streaming_language: str = field(
        default="zh",
        metadata={"help": "Default language code before Qwen3-ASR detects a language."},
    )
    qwen3_asr_streaming_serialize_requests: bool = field(
        default=True,
        metadata={"help": "Serialize HTTP requests to the same Qwen3-ASR streaming service to avoid non-thread-safe demo/model concurrency."},
    )

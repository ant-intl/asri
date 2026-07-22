"""OpenAI TTS handler arguments.

Supports OpenAI TTS API, Azure TTS, Edge-TTS-Server, and other
OpenAI-compatible /v1/audio/speech endpoints.
"""

from dataclasses import dataclass, field


@dataclass
class OpenAITTSHandlerArguments:
    openai_tts_base_url: str = field(
        default="",
        metadata={"help": "OpenAI TTS API base URL (e.g. https://api.openai.com/v1)."},
    )
    openai_tts_api_key: str = field(
        default="",
        metadata={"help": "API key for authentication (optional for self-hosted services)."},
    )
    openai_tts_model: str = field(
        default="tts-1",
        metadata={"help": "Model name to use (e.g. tts-1, tts-1-hd, tts-azure)."},
    )
    openai_tts_voice: str = field(
        default="alloy",
        metadata={"help": "Voice name to use (e.g. alloy, echo, fable, onyx, nova, shimmer)."},
    )
    openai_tts_speed: float = field(
        default=1.0,
        metadata={"help": "Speech speed multiplier (0.25 to 4.0)."},
    )
    openai_tts_timeout: float = field(
        default=30.0,
        metadata={"help": "HTTP request timeout in seconds."},
    )
    openai_tts_sample_rate: int = field(
        default=16000,
        metadata={"help": "Output audio sample rate in Hz."},
    )
    openai_tts_blocksize: int = field(
        default=512,
        metadata={"help": "Audio chunk size in samples for streaming output."},
    )

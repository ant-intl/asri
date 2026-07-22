"""OpenAI Whisper STT handler arguments.

Supports OpenAI Whisper API, faster-whisper-server, and other
OpenAI-compatible transcription endpoints.
"""

from dataclasses import dataclass, field


@dataclass
class OpenAIWhisperSTTArguments:
    openai_whisper_stt_url: str = field(
        default="",
        metadata={"help": "OpenAI Whisper API endpoint URL (e.g. https://api.openai.com/v1/audio/transcriptions)."},
    )
    openai_whisper_stt_api_key: str = field(
        default="",
        metadata={"help": "API key for authentication (optional for self-hosted services)."},
    )
    openai_whisper_stt_model: str = field(
        default="whisper-1",
        metadata={"help": "Model name to use (e.g. whisper-1, whisper-large-v3)."},
    )
    openai_whisper_stt_language: str = field(
        default="zh",
        metadata={"help": "Default language code for transcription output."},
    )
    openai_whisper_stt_timeout: float = field(
        default=30.0,
        metadata={"help": "HTTP request timeout in seconds."},
    )

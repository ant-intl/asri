"""ElevenLabs STT handler arguments.

Docs: https://elevenlabs.io/docs/api-reference/speech-to-text
"""

from dataclasses import dataclass, field


@dataclass
class ElevenLabsSTTArguments:
    elevenlabs_stt_api_key: str = field(
        default="",
        metadata={"help": "ElevenLabs API key (xi-api-key). Get one at https://elevenlabs.io/app/settings/api-keys"},
    )
    elevenlabs_stt_model: str = field(
        default="scribe_v1",
        metadata={"help": "Model name (e.g. scribe_v1)."},
    )
    elevenlabs_stt_language_code: str = field(
        default="",
        metadata={"help": "Language code hint (e.g. zh, en, ms). Leave empty for auto-detection."},
    )
    elevenlabs_stt_timeout: float = field(
        default=30.0,
        metadata={"help": "HTTP request timeout in seconds."},
    )

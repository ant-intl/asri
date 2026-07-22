"""ElevenLabs TTS handler arguments.

Docs: https://elevenlabs.io/docs/api-reference/text-to-speech
"""

from dataclasses import dataclass, field


@dataclass
class ElevenLabsTTSArguments:
    elevenlabs_tts_api_key: str = field(
        default="",
        metadata={"help": "ElevenLabs API key (xi-api-key). Get one at https://elevenlabs.io/app/settings/api-keys"},
    )
    elevenlabs_tts_voice_id: str = field(
        default="21m00Tcm4TlvDq8ikWAM",
        metadata={"help": "Voice ID from ElevenLabs voice library (e.g. Rachel, Adam, etc.)."},
    )
    elevenlabs_tts_model: str = field(
        default="eleven_multilingual_v2",
        metadata={"help": "Model name (e.g. eleven_multilingual_v2, eleven_turbo_v2_5)."},
    )
    elevenlabs_tts_output_format: str = field(
        default="pcm_16000",
        metadata={"help": "Output format: pcm_16000, pcm_22050, pcm_24000, pcm_44100, mp3_44100_128, mp3_44100_192."},
    )
    elevenlabs_tts_timeout: float = field(
        default=30.0,
        metadata={"help": "HTTP request timeout in seconds."},
    )
    elevenlabs_tts_blocksize: int = field(
        default=512,
        metadata={"help": "Audio chunk size in samples for streaming output."},
    )

"""DashScope (阿里百炼) TTS handler arguments.

Docs: https://help.aliyun.com/zh/model-studio/cosyvoice-websocket-api
"""

from dataclasses import dataclass, field


@dataclass
class DashScopeTTSArguments:
    dashscope_tts_api_key: str = field(
        default="",
        metadata={"help": "DashScope API Key. Get one at https://dashscope.console.aliyun.com/apiKey"},
    )
    dashscope_tts_model: str = field(
        default="cosyvoice-v1",
        metadata={"help": "Model name: cosyvoice-v1, cosyvoice-v2, etc."},
    )
    dashscope_tts_voice: str = field(
        default="longxiaochun",
        metadata={"help": "Voice name: longxiaochun, longxiaoxia, longxiaofei, etc."},
    )
    dashscope_tts_sample_rate: int = field(
        default=16000,
        metadata={"help": "Audio sample rate in Hz."},
    )
    dashscope_tts_blocksize: int = field(
        default=512,
        metadata={"help": "Audio chunk size in samples for streaming output."},
    )
    dashscope_tts_timeout: float = field(
        default=30.0,
        metadata={"help": "Request timeout in seconds."},
    )
    dashscope_tts_max_seconds: float = field(
        default=0.0,
        metadata={"help": "Max synthesis duration in seconds (0 = unlimited)."},
    )
    dashscope_tts_max_bytes: int = field(
        default=0,
        metadata={"help": "Max PCM bytes to emit (0 = unlimited)."},
    )

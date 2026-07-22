"""DashScope (阿里百炼) STT handler arguments.

Docs: https://help.aliyun.com/zh/model-studio/paraformer-real-time-speech-recognition-python-sdk
"""

from dataclasses import dataclass, field


@dataclass
class DashScopeSTTArguments:
    dashscope_stt_api_key: str = field(
        default="",
        metadata={"help": "DashScope API Key. Get one at https://dashscope.console.aliyun.com/apiKey"},
    )
    dashscope_stt_model: str = field(
        default="paraformer-realtime-v2",
        metadata={"help": "Model name: paraformer-realtime-v2 (recommended), paraformer-realtime-v1, etc."},
    )
    dashscope_stt_sample_rate: int = field(
        default=16000,
        metadata={"help": "Audio sample rate in Hz."},
    )
    dashscope_stt_language_hints: str = field(
        default="zh,en",
        metadata={"help": "Comma-separated language hints (e.g. 'zh,en'). Only paraformer-realtime-v2."},
    )
    dashscope_stt_timeout: float = field(
        default=30.0,
        metadata={"help": "Request timeout in seconds."},
    )

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Qwen3OmniALLMHandlerArguments:
    allm_model_name: str = field(
        default="Qwen3-Omni-30B-A3B-Instruct",
        metadata={"help": "The Qwen3-Omni model name served by vLLM."},
    )
    allm_base_url: str = field(
        default="http://localhost:8000/v1",
        metadata={"help": "Base URL of the vLLM server hosting Qwen3-Omni."},
    )
    allm_api_key: str = field(
        default="EMPTY",
        metadata={"help": "API key for the vLLM server. Default is 'EMPTY'."},
    )
    allm_init_chat_prompt: str = field(
        default="You are a helpful and friendly AI assistant. You are polite, respectful, and aim to provide concise responses of less than 20 words.",
        metadata={"help": "The system prompt for the ALLM."},
    )
    allm_chat_size: int = field(
        default=999,
        metadata={"help": "Number of assistant-user interaction pairs to keep in chat history."},
    )
    allm_disable_thinking: bool = field(
        default=True,
        metadata={"help": "Disable thinking/reasoning in the model output."},
    )
    allm_request_timeout_s: float = field(
        default=30.0,
        metadata={"help": "Request timeout in seconds for the vLLM API call."},
    )
    allm_max_agent_iterations: int = field(
        default=10,
        metadata={"help": "Maximum XML tool-call agent-loop iterations for ALLM mode."},
    )
    allm_clean_response_text: bool = field(
        default=True,
        metadata={"help": "Clean unspeakable text before sending ALLM output to TTS."},
    )
    allm_gen_max_tokens: Optional[int] = field(
        default=None,
        metadata={"help": "Optional max_tokens passed to the Qwen3-Omni chat completion."},
    )

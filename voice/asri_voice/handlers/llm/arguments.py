from dataclasses import dataclass, field


@dataclass
class LanguageModelHandlerArguments:
    lm_model_name: str = field(
        default="Qwen/Qwen3-4B-Instruct-2507",
        metadata={"help": "The pretrained language model to use."},
    )
    lm_device: str = field(
        default="cuda",
        metadata={"help": "The device type on which the model will run. Default is 'cuda'."},
    )
    lm_torch_dtype: str = field(
        default="float16",
        metadata={"help": "The PyTorch data type for the model and input tensors."},
    )
    user_role: str = field(
        default="user",
        metadata={"help": "Role assigned to the user in the chat context. Default is 'user'."},
    )
    init_chat_role: str = field(
        default="system",
        metadata={"help": "Initial role for setting up the chat context. Default is 'system'."},
    )
    init_chat_prompt: str = field(
        default="You are a helpful and friendly AI assistant. You are polite, respectful, and aim to provide concise responses of less than 20 words.",
        metadata={"help": "The initial chat prompt to establish context for the language model."},
    )
    lm_gen_max_new_tokens: int = field(
        default=1024,
        metadata={"help": "Maximum number of new tokens to generate. Default is 1024."},
    )
    lm_gen_min_new_tokens: int = field(
        default=0,
        metadata={"help": "Minimum number of new tokens to generate. Default is 0."},
    )
    lm_gen_temperature: float = field(
        default=0.0,
        metadata={"help": "Controls the randomness of the output. Default is 0.0."},
    )
    lm_gen_do_sample: bool = field(
        default=False,
        metadata={"help": "Whether to use sampling. Default is False."},
    )
    chat_size: int = field(
        default=999,
        metadata={"help": "Number of interactions to keep for the chat. Default is 10."},
    )
    lm_is_vlm: bool = field(
        default=False,
        metadata={"help": "Set to True when using a Vision Language Model (VLM). Default is False."},
    )


@dataclass
class OpenApiLanguageModelHandlerArguments:
    open_api_model_name: str = field(
        default="deepseek-chat",
        metadata={"help": "The pretrained language model to use. Default is 'deepseek-chat'."},
    )
    open_api_user_role: str = field(
        default="user",
        metadata={"help": "Role assigned to the user in the chat context. Default is 'user'."},
    )
    open_api_init_chat_role: str = field(
        default="system",
        metadata={"help": "Initial role for setting up the chat context. Default is 'system'."},
    )
    open_api_init_chat_prompt: str = field(
        default="You are a helpful and friendly AI assistant. You are polite, respectful, and aim to provide concise responses of less than 20 words.",
        metadata={"help": "The initial chat prompt to establish context for the language model."},
    )
    open_api_chat_size: int = field(
        default=999,
        metadata={"help": "Number of interactions to keep for the chat. Default is 999."},
    )
    open_api_api_key: str | None = field(
        default=None,
        metadata={"help": "API key for authentication. Default is None."},
    )
    open_api_base_url: str | None = field(
        default=None,
        metadata={"help": "The root URL for all API endpoints. Default is None."},
    )
    open_api_stream: bool = field(
        default=False,
        metadata={"help": "Whether to use streaming mode. Default is False."},
    )
    open_api_disable_thinking: bool = field(
        default=True,
        metadata={"help": "Disable provider-side thinking/reasoning. Default is True."},
    )
    open_api_clean_response_text: bool = field(
        default=True,
        metadata={"help": "Clean assistant text before sending it to clients/eval. TTS text is always cleaned."},
    )
    open_api_gen_max_tokens: int | None = field(
        default=None,
        metadata={"help": "Maximum number of tokens to generate via OpenAI-compatible APIs."},
    )

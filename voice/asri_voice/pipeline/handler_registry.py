"""Declarative handler registry for pipeline components.

Instead of if-elif chains in src/main.py, each handler type (STT, LLM, TTS, ALLM)
is registered declaratively. New handlers only need to add a registration entry —
no changes to pipeline wiring code.
"""

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HandlerRegistration:
    """Describes how to instantiate a pipeline handler.

    Attributes:
        name: CLI/config key (e.g. "sensevoice", "open_api", "omnivoice").
        handler_class_path: Dotted import path to the handler class
            (e.g. "STT.sensevoice_handler.SenseVoiceSTTHandler").
        args_class_path: Dotted import path to the arguments dataclass
            (e.g. "arguments_classes.sensevoice_stt_arguments.SenseVoiceSTTHandlerArguments").
        args_prefix: Prefix used by HfArgumentParser for this handler's fields,
            stripped by rename_args (e.g. "sensevoice_stt").
        needs_should_listen: If True, pass (should_listen,) as setup_args (TTS handlers).
        extra_setup_keys: Additional keys injected into setup_kwargs at build time
            (e.g. ["cancel_scope"] for ALLM).
    """
    name: str
    handler_class_path: str
    args_class_path: str
    args_prefix: str
    needs_should_listen: bool = False
    extra_setup_keys: list[str] = field(default_factory=list)


def _import_class(dotted_path: str):
    """Import and return a class from a dotted path like 'STT.sensevoice_handler.SenseVoiceSTTHandler'."""
    module_path, class_name = dotted_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


class HandlerRegistry:
    """Registry mapping handler type + name to registration info."""

    def __init__(self):
        self._registrations: dict[str, dict[str, HandlerRegistration]] = {}

    def register(self, handler_type: str, registration: HandlerRegistration):
        """Register a handler under a type (stt, llm, tts, allm)."""
        if handler_type not in self._registrations:
            self._registrations[handler_type] = {}
        self._registrations[handler_type][registration.name] = registration

    def get(self, handler_type: str, name: str) -> HandlerRegistration:
        """Look up a registration by type and name."""
        try:
            return self._registrations[handler_type][name]
        except KeyError:
            available = list(self._registrations.get(handler_type, {}).keys())
            raise ValueError(
                f"Unknown {handler_type} handler '{name}'. Available: {available}"
            )

    def available(self, handler_type: str) -> list[str]:
        """List available handler names for a type."""
        return list(self._registrations.get(handler_type, {}).keys())

    def all_args_classes(self) -> list[type]:
        """Return all arguments dataclasses across all registered handlers.
        Used by the argument parser to know which dataclasses to parse."""
        classes = []
        seen = set()
        for type_regs in self._registrations.values():
            for reg in type_regs.values():
                if reg.args_class_path not in seen:
                    seen.add(reg.args_class_path)
                    classes.append(_import_class(reg.args_class_path))
        return classes

    def get_args_prefix(self, handler_type: str, name: str) -> str:
        """Get the args_prefix for a handler."""
        return self.get(handler_type, name).args_prefix

    def create_handler(
        self,
        handler_type: str,
        name: str,
        stop_event,
        queue_in,
        queue_out,
        handler_kwargs: dict[str, Any],
        should_listen=None,
        extra_kwargs: dict[str, Any] | None = None,
    ):
        """Instantiate a handler from its registration.

        Parameters
        ----------
        handler_type : str
            One of "stt", "llm", "tts", "allm".
        name : str
            The handler name (e.g. "sensevoice", "open_api").
        stop_event : threading.Event
            Pipeline stop signal.
        queue_in, queue_out : queue.Queue
            Input/output queues.
        handler_kwargs : dict
            The parsed + renamed arguments for this handler.
        should_listen : threading.Event, optional
            Passed as setup_args for handlers that need it (TTS).
        extra_kwargs : dict, optional
            Additional kwargs merged into setup_kwargs (e.g. cancel_scope).
        """
        reg = self.get(handler_type, name)
        handler_class = _import_class(reg.handler_class_path)

        setup_kwargs = dict(handler_kwargs)
        if extra_kwargs:
            for key in reg.extra_setup_keys:
                if key in extra_kwargs:
                    setup_kwargs[key] = extra_kwargs[key]
            # Also merge any extra_kwargs not in extra_setup_keys filter
            # if the caller explicitly passes them
            for k, v in extra_kwargs.items():
                if k not in setup_kwargs:
                    setup_kwargs[k] = v

        setup_args = ()
        if reg.needs_should_listen and should_listen is not None:
            setup_args = (should_listen,)

        return handler_class(
            stop_event,
            queue_in=queue_in,
            queue_out=queue_out,
            setup_args=setup_args,
            setup_kwargs=setup_kwargs,
        )


# ---------------------------------------------------------------------------
# Global registry instance with all built-in handlers
# ---------------------------------------------------------------------------
registry = HandlerRegistry()

# --- STT handlers ---
registry.register("stt", HandlerRegistration(
    name="sensevoice",
    handler_class_path="handlers.stt.sensevoice_handler.SenseVoiceSTTHandler",
    args_class_path="handlers.stt.arguments.SenseVoiceSTTHandlerArguments",
    args_prefix="sensevoice_stt",
))
registry.register("stt", HandlerRegistration(
    name="qwen3",
    handler_class_path="handlers.stt.qwen3_asr_handler.Qwen3ASRSTTHandler",
    args_class_path="handlers.stt.arguments.Qwen3ASRArguments",
    args_prefix="qwen3_asr",
))
registry.register("stt", HandlerRegistration(
    name="vadasr",
    handler_class_path="handlers.stt.fake_streaming_asr.FakeStreamingASRHandler",
    args_class_path="handlers.stt.arguments.StreamingSenseVoiceHandlerArguments",
    args_prefix="vadasr",
    extra_setup_keys=["cancel_scope", "text_output_queue"],
))
registry.register("stt", HandlerRegistration(
    name="qwen3-asr-streaming",
    handler_class_path="handlers.stt.qwen3_asr_streaming_handler.Qwen3ASRStreamingHandler",
    args_class_path="handlers.stt.arguments.Qwen3ASRStreamingArguments",
    args_prefix="qwen3_asr_streaming",
    extra_setup_keys=["cancel_scope", "text_output_queue"],
))
registry.register("stt", HandlerRegistration(
    name="openai_whisper",
    handler_class_path="handlers.stt.openai_whisper_handler.OpenAIWhisperSTTHandler",
    args_class_path="handlers.stt.openai_whisper_arguments.OpenAIWhisperSTTArguments",
    args_prefix="openai_whisper_stt",
))
registry.register("stt", HandlerRegistration(
    name="elevenlabs",
    handler_class_path="handlers.stt.elevenlabs_stt_handler.ElevenLabsSTTHandler",
    args_class_path="handlers.stt.elevenlabs_stt_arguments.ElevenLabsSTTArguments",
    args_prefix="elevenlabs_stt",
))
registry.register("stt", HandlerRegistration(
    name="dashscope",
    handler_class_path="handlers.stt.dashscope_stt_handler.DashScopeSTTHandler",
    args_class_path="handlers.stt.dashscope_stt_arguments.DashScopeSTTArguments",
    args_prefix="dashscope_stt",
))


# --- LLM handlers ---
registry.register("llm", HandlerRegistration(
    name="open_api",
    handler_class_path="handlers.llm.openai_api_language_model.OpenApiModelHandler",
    args_class_path="handlers.llm.arguments.OpenApiLanguageModelHandlerArguments",
    args_prefix="open_api",
    extra_setup_keys=["cancel_scope", "runtime_config", "tool_registry", "text_output_queue"],
))
registry.register("llm", HandlerRegistration(
    name="transformers",
    handler_class_path="handlers.llm.language_model.LanguageModelHandler",
    args_class_path="handlers.llm.arguments.LanguageModelHandlerArguments",
    args_prefix="lm",
))
registry.register("llm", HandlerRegistration(
    name="mlx-lm",
    handler_class_path="handlers.llm.language_model.LanguageModelHandler",
    args_class_path="handlers.llm.arguments.LanguageModelHandlerArguments",
    args_prefix="lm",
))

# --- TTS handlers ---
registry.register("tts", HandlerRegistration(
    name="omnivoice",
    handler_class_path="handlers.tts.omnivoice_tts_handler.OmniVoiceTTSHandler",
    args_class_path="handlers.tts.arguments.OmniVoiceTTSHandlerArguments",
    args_prefix="omnivoice_tts",
    needs_should_listen=True,
))
registry.register("tts", HandlerRegistration(
    name="qwen3_local",
    handler_class_path="handlers.tts.qwen3_local_tts_handler.Qwen3TTSHandler",
    args_class_path="handlers.tts.arguments.Qwen3LocalTTSHandlerArguments",
    args_prefix="qwen3_local",
    needs_should_listen=True,
))
registry.register("tts", HandlerRegistration(
    name="qwen3_tts",
    handler_class_path="handlers.tts.qwen3_tts_handler.Qwen3TTSHandler",
    args_class_path="handlers.tts.arguments.Qwen3TTSHandlerArguments",
    args_prefix="qwen3_tts",
    needs_should_listen=True,
))
registry.register("tts", HandlerRegistration(
    name="qwen3_tts_streaming",
    handler_class_path="handlers.tts.qwen3_tts_streaming_handler.Qwen3TTSStreamingHandler",
    args_class_path="handlers.tts.arguments.Qwen3TTSStreamingHandlerArguments",
    args_prefix="qwen3_tts_streaming",
    needs_should_listen=True,
))
registry.register("tts", HandlerRegistration(
    name="voxcpm2",
    handler_class_path="handlers.tts.voxcpm2_tts_handler.VoxCPM2TTSHandler",
    args_class_path="handlers.tts.arguments.VoxCPM2TTSHandlerArguments",
    args_prefix="voxcpm2_tts",
    needs_should_listen=True,
))
registry.register("tts", HandlerRegistration(
    name="openai_tts",
    handler_class_path="handlers.tts.openai_tts_handler.OpenAITTSHandler",
    args_class_path="handlers.tts.openai_tts_arguments.OpenAITTSHandlerArguments",
    args_prefix="openai_tts",
    needs_should_listen=True,
    extra_setup_keys=["cancel_scope", "runtime_config"],
))
registry.register("tts", HandlerRegistration(
    name="elevenlabs",
    handler_class_path="handlers.tts.elevenlabs_tts_handler.ElevenLabsTTSHandler",
    args_class_path="handlers.tts.elevenlabs_tts_arguments.ElevenLabsTTSArguments",
    args_prefix="elevenlabs_tts",
    needs_should_listen=True,
    extra_setup_keys=["cancel_scope", "runtime_config"],
))
registry.register("tts", HandlerRegistration(
    name="dashscope",
    handler_class_path="handlers.tts.dashscope_tts_handler.DashScopeTTSHandler",
    args_class_path="handlers.tts.dashscope_tts_arguments.DashScopeTTSArguments",
    args_prefix="dashscope_tts",
    needs_should_listen=True,
    extra_setup_keys=["cancel_scope", "runtime_config"],
))

# --- HeartBeat Interaction (side-branch) ---
registry.register("heartbeat_interaction", HandlerRegistration(
    name="omni",
    handler_class_path="handlers.heartbeat_interaction.handler.HeartbeatInteractionHandler",
    args_class_path="handlers.heartbeat_interaction.arguments.HeartbeatInteractionArguments",
    args_prefix="heartbeat_interaction",
    extra_setup_keys=["chat_ref", "cancel_scope"],
))

# --- ALLM handlers ---
registry.register("allm", HandlerRegistration(
    name="qwen3-omni",
    handler_class_path="handlers.allm.qwen3omni_handler.Qwen3OmniALLMHandler",
    args_class_path="handlers.allm.arguments.Qwen3OmniALLMHandlerArguments",
    args_prefix="allm",
    extra_setup_keys=["cancel_scope", "runtime_config", "tool_registry", "text_output_queue"],
))

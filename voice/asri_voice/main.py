"""Speech-to-speech pipeline entry point.

Supports two modes:
  - Two-stage: VAD → STT → LLM → LMOutputProcessor → PrefetchHandler+TTS → Speaker
  - ALLM:      VAD → ALLM (audio-native LLM) → LMOutputProcessor → PrefetchHandler+TTS → Speaker

Config sources (priority: CLI > YAML > defaults):
  uv run python asri_voice/main.py --config configs/asri-voice.yaml
  uv run python asri_voice/main.py --stt sensevoice --llm open_api --tts omnivoice ...
"""

import logging
import os
import signal
import sys
import time

from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
ROOT_DIR = CURRENT_DIR.parent
# Ensure sub-modules (pipeline/, handlers/, etc.) are importable when
# running as ``python asri_voice/main.py`` directly.
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

import numpy as np  # noqa: F401 – used in nested classes below
from copy import copy
from queue import Queue
from threading import Event
from typing import Any, Optional

# Heavy imports (torch, rich, transformers) are deferred to the functions
# that use them so that ``from main import build_pipeline_from_yaml`` can
# succeed in environments that don't have these packages installed
# (e.g. the Django host process).  numpy is kept at module level because
# it is referenced inside nested helper classes.

from pipeline.cancel_scope import CancelScope
from pipeline.handler_registry import registry
from pipeline.thread_manager import ThreadManager

def _ensure_nltk_resource(resource: str, package: str) -> None:
    """Avoid blocking offline service startup on optional NLTK downloads."""
    if os.getenv("S2S_ENSURE_NLTK_RESOURCES", "").lower() not in ("1", "true", "yes"):
        return
    import nltk

    try:
        nltk.data.find(resource)
        return
    except (LookupError, OSError):
        pass

    nltk.download(package)


_ensure_nltk_resource("tokenizers/punkt_tab", "punkt_tab")
_ensure_nltk_resource("taggers/averaged_perceptron_tagger_eng", "averaged_perceptron_tagger_eng")

# Only set torch-related env vars when torch is available
try:
    import torch as _torch  # noqa: F401
    os.environ["TORCHINDUCTOR_CACHE_DIR"] = os.path.join(ROOT_DIR, "tmp")
except ImportError:
    pass

logging.getLogger("numba").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
MLX_DEFAULT_LM_MODEL = "mlx-community/Qwen3-4B-Instruct-2507-bf16"
TRANSFORMERS_DEFAULT_LM_MODEL = "Qwen/Qwen3-4B-Instruct-2507"


# ---------------------------------------------------------------------------
# YAML config support
# ---------------------------------------------------------------------------

def _load_yaml_config(path: str) -> dict[str, Any]:
    """Load YAML file as a flat list of CLI-style key=value pairs."""
    import yaml
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    # Flatten nested sections into CLI-arg style keys
    cli_args = []
    for key, value in raw.items():
        if isinstance(value, dict):
            # Nested section like stt_config, llm_config, tts_config, allm_config
            for sub_key, sub_value in value.items():
                if key == "heartbeat_interaction_config" and not sub_key.startswith("heartbeat_interaction_"):
                    sub_key = f"heartbeat_interaction_{sub_key}"
                cli_args.append((f"--{sub_key}", _expand_yaml_value(sub_value)))
        else:
            cli_args.append((f"--{key}", _expand_yaml_value(value)))
    return cli_args


def _expand_yaml_value(value: Any) -> Any:
    """Expand environment variables in YAML string values.

    This keeps vLLM-style literal keys such as ``EMPTY`` untouched, while
    allowing real providers to use ``env:OPENAI_API_KEY`` or
    ``${OPENAI_API_KEY}`` in config files without committing secrets.
    """
    if not isinstance(value, str):
        return value
    if value.startswith("env:"):
        env_name = value[len("env:"):].strip()
        expanded = os.environ.get(env_name)
        if expanded is None:
            logger.warning("Environment variable in config value is not set: %s", env_name)
            return value
        return expanded
    expanded = os.path.expandvars(value)
    if expanded == value and ("${" in value or "$" in value):
        logger.warning("Environment variable in config value is not set: %s", value)
    return expanded


def _merge_yaml_and_cli(yaml_args: list[tuple], cli_argv: list[str]) -> list[str]:
    """Merge YAML args with CLI args. CLI takes precedence."""
    # Collect CLI keys (--xxx)
    cli_keys = set()
    for arg in cli_argv:
        if arg.startswith("--"):
            cli_keys.add(arg.split("=")[0])

    result = list(cli_argv)
    for key, value in yaml_args:
        if key not in cli_keys:
            if isinstance(value, bool):
                result.extend([key, str(value)])
            else:
                result.extend([key, str(value)])

    return result


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def _all_argument_classes():
    """Collect all argument dataclasses: base + registry handlers."""
    from arguments.module_arguments import ModuleArguments
    from connections.arguments import SocketReceiverArguments, SocketSenderArguments, WebSocketStreamerArguments
    from handlers.vad.arguments import VADHandlerArguments

    base = [
        ModuleArguments,
        SocketReceiverArguments,
        SocketSenderArguments,
        WebSocketStreamerArguments,
        VADHandlerArguments,
    ]
    return base + registry.all_args_classes()


def parse_arguments():
    """Parse config from YAML + CLI. Returns tuple of dataclass instances."""
    from transformers import HfArgumentParser
    all_classes = _all_argument_classes()
    parser = HfArgumentParser(tuple(all_classes))

    argv = list(sys.argv[1:])

    # Extract --config before HfArgumentParser sees it
    yaml_args = []
    if "--config" in argv:
        idx = argv.index("--config")
        if idx + 1 < len(argv):
            config_path = argv[idx + 1]
            argv = argv[:idx] + argv[idx + 2:]
            yaml_args = _load_yaml_config(config_path)
            logger.info("Loaded config from %s", config_path)

    if len(argv) == 1 and argv[0].endswith(".json"):
        return parser.parse_json_file(json_file=os.path.abspath(argv[0]))

    # Merge YAML defaults with CLI overrides
    if yaml_args:
        argv = _merge_yaml_and_cli(yaml_args, argv)

    original_argv = sys.argv
    sys.argv = [sys.argv[0]] + argv
    try:
        return parser.parse_args_into_dataclasses()
    finally:
        sys.argv = original_argv


# ---------------------------------------------------------------------------
# Argument preparation helpers
# ---------------------------------------------------------------------------

def rename_args(args, prefix):
    """Remove prefix from dataclass fields and collect gen_kwargs."""
    gen_kwargs = {}
    for key in copy(args.__dict__):
        if key.startswith(prefix):
            value = args.__dict__.pop(key)
            new_key = key[len(prefix) + 1:]
            if new_key.startswith("gen_"):
                gen_kwargs[new_key[4:]] = value
            else:
                args.__dict__[new_key] = value
    args.__dict__["gen_kwargs"] = gen_kwargs


def prepare_args(module_kwargs, handler_kwargs_map: dict[str, Any]):
    """Apply platform checks and device overrides, then rename all handler args."""
    from sys import platform

    # Mac optimal settings
    if module_kwargs.local_mac_optimal_settings:
        for kwargs in handler_kwargs_map.values():
            if hasattr(kwargs, "device"):
                kwargs.device = "mps"
        module_kwargs.mode = "local"
        module_kwargs.stt = "sensevoice"
        module_kwargs.llm = "mlx-lm"
        module_kwargs.tts = "omnivoice"

    # Default TTS
    if module_kwargs.tts is None:
        module_kwargs.tts = "omnivoice"

    # Mac checks
    if platform == "darwin":
        if module_kwargs.device == "cuda":
            raise ValueError("Cannot use CUDA on macOS.")
        if module_kwargs.llm != "mlx-lm":
            logger.warning("For macOS, mlx-lm is recommended. Use --llm mlx-lm.")
        if module_kwargs.tts not in ("omnivoice", "qwen3_local", "qwen3_tts", "qwen3_tts_streaming", "voxcpm2"):
            logger.warning("For macOS, use --tts omnivoice, qwen3_local, qwen3_tts, qwen3_tts_streaming, or voxcpm2.")

    # Device override
    if module_kwargs.device:
        device = module_kwargs.device
        for kwargs in handler_kwargs_map.values():
            for attr in ("lm_device", "tts_device", "stt_device",
                         "qwen3_local_device"):
                if hasattr(kwargs, attr):
                    setattr(kwargs, attr, device)

    # Rename all handler kwargs using their registry prefix
    for prefix, kwargs in handler_kwargs_map.items():
        rename_args(kwargs, prefix)


# ---------------------------------------------------------------------------
# Queues and events
# ---------------------------------------------------------------------------

def create_queues_and_events() -> dict[str, Any]:
    from pipeline.pipeline_state import PipelineStateMachine
    pipeline_state = PipelineStateMachine()
    return {
        "stop_event": Event(),
        # Legacy Event shims backed by the state machine. Handlers that take
        # should_listen / response_playing keep working; the state machine is
        # the single source of truth (see pipeline/pipeline_state.py).
        "pipeline_state": pipeline_state,
        "should_listen": pipeline_state.make_should_listen(),
        "response_playing": pipeline_state.make_response_playing(),
        "cancel_scope": CancelScope(),
        "recv_audio_chunks_queue": Queue(),
        "send_audio_chunks_queue": Queue(),
        "spoken_prompt_queue": Queue(),
        "stt_output_queue": Queue(),
        "text_prompt_queue": Queue(),
        "lm_response_queue": Queue(),
        "lm_processed_queue": Queue(),
        "text_output_queue": Queue(),
    }


# ---------------------------------------------------------------------------
# Communication handlers (mode-dependent, not in registry)
# ---------------------------------------------------------------------------

def _build_comms_handlers(module_kwargs, queues, vad_handler_kwargs, handler_kwargs_map):
    """Build communication handlers based on mode. Returns (comms_handlers, text_output_queue)."""
    stop_event = queues["stop_event"]
    should_listen = queues["should_listen"]
    response_playing = queues["response_playing"]
    cancel_scope = queues["cancel_scope"]
    recv_q = queues["recv_audio_chunks_queue"]
    send_q = queues["send_audio_chunks_queue"]
    stt_out_q = queues["stt_output_queue"]
    text_prompt_q = queues["text_prompt_queue"]
    text_output_queue = None

    if module_kwargs.mode == "local":
        from connections.local_audio_streamer import LocalAudioStreamer
        local_audio_streamer = LocalAudioStreamer(
            input_queue=recv_q,
            output_queue=send_q,
            enable_barge_in=module_kwargs.enable_barge_in,
            should_listen=should_listen,
            input_device=module_kwargs.input_device,
            output_device=module_kwargs.output_device,
        )
        should_listen.set()
        return [local_audio_streamer], None

    elif module_kwargs.mode == "websocket":
        from connections.websocket_streamer import WebSocketStreamer
        from handlers.stt.transcription_notifier import TranscriptionNotifier
        text_output_queue = queues["text_output_queue"]
        ws = WebSocketStreamer(
            stop_event,
            input_queue=recv_q, output_queue=send_q,
            should_listen=should_listen,
            text_output_queue=text_output_queue,
            host=module_kwargs.ws_host if hasattr(module_kwargs, "ws_host") else "localhost",
            port=module_kwargs.ws_port if hasattr(module_kwargs, "ws_port") else 8765,
        )
        notifier = TranscriptionNotifier(
            stop_event,
            queue_in=stt_out_q, queue_out=text_prompt_q,
            setup_kwargs={
                "text_output_queue": text_output_queue,
                "cancel_scope": cancel_scope,
                "runtime_config": runtime_config,
            },
        )
        return [ws, notifier], text_output_queue

    elif module_kwargs.mode == "realtime":
        from api.openai_realtime.server import RealtimeServer
        from api.openai_realtime.runtime_config import RuntimeConfig
        from handlers.stt.transcription_notifier import TranscriptionNotifier
        text_output_queue = queues["text_output_queue"]
        runtime_config = RuntimeConfig(server_agent_loop=bool(module_kwargs.tools_module))

        # Inject runtime_config into applicable handlers
        for kwargs in handler_kwargs_map.values():
            vars(kwargs)["runtime_config"] = runtime_config
        vars(vad_handler_kwargs)["text_output_queue"] = text_output_queue
        for kwargs in handler_kwargs_map.values():
            vars(kwargs)["cancel_scope"] = cancel_scope

        notifier = TranscriptionNotifier(
            stop_event,
            queue_in=stt_out_q, queue_out=text_prompt_q,
            setup_kwargs={
                "text_output_queue": text_output_queue,
                "cancel_scope": cancel_scope,
                "runtime_config": runtime_config,
            },
        )
        ws_kwargs = handler_kwargs_map.get("_websocket", None)
        realtime = RealtimeServer(
            stop_event,
            input_queue=recv_q, output_queue=send_q,
            should_listen=should_listen,
            response_playing=response_playing,
            cancel_scope=cancel_scope,
            text_output_queue=text_output_queue,
            text_prompt_queue=text_prompt_q,
            runtime_config=runtime_config,
            host="localhost", port=8765,
        )
        return [realtime, notifier], text_output_queue

    else:  # socket mode
        from connections.socket_receiver import SocketReceiver
        from connections.socket_sender import SocketSender
        sock_recv_kwargs = handler_kwargs_map.get("_socket_recv", {})
        sock_send_kwargs = handler_kwargs_map.get("_socket_send", {})
        return [
            SocketReceiver(stop_event, recv_q, should_listen,
                           host="localhost", port=12345, chunk_size=1024),
            SocketSender(stop_event, send_q, host="localhost", port=12346),
        ], None


# ---------------------------------------------------------------------------
# Pipeline builder — the core simplification
# ---------------------------------------------------------------------------

def build_pipeline(module_kwargs, vad_handler_kwargs, handler_kwargs_map,
                   queues, websocket_streamer_kwargs=None,
                   socket_receiver_kwargs=None, socket_sender_kwargs=None,
                   comm_mode="standalone"):
    """Build the complete pipeline using the handler registry.

    Parameters
    ----------
    module_kwargs : ModuleArguments
    vad_handler_kwargs : VADHandlerArguments
    handler_kwargs_map : dict
        Maps args_prefix → renamed kwargs dict for each handler.
    queues : dict
        From create_queues_and_events().
    """
    stop_event = queues["stop_event"]
    should_listen = queues["should_listen"]
    pipeline_state = queues.get("pipeline_state")
    cancel_scope = queues["cancel_scope"]
    recv_q = queues["recv_audio_chunks_queue"]
    send_q = queues["send_audio_chunks_queue"]
    spoken_prompt_q = queues["spoken_prompt_queue"]
    stt_out_q = queues["stt_output_queue"]
    text_prompt_q = queues["text_prompt_queue"]
    lm_response_q = queues["lm_response_queue"]
    lm_processed_q = queues["lm_processed_queue"]

    # Create runtime_config early for realtime mode (needed by handlers below)
    runtime_config = None
    if module_kwargs.mode == "realtime":
        from api.openai_realtime.runtime_config import RuntimeConfig
        runtime_config = RuntimeConfig(server_agent_loop=bool(module_kwargs.tools_module))

    # --- Communication handlers (mode-dependent) ---
    text_output_queue = None
    realtime_server = None
    if module_kwargs.mode == "local":
        from connections.local_audio_streamer import LocalAudioStreamer
        comms = [LocalAudioStreamer(
            input_queue=recv_q, output_queue=send_q,
            enable_barge_in=module_kwargs.enable_barge_in,
            should_listen=should_listen,
            input_device=module_kwargs.input_device,
            output_device=module_kwargs.output_device,
        )]
        should_listen.set()

    elif module_kwargs.mode == "websocket":
        from connections.websocket_streamer import WebSocketStreamer
        from handlers.stt.transcription_notifier import TranscriptionNotifier
        text_output_queue = queues["text_output_queue"]
        comms = [
            WebSocketStreamer(
                stop_event, input_queue=recv_q, output_queue=send_q,
                should_listen=should_listen, text_output_queue=text_output_queue,
                host=websocket_streamer_kwargs.ws_host if websocket_streamer_kwargs else "localhost",
                port=websocket_streamer_kwargs.ws_port if websocket_streamer_kwargs else 8765,
            ),
            TranscriptionNotifier(
                stop_event, queue_in=stt_out_q, queue_out=text_prompt_q,
                setup_kwargs={
                    "text_output_queue": text_output_queue,
                    "cancel_scope": cancel_scope,
                    "runtime_config": runtime_config,
                },
            ),
        ]

    elif module_kwargs.mode == "realtime":
        from handlers.stt.transcription_notifier import TranscriptionNotifier
        text_output_queue = queues["text_output_queue"]

        # Inject runtime_config into TTS handler kwargs only
        # (STT/LLM handlers don't accept runtime_config in setup())
        tts_key = module_kwargs.tts
        if tts_key in handler_kwargs_map and isinstance(handler_kwargs_map[tts_key], dict):
            handler_kwargs_map[tts_key]["runtime_config"] = runtime_config

        vad_setup = vars(vad_handler_kwargs) if hasattr(vad_handler_kwargs, '__dict__') else vad_handler_kwargs
        vad_setup["text_output_queue"] = text_output_queue

        if comm_mode != "django":
            from api.openai_realtime.server import RealtimeServer
            realtime_server = RealtimeServer(
                    stop_event, input_queue=recv_q, output_queue=send_q,
                    should_listen=should_listen, response_playing=queues["response_playing"],
                    cancel_scope=cancel_scope, text_output_queue=text_output_queue,
                    text_prompt_queue=text_prompt_q, runtime_config=runtime_config,
                    internal_queues=[stt_out_q, text_prompt_q, lm_response_q, lm_processed_q],
                    host=websocket_streamer_kwargs.ws_host if websocket_streamer_kwargs else "localhost",
                    port=websocket_streamer_kwargs.ws_port if websocket_streamer_kwargs else 8765,
                )
        comms = [
            TranscriptionNotifier(
                stop_event, queue_in=stt_out_q, queue_out=text_prompt_q,
                setup_kwargs={
                    "text_output_queue": text_output_queue,
                    "cancel_scope": cancel_scope,
                    "runtime_config": runtime_config,
                },
            ),
        ]
        if realtime_server is not None:
            comms.insert(0, realtime_server)

    else:  # socket
        from connections.socket_receiver import SocketReceiver
        from connections.socket_sender import SocketSender
        comms = [
            SocketReceiver(
                stop_event, recv_q, should_listen,
                host=socket_receiver_kwargs.recv_host if socket_receiver_kwargs else "localhost",
                port=socket_receiver_kwargs.recv_port if socket_receiver_kwargs else 12345,
                chunk_size=socket_receiver_kwargs.chunk_size if socket_receiver_kwargs else 1024,
            ),
            SocketSender(
                stop_event, send_q,
                host=socket_sender_kwargs.send_host if socket_sender_kwargs else "localhost",
                port=socket_sender_kwargs.send_port if socket_sender_kwargs else 12346,
            ),
        ]

    # --- VAD (always present) ---
    from handlers.vad.vad_handler import VADHandler

    if module_kwargs.enable_live_transcription:
        vad_handler_kwargs.enable_realtime_transcription = True
        vad_handler_kwargs.realtime_processing_pause = module_kwargs.live_transcription_update_interval

    vad_setup = vars(vad_handler_kwargs)
    vad_setup["cancel_scope"] = cancel_scope
    vad_setup["playback_queue"] = send_q
    vad_setup["enable_barge_in"] = module_kwargs.enable_barge_in
    # Wire the pipeline state machine so VAD runs in every phase and can
    # trigger barge-in during THINKING/SPEAKING (see pipeline_state.py).
    if pipeline_state is not None:
        vad_setup["pipeline_state"] = pipeline_state
    if module_kwargs.stt in ("vadasr", "qwen3-asr-streaming"):
        vad_setup["enable_vadasr"] = True
    vad = VADHandler(
        stop_event,
        queue_in=recv_q, queue_out=spoken_prompt_q,
        setup_args=(should_listen,),
        setup_kwargs=vad_setup,
    )

    # --- LM output processor (always present) ---
    from handlers.llm.lm_output_processor import LMOutputProcessor
    open_api_kwargs = handler_kwargs_map.get("open_api", {})
    lm_processor_kwargs = {
        "text_output_queue": text_output_queue,
        "cancel_scope": cancel_scope,
        "clean_response_text": open_api_kwargs.get("clean_response_text", True),
    }
    # In realtime mode, pass runtime_config and audio_output_queue so
    # LMOutputProcessor can skip TTS in text-only mode.
    if module_kwargs.mode == "realtime":
        lm_processor_kwargs["runtime_config"] = runtime_config
        lm_processor_kwargs["audio_output_queue"] = send_q
    lm_processor = LMOutputProcessor(
        stop_event,
        queue_in=lm_response_q, queue_out=lm_processed_q,
        setup_kwargs=lm_processor_kwargs,
    )

    # --- TTS via registry ---
    tts_name = module_kwargs.tts
    tts_reg = registry.get("tts", tts_name)
    tts_kwargs = handler_kwargs_map.get(tts_reg.args_prefix, {})
    tts = registry.create_handler(
        "tts", tts_name,
        stop_event=stop_event,
        queue_in=lm_processed_q, queue_out=send_q,
        handler_kwargs=tts_kwargs,
        should_listen=should_listen,
        extra_kwargs={"cancel_scope": cancel_scope},
    )

    # Wrap TTS with prefetch parallelism. Native streaming Qwen3-TTS needs a
    # hybrid wrapper: stream the first sentence immediately, then prefetch
    # later sentences behind playback. The regular PrefetchHandler would
    # materialize the first generator and defeat first-audio streaming.
    if tts_name == "qwen3_tts_streaming":
        from pipeline.streaming_prefetch_handler import StreamingHeadPrefetchHandler
        tts = StreamingHeadPrefetchHandler(tts, prefetch=1, cancel_scope=cancel_scope)
    else:
        from pipeline.prefetch_handler import PrefetchHandler
        tts = PrefetchHandler(tts, prefetch=1, cancel_scope=cancel_scope)

    # --- Server-side tool registry (shared by LLM, ALLM, and HeartBeat) ---
    tool_registry = None
    if module_kwargs.tools_module:
        from handlers.llm.tool_call.tool_registry import ToolRegistry
        import importlib
        tool_registry = ToolRegistry()
        tools_mod = importlib.import_module(module_kwargs.tools_module)
        if hasattr(tools_mod, "register_tools"):
            tools_mod.register_tools(tool_registry)
            logger.info(
                "Loaded %d server tools from %s: %s",
                len(tool_registry), module_kwargs.tools_module,
                tool_registry.all_server_tool_names(),
            )
        else:
            logger.warning(
                "Module %s has no register_tools(registry) function, skipping tool registration",
                module_kwargs.tools_module,
            )
        if module_kwargs.mode == "realtime":
            tool_registry.set_context_provider(runtime_config.tool_context)
            if realtime_server is not None:
                realtime_server.tool_registry = tool_registry
    elif comm_mode == "django":
        # In Django mode, always create an empty registry so that Django
        # tools can be registered after build_pipeline returns.
        from handlers.llm.tool_call.tool_registry import ToolRegistry
        tool_registry = ToolRegistry()
        if module_kwargs.mode == "realtime":
            tool_registry.set_context_provider(runtime_config.tool_context)
        logger.info("Created empty tool_registry for Django integration")

    # --- STT + LLM or ALLM ---
    if module_kwargs.stt == "allm":
        # ALLM mode: audio → ALLM → LM output
        allm_kwargs = handler_kwargs_map.get("allm", {})
        if module_kwargs.system_prompt_file:
            prompt_path = Path(module_kwargs.system_prompt_file)
            if not prompt_path.is_absolute():
                prompt_path = CURRENT_DIR / prompt_path
            allm_kwargs["init_chat_prompt"] = prompt_path.read_text(encoding="utf-8").strip()
            logger.info("Loaded ALLM system prompt from %s (%d chars)", prompt_path, len(allm_kwargs["init_chat_prompt"]))
        allm = registry.create_handler(
            "allm", "qwen3-omni",
            stop_event=stop_event,
            queue_in=spoken_prompt_q, queue_out=lm_response_q,
            handler_kwargs=allm_kwargs,
            extra_kwargs={
                "cancel_scope": cancel_scope,
                "runtime_config": runtime_config if module_kwargs.mode == "realtime" else None,
                "tool_registry": tool_registry,
                "text_output_queue": text_output_queue,
            },
        )

        if module_kwargs.mode == "realtime" and hasattr(allm, "chat"):
            for c in comms:
                if hasattr(c, "chat_ref"):
                    c.chat_ref = allm.chat

        heartbeat_interaction_handler = None
        if module_kwargs.enable_heartbeat_interaction:
            from handlers.heartbeat_interaction.handler import HeartbeatInteractionHandler, TURN_END
            from handlers.heartbeat_interaction.heartbeat_cache import HeartBeatCache
            from pipeline.turn_audio_history import TurnAudioHistory

            heartbeat_kwargs = handler_kwargs_map.get("heartbeat_interaction", {})
            heartbeat_mode = heartbeat_kwargs.get("mode", "omni")
            if heartbeat_mode != "omni":
                logger.warning("ALLM mode only supports HeartBeat Interaction mode=omni; got %s", heartbeat_mode)

            max_heartbeat = heartbeat_kwargs.get("max_heartbeat_entries", 2)
            heartbeat_cache = HeartBeatCache(max_entries=max_heartbeat)
            allm.heartbeat_cache = heartbeat_cache

            chat_turn_window = getattr(getattr(allm, "chat", None), "size", 999) + 1
            turn_audio_history = TurnAudioHistory(
                max_turns=chat_turn_window,
                max_total_seconds=None,
            )

            heartbeat_audio_queue = Queue()
            heartbeat_sink_queue = Queue()
            vad.predict_audio_queue = heartbeat_audio_queue

            original_vad_out = spoken_prompt_q

            class _VadOutWithSignal:
                def __init__(self, main_out, heartbeat_out):
                    self.main_out = main_out
                    self.heartbeat_out = heartbeat_out

                def _forward(self, item, method):
                    getattr(self.main_out, method)(item)
                    if self.heartbeat_out is None:
                        return
                    if isinstance(item, np.ndarray):
                        getattr(self.heartbeat_out, method)((TURN_END, item))
                    elif isinstance(item, tuple) and len(item) == 2:
                        label, audio = item
                        if label == "final":
                            audio_payload = audio if isinstance(audio, np.ndarray) else None
                            getattr(self.heartbeat_out, method)((TURN_END, audio_payload))

                def put(self, item, **kwargs):
                    self._forward(item, "put")

                def put_nowait(self, item):
                    self._forward(item, "put_nowait")

            vad.queue_out = _VadOutWithSignal(original_vad_out, heartbeat_audio_queue)
            heartbeat_interaction_handler = HeartbeatInteractionHandler(
                stop_event,
                queue_in=heartbeat_audio_queue,
                queue_out=heartbeat_sink_queue,
                setup_kwargs={
                    "chat_ref": allm.chat,
                    "turn_audio_history": turn_audio_history,
                    "model_name": heartbeat_kwargs.get("model_name", "Qwen3-Omni-8B"),
                    "base_url": heartbeat_kwargs.get("base_url", "http://localhost:8906/v1"),
                    "api_key": heartbeat_kwargs.get("api_key", "dummy"),
                    "block_duration_ms": heartbeat_kwargs.get("block_duration_ms", 500),
                    "request_timeout_s": heartbeat_kwargs.get("request_timeout_s", 5.0),
                    "cancel_scope": cancel_scope,
                    "heartbeat_cache": heartbeat_cache,
                    "tool_registry": tool_registry,
                    "runtime_config": runtime_config if module_kwargs.mode == "realtime" else None,
                    "text_output_queue": text_output_queue,
                    "tool_llm_model_name": allm_kwargs.get("model_name"),
                    "tool_llm_base_url": allm_kwargs.get("base_url"),
                    "tool_llm_api_key": allm_kwargs.get("api_key"),
                    "prompt_version": heartbeat_kwargs.get("prompt_version", "asri-v0"),
                    "blocking": heartbeat_kwargs.get("blocking", True),
                    "max_concurrent": heartbeat_kwargs.get("max_concurrent", 8),
                    "fd_mode": heartbeat_kwargs.get("fd_mode", False),
                },
            )
            if realtime_server is not None:
                realtime_server.internal_queues.extend([heartbeat_audio_queue, heartbeat_sink_queue])
            for c in comms:
                if hasattr(c, "turn_audio_history"):
                    c.turn_audio_history = turn_audio_history
            logger.info("HeartBeat Interaction side-branch enabled (ALLM + omni mode)")

        handlers = [*comms, vad, allm, lm_processor, tts]
        if heartbeat_interaction_handler is not None:
            handlers.append(heartbeat_interaction_handler)
        if comm_mode == "django":
            return {
                "manager": ThreadManager(handlers),
                "queues": queues,
                "runtime_config": runtime_config,
                "tool_registry": tool_registry,
            }
        return ThreadManager(handlers)

    else:
        # Two-stage: STT + LLM
        stt_dest = stt_out_q if module_kwargs.mode in ("websocket", "realtime") else text_prompt_q

        stt_name = module_kwargs.stt
        stt_reg = registry.get("stt", stt_name)
        stt_kwargs = handler_kwargs_map.get(stt_reg.args_prefix, {})



        stt = registry.create_handler(
            "stt", stt_name,
            stop_event=stop_event,
            queue_in=spoken_prompt_q, queue_out=stt_dest,
            handler_kwargs=stt_kwargs,
            extra_kwargs={"cancel_scope": cancel_scope, "text_output_queue": text_output_queue},
        )

        # LLM
        llm_name = module_kwargs.llm
        llm_reg = registry.get("llm", llm_name)
        llm_kwargs = handler_kwargs_map.get(llm_reg.args_prefix, {})

        # Special case: mlx-lm sets backend flag
        if llm_name == "mlx-lm":
            llm_kwargs["backend"] = "mlx"

        # Load system prompt from file (overrides init_chat_prompt)
        if module_kwargs.system_prompt_file:
            prompt_path = Path(module_kwargs.system_prompt_file)
            if not prompt_path.is_absolute():
                prompt_path = CURRENT_DIR / prompt_path
            llm_kwargs["init_chat_prompt"] = prompt_path.read_text(encoding="utf-8").strip()
            logger.info("Loaded system prompt from %s (%d chars)", prompt_path, len(llm_kwargs["init_chat_prompt"]))

        # Special case: VLM variant
        is_vlm = llm_kwargs.pop("is_vlm", False)
        if is_vlm and llm_name in ("transformers", "mlx-lm"):
            from handlers.llm.language_model import VisionLanguageModelHandler
            lm = VisionLanguageModelHandler(
                stop_event,
                queue_in=text_prompt_q, queue_out=lm_response_q,
                setup_kwargs=llm_kwargs,
            )
        else:
            lm_extra_kwargs = {
                "cancel_scope": cancel_scope,
                "tool_registry": tool_registry,
                "text_output_queue": text_output_queue,
            }
            if module_kwargs.mode == "realtime":
                lm_extra_kwargs["runtime_config"] = runtime_config
            lm = registry.create_handler(
                "llm", llm_name,
                stop_event=stop_event,
                queue_in=text_prompt_q, queue_out=lm_response_q,
                handler_kwargs=llm_kwargs,
                extra_kwargs=lm_extra_kwargs,
            )

        # Wire debug chat reference for /v1/debug/messages endpoint
        if module_kwargs.mode == "realtime" and hasattr(lm, "chat"):
            for c in comms:
                if hasattr(c, "chat_ref"):
                    c.chat_ref = lm.chat

        # --- HeartBeat Interaction side-branch (optional) ---
        heartbeat_interaction_handler = None
        streaming_sensevoice = None
        if module_kwargs.enable_heartbeat_interaction:
            from pipeline.fork_queue import ForkQueue
            from handlers.heartbeat_interaction.handler import HeartbeatInteractionHandler
            from handlers.heartbeat_interaction.streaming_asr_handler import StreamingASRHeartbeatHandler
            from handlers.heartbeat_interaction.heartbeat_cache import HeartBeatCache
            from pipeline.turn_audio_history import TurnAudioHistory

            # Get HeartBeat worker kwargs from parsed arguments
            heartbeat_kwargs = handler_kwargs_map.get("heartbeat_interaction", {})
            heartbeat_mode = heartbeat_kwargs.get("mode", "omni")  # "omni" or "streaming_asr"

            # Shared HeartBeat cache between HeartBeat worker and LLM handler
            max_heartbeat = heartbeat_kwargs.get("max_heartbeat_entries", 2)
            heartbeat_cache = HeartBeatCache(max_entries=max_heartbeat)

            # Shared audio segment buffer between FakeStreamingASRHandler and
            # StreamingASRHeartbeatHandler.  The ASR handler writes the cumulative
            # audio segment for each block; the HeartBeat worker consumes and
            # deletes it after emitting the input_messages event in replay mode.
            audio_segment_buffer: dict = {}

            # Shared turn audio history — keep the same user-turn window as Chat.
            # Audio history must use the same turn window as Chat and must
            # not have an independent duration cap.
            chat_turn_window = getattr(getattr(lm, "chat", None), "size", 999) + 1
            turn_audio_history = TurnAudioHistory(
                max_turns=chat_turn_window,
                max_total_seconds=None,
            )

            # Inject heartbeat_cache into the LLM handler.
            lm.heartbeat_cache = heartbeat_cache

            # Create a side-branch queue for the HeartBeat worker
            heartbeat_audio_queue = Queue()
            # HeartBeat worker writes to a sink queue (output not consumed by main pipeline)
            heartbeat_sink_queue = Queue()

            # VAD forwards real-time audio chunks to heartbeat_audio_queue
            # internally during speech (including the initial buffer flush).
            vad.predict_audio_queue = heartbeat_audio_queue

            # When VAD detects end-of-speech, it yields the complete utterance
            # to spoken_prompt_q.  We also send a TURN_END sentinel to the
            # HeartBeat worker so it can reset per-turn state for the next
            # utterance.  We also store the completed turn audio in
            # turn_audio_history for the HeartBeat worker to use as historical
            # context in multi-turn conversations.
            from handlers.heartbeat_interaction.handler import TURN_END
            from pipeline.turn_audio_history import encode_audio_base64
            original_vad_out = spoken_prompt_q
            class _VadOutWithSignal:
                """Wraps VAD's original queue_out, also sending TURN_END to HeartBeat.

                Audio storage is deferred: instead of storing here (which races
                with the HeartBeat worker reading turn_audio_history), we send
                the VAD-processed audio alongside TURN_END as a tuple
                ``(TURN_END, audio_ndarray)``.  The HeartBeat worker stores it
                into turn_audio_history when it processes the sentinel — at
                which point its current block processing is complete and the
                timing is correct.

                When *heartbeat_out* is None, only forward to main_out (used
                when HeartBeat worker reads from a different queue, e.g. interim_text).
                """
                def __init__(self, main_out, heartbeat_out, audio_history):
                    self.main_out = main_out
                    self.heartbeat_out = heartbeat_out
                    self.audio_history = audio_history

                def _forward(self, item, method):
                    getattr(self.main_out, method)(item)
                    if self.heartbeat_out is None:
                        return
                    if isinstance(item, np.ndarray):
                        getattr(self.heartbeat_out, method)((TURN_END, item))
                    elif isinstance(item, tuple) and len(item) == 2:
                        label, audio = item
                        if label == "final":
                            audio_payload = audio if isinstance(audio, np.ndarray) else None
                            getattr(self.heartbeat_out, method)((TURN_END, audio_payload))

                def put(self, item, **kwargs):
                    self._forward(item, "put")

                def put_nowait(self, item):
                    self._forward(item, "put_nowait")

            # The SFT system prompt + tool schema are hard-coded inside the
            # HeartBeat worker to match training data byte-for-byte; no EPOS
            # voice prompt is forwarded here.
            if heartbeat_mode == "streaming_asr":
                from handlers.stt.fake_streaming_asr import FakeStreamingASRHandler

                if module_kwargs.stt in ("vadasr", "qwen3-asr-streaming"):
                    # VADASR-family mode: main STT is already doing ASR. Share its
                    # interim_text_queue with the HeartBeat worker instead of
                    # creating a separate FakeStreamingASRHandler.
                    # heartbeat_audio_queue is not used — set heartbeat_out=None.
                    vad.queue_out = _VadOutWithSignal(original_vad_out, None, turn_audio_history)
                    interim_text_queue = Queue()
                    stt.interim_text_queue = interim_text_queue
                    stt.audio_segment_buffer = audio_segment_buffer
                    streaming_sensevoice = None  # no separate ASR instance
                    logger.info("HeartBeat Interaction: sharing VADASR ASR with HeartBeat worker")
                else:
                    vad.queue_out = _VadOutWithSignal(original_vad_out, heartbeat_audio_queue, turn_audio_history)
                    # Create a separate FakeStreamingASRHandler for HeartBeat side-branch
                    interim_text_queue = Queue()
                    streaming_sensevoice = FakeStreamingASRHandler(
                        stop_event,
                        queue_in=heartbeat_audio_queue,
                        queue_out=heartbeat_sink_queue,
                        setup_kwargs={
                            "asr_backend": heartbeat_kwargs.get("asr_backend", "sensevoice"),
                            "url": heartbeat_kwargs.get("sensevoice_url", ""),
                            "timeout": heartbeat_kwargs.get("sensevoice_timeout", 10.0),
                            "qwen3_asr_base_url": heartbeat_kwargs.get("qwen3_asr_base_url", ""),
                            "qwen3_asr_model_name": heartbeat_kwargs.get("qwen3_asr_model_name", ""),
                            "qwen3_asr_timeout": heartbeat_kwargs.get("qwen3_asr_timeout", 30.0),
                            "dashscope_api_key": heartbeat_kwargs.get("dashscope_asr_api_key", ""),
                            "dashscope_model": heartbeat_kwargs.get("dashscope_asr_model", "paraformer-realtime-v2"),
                            "dashscope_language_hints": heartbeat_kwargs.get("dashscope_asr_language_hints", "zh,en"),
                            "whisper_url": heartbeat_kwargs.get("whisper_asr_url", ""),
                            "whisper_api_key": heartbeat_kwargs.get("whisper_asr_api_key", ""),
                            "whisper_model": heartbeat_kwargs.get("whisper_asr_model", "whisper-1"),
                            "whisper_language": heartbeat_kwargs.get("whisper_asr_language", "zh"),
                            "block_duration_ms": heartbeat_kwargs.get("block_duration_ms", 500),
                            "interim_text_queue": interim_text_queue,
                            "heartbeat_cache": heartbeat_cache,
                            "cancel_scope": cancel_scope,
                            "audio_segment_buffer": audio_segment_buffer,
                        },
                    )
                    logger.info("HeartBeat Interaction side-branch ASR enabled (streaming_asr mode)")

                # HeartBeat worker: consumes interim text, calls text LLM for thinking/action.
                heartbeat_interaction_handler = StreamingASRHeartbeatHandler(
                    stop_event,
                    queue_in=interim_text_queue,
                    queue_out=heartbeat_sink_queue,
                    setup_kwargs={
                        "chat_ref": lm.chat,
                        "model_name": heartbeat_kwargs.get("model_name", "Qwen3.5-122B-A10B"),
                        "base_url": heartbeat_kwargs.get("base_url", "http://127.0.0.1:18001/v1"),
                        "api_key": heartbeat_kwargs.get("api_key", "dummy"),
                        "block_duration_ms": heartbeat_kwargs.get("block_duration_ms", 500),
                        "request_timeout_s": heartbeat_kwargs.get("request_timeout_s", 5.0),
                        "cancel_scope": cancel_scope,
                        "heartbeat_cache": heartbeat_cache,
                        "tool_registry": tool_registry,
                        "runtime_config": runtime_config if module_kwargs.mode == "realtime" else None,
                        "tool_llm_model_name": llm_kwargs.get("model_name"),
                        "tool_llm_base_url": llm_kwargs.get("base_url"),
                        "tool_llm_api_key": llm_kwargs.get("api_key"),
                        "prompt_version": heartbeat_kwargs.get("prompt_version", "asri-v0"),
                        "disable_thinking": heartbeat_kwargs.get("disable_thinking", True),
                        "blocking": heartbeat_kwargs.get("blocking", True),
                        "max_concurrent": heartbeat_kwargs.get("max_concurrent", 8),
                        "fd_mode": heartbeat_kwargs.get("fd_mode", False),
                        "text_output_queue": text_output_queue,
                        "audio_segment_buffer": audio_segment_buffer,
                    },
                )
                logger.info("HeartBeat Interaction side-branch enabled (streaming_asr mode, text LLM)")
            else:
                vad.queue_out = _VadOutWithSignal(original_vad_out, heartbeat_audio_queue, turn_audio_history)
                heartbeat_interaction_handler = HeartbeatInteractionHandler(
                    stop_event,
                    queue_in=heartbeat_audio_queue,
                    queue_out=heartbeat_sink_queue,
                    setup_kwargs={
                        "chat_ref": lm.chat,
                        "turn_audio_history": turn_audio_history,
                        "model_name": heartbeat_kwargs.get("model_name", "Qwen3-Omni-8B"),
                        "base_url": heartbeat_kwargs.get("base_url", "http://localhost:8906/v1"),
                        "api_key": heartbeat_kwargs.get("api_key", "dummy"),
                        "block_duration_ms": heartbeat_kwargs.get("block_duration_ms", 500),
                        "request_timeout_s": heartbeat_kwargs.get("request_timeout_s", 5.0),
                        "cancel_scope": cancel_scope,
                        "heartbeat_cache": heartbeat_cache,
                        "tool_registry": tool_registry,
                        "runtime_config": runtime_config if module_kwargs.mode == "realtime" else None,
                        "tool_llm_model_name": llm_kwargs.get("model_name"),
                        "tool_llm_base_url": llm_kwargs.get("base_url"),
                        "tool_llm_api_key": llm_kwargs.get("api_key"),
                        "prompt_version": heartbeat_kwargs.get("prompt_version", "asri-v0"),
                        "blocking": heartbeat_kwargs.get("blocking", True),
                        "max_concurrent": heartbeat_kwargs.get("max_concurrent", 8),
                    },
                )
                logger.info("HeartBeat Interaction side-branch enabled (omni mode, with HeartBeat cache)")

            if realtime_server is not None:
                realtime_server.internal_queues.extend([heartbeat_audio_queue, heartbeat_sink_queue])

            # Wire turn_audio_history to comms so eval history.set can
            # pre-load audio into the shared buffer.
            for c in comms:
                if hasattr(c, "turn_audio_history"):
                    c.turn_audio_history = turn_audio_history

        if (
            heartbeat_interaction_handler is not None
            and hasattr(lm, "heartbeat_replay_drain_hook")
            and hasattr(heartbeat_interaction_handler, "wait_for_replay_idle")
        ):
            lm.heartbeat_replay_drain_hook = heartbeat_interaction_handler.wait_for_replay_idle

        handlers = [*comms, vad, stt, lm, lm_processor, tts]
        if heartbeat_interaction_handler is not None:
            handlers.append(heartbeat_interaction_handler)
        # In streaming_asr mode (non-VADASR), add the separate ASR instance
        if (module_kwargs.enable_heartbeat_interaction and heartbeat_mode == "streaming_asr"
                and streaming_sensevoice is not None):
            handlers.append(streaming_sensevoice)
        if comm_mode == "django":
            return {
                "manager": ThreadManager(handlers),
                "queues": queues,
                "runtime_config": runtime_config,
                "tool_registry": tool_registry,
            }
        return ThreadManager(handlers)


# ---------------------------------------------------------------------------
# Django integration: build pipeline from YAML config
# ---------------------------------------------------------------------------

def build_pipeline_from_yaml(config_path: str, comm_mode: str = "django",
                             django_config: dict | None = None):
    """Build voice pipeline from a YAML config file.

    Designed for Django integration where the WebSocket layer is handled
    externally (e.g. by Django Channels VoiceConsumer).

    Parameters
    ----------
    config_path : str
        Path to the YAML configuration file.
    comm_mode : str
        Communication mode. ``"django"`` skips RealtimeServer creation
        and returns a dict with pipeline context.
    django_config : dict, optional
        Output of ``DjangoConfigReader.read_all()``. When provided,
        LLM config, system prompt, and tool schemas from Django
        override the YAML values.

    Returns
    -------
    dict
        ``{"manager": ThreadManager, "queues": dict,
          "runtime_config": RuntimeConfig | None,
          "tool_registry": ToolRegistry | None}``
    """
    # Parse YAML config into CLI-style args
    yaml_args = _load_yaml_config(config_path)

    # Collect all argument dataclasses
    all_classes = _all_argument_classes()
    from transformers import HfArgumentParser
    parser = HfArgumentParser(tuple(all_classes))

    # Parse yaml args through HfArgumentParser
    # Filter out None values and convert everything to strings
    original_argv = sys.argv
    flat_args = []
    for pair in yaml_args:
        items = pair if isinstance(pair, (list, tuple)) else [pair]
        i = 0
        while i < len(items):
            key = items[i]
            if i + 1 < len(items) and items[i + 1] is None:
                # Skip --key None pairs; let dataclass defaults apply
                i += 2
                continue
            flat_args.append(str(items[i]))
            i += 1
    sys.argv = [sys.argv[0]] + flat_args
    try:
        all_parsed = parser.parse_args_into_dataclasses()
    finally:
        sys.argv = original_argv

    # Unpack: first 5 are base classes, rest are handler args
    module_kwargs = all_parsed[0]
    socket_receiver_kwargs = all_parsed[1]
    socket_sender_kwargs = all_parsed[2]
    websocket_streamer_kwargs = all_parsed[3]
    vad_handler_kwargs = all_parsed[4]
    handler_instances = all_parsed[5:]

    setup_logger(module_kwargs.log_level)

    # Build handler_kwargs_map
    handler_args_classes = registry.all_args_classes()
    handler_kwargs_map = {}
    for dc_instance, dc_class in zip(handler_instances, handler_args_classes):
        prefix = _find_prefix(dc_class)
        if prefix:
            handler_kwargs_map[prefix] = dc_instance

    # Platform prep and rename
    prepare_args(module_kwargs, handler_kwargs_map)

    # Force realtime mode for Django WebSocket integration
    module_kwargs.mode = "realtime"

    # Convert dataclass instances to dicts
    for prefix in list(handler_kwargs_map.keys()):
        dc = handler_kwargs_map[prefix]
        handler_kwargs_map[prefix] = vars(dc) if hasattr(dc, '__dict__') else dc

    # Apply Django config overrides (LLM, prompt, tools)
    if django_config:
        from voice_django.django_config_reader import apply_django_config_to_handler_kwargs
        apply_django_config_to_handler_kwargs(
            django_config, handler_kwargs_map, module_kwargs,
            vad_handler_kwargs=vad_handler_kwargs,
        )

    queues = create_queues_and_events()

    result = build_pipeline(
        module_kwargs, vad_handler_kwargs, handler_kwargs_map, queues,
        websocket_streamer_kwargs=websocket_streamer_kwargs,
        socket_receiver_kwargs=socket_receiver_kwargs,
        socket_sender_kwargs=socket_sender_kwargs,
        comm_mode=comm_mode,
    )

    # Register Django tools into the shared tool_registry.
    # This runs *after* build_pipeline so the registry is already wired
    # to both the main LLM and Heartbeat LLM handlers.  Since the
    # registry is a mutable object, late registration is visible to all
    # handlers at call time.
    if django_config and result.get("tool_registry") is not None:
        tenant_id = django_config.get("tenant_id", "default")
        django_tool_schemas = (django_config.get("tool_schemas") or []) + (
            django_config.get("mcp_tools") or []
        )
        if django_tool_schemas:
            result["tool_registry"].register_django_tools(
                django_tool_schemas, tenant_id,
            )

    return result


# ---------------------------------------------------------------------------
# Logger setup
# ---------------------------------------------------------------------------

def setup_logger(log_level):
    level = log_level.upper()
    # Django may have already configured logging, so basicConfig is a no-op.
    # Ensure the root logger has a console handler at the requested level so
    # Voice module loggers (e.g. handlers.llm.*, utils.utils) are visible.
    root = logging.getLogger()
    root.setLevel(level)

    has_console = any(
        isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        for h in root.handlers
    )
    if not has_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        root.addHandler(console_handler)

    global logger
    logger = logging.getLogger(__name__)
    import torch
    if log_level == "debug":
        torch._logging.set_logs(graph_breaks=True, recompiles=True, cudagraphs=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    from rich.console import Console
    console = Console()

    all_parsed = parse_arguments()

    # Unpack: first 5 are base classes, rest are handler args
    module_kwargs = all_parsed[0]
    socket_receiver_kwargs = all_parsed[1]
    socket_sender_kwargs = all_parsed[2]
    websocket_streamer_kwargs = all_parsed[3]
    vad_handler_kwargs = all_parsed[4]
    handler_instances = all_parsed[5:]

    setup_logger(module_kwargs.log_level)

    # Build handler_kwargs_map: prefix → dataclass instance (pre-rename)
    handler_args_classes = registry.all_args_classes()

    # Map each handler's args prefix to the parsed dataclass
    handler_kwargs_map = {}
    for dc_instance, dc_class in zip(handler_instances, handler_args_classes):
        prefix = _find_prefix(dc_class)
        if prefix:
            handler_kwargs_map[prefix] = dc_instance

    # Platform prep and rename
    prepare_args(module_kwargs, handler_kwargs_map)

    # After rename_args, convert dataclass instances to dicts
    for prefix in list(handler_kwargs_map.keys()):
        dc = handler_kwargs_map[prefix]
        handler_kwargs_map[prefix] = vars(dc) if hasattr(dc, '__dict__') else dc

    queues = create_queues_and_events()

    pipeline_manager = build_pipeline(
        module_kwargs, vad_handler_kwargs, handler_kwargs_map, queues,
        websocket_streamer_kwargs=websocket_streamer_kwargs,
        socket_receiver_kwargs=socket_receiver_kwargs,
        socket_sender_kwargs=socket_sender_kwargs,
    )

    # Graceful shutdown
    shutdown_requested = [False]

    def signal_handler(_sig, _frame):
        if not shutdown_requested[0]:
            shutdown_requested[0] = True
            console.print("\n[yellow]Shutting down gracefully...[/yellow]")
            pipeline_manager.stop()
            console.print("[green]Pipeline stopped successfully[/green]")

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        pipeline_manager.start()
        while not shutdown_requested[0] and pipeline_manager.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        if not shutdown_requested[0]:
            console.print("\n[yellow]Shutting down gracefully...[/yellow]")
            pipeline_manager.stop()
            console.print("[green]Pipeline stopped successfully[/green]")


def _find_prefix(args_class) -> Optional[str]:
    """Find registry prefix for an args dataclass."""
    class_path = f"{args_class.__module__}.{args_class.__qualname__}"
    for type_regs in registry._registrations.values():
        for reg in type_regs.values():
            if reg.args_class_path == class_path:
                return reg.args_prefix
    return None


if __name__ == "__main__":
    main()

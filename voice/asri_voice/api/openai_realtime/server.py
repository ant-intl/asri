import logging
import os
import threading
from queue import Queue
from threading import Event

import uvicorn

from api.openai_realtime.runtime_config import RuntimeConfig
from api.openai_realtime.service import RealtimeService
from api.openai_realtime.websocket_router import create_app
from pipeline.cancel_scope import CancelScope

logger = logging.getLogger(__name__)


def _ws_ping_setting(env_name: str, default: float) -> float | None:
    raw = os.environ.get(env_name)
    if raw is None or raw == "":
        return default
    if raw.lower() in {"0", "none", "off", "false"}:
        return None
    return float(raw)


class RealtimeServer:
    """
    Pipeline handler for the OpenAI Realtime API mode.

    Owns pipeline queues, exposes run() for ThreadManager, and bridges
    between FastAPI/uvicorn and the internal audio + text queues.
    """

    def __init__(
        self,
        stop_event: Event,
        input_queue: Queue,
        output_queue: Queue,
        should_listen: Event,
        response_playing: Event | None = None,
        cancel_scope: CancelScope | None = None,
        text_output_queue: Queue | None = None,
        text_prompt_queue: Queue | None = None,
        runtime_config: RuntimeConfig | None = None,
        internal_queues: list[Queue] | None = None,
        tool_registry=None,
        host: str = "0.0.0.0",
        port: int = 8765,
    ):
        self.stop_event = stop_event
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.text_output_queue = text_output_queue
        self.text_prompt_queue = text_prompt_queue
        self.should_listen = should_listen
        self.response_playing = response_playing
        self.cancel_scope = cancel_scope
        self.runtime_config = runtime_config or RuntimeConfig()
        self.internal_queues = internal_queues or []
        self.tool_registry = tool_registry
        self.host = host
        self.port = port
        self.chat_ref = None
        self.turn_audio_history = None

    def run(self):
        """Start the FastAPI/uvicorn server (called from a ThreadManager thread)."""
        service = RealtimeService(
            runtime_config=self.runtime_config,
            text_prompt_queue=self.text_prompt_queue,
            should_listen=self.should_listen,
            turn_audio_history=self.turn_audio_history,
            tool_registry=self.tool_registry,
        )
        app = create_app(
            service=service,
            input_queue=self.input_queue,
            output_queue=self.output_queue,
            text_output_queue=self.text_output_queue,
            should_listen=self.should_listen,
            response_playing=self.response_playing,
            cancel_scope=self.cancel_scope,
            stop_event=self.stop_event,
            chat_ref=self.chat_ref,
            internal_queues=self.internal_queues,
        )

        logger.info(
            f"OpenAI Realtime API server starting on ws://{self.host}:{self.port}/v1/realtime/{{audio,text}}"
        )

        config = uvicorn.Config(
            app,
            host=self.host,
            port=self.port,
            log_level="info",
            ws_ping_interval=_ws_ping_setting("OPENAI_REALTIME_WS_PING_INTERVAL", 20.0),
            ws_ping_timeout=_ws_ping_setting("OPENAI_REALTIME_WS_PING_TIMEOUT", 20.0),
        )
        server = uvicorn.Server(config)

        server.install_signal_handlers = lambda: None

        def _watch_stop():
            self.stop_event.wait()
            server.should_exit = True

        watcher = threading.Thread(target=_watch_stop, daemon=True)
        watcher.start()

        server.run()

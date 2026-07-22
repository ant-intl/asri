"""
Voice WebSocket consumer for Django Channels.

Thin wrapper that bridges the OpenAI Realtime WebSocket protocol into
Voice's existing threading pipeline, replacing the standalone FastAPI server.
"""
import asyncio
import base64
import json
import logging
import os
import re
from queue import Empty, Queue
from threading import Event as ThreadingEvent
from typing import Callable, Optional

from channels.generic.websocket import AsyncWebsocketConsumer

logger = logging.getLogger(__name__)

MAX_AUDIO_BATCH_BYTES = 6400

# Module-level singleton: only one active voice session allowed
_active_session: Optional["VoiceConsumer"] = None


def _keep_audio_sentinel(item) -> bool:
    return isinstance(item, bytes) and item == b"__RESPONSE_DONE__"


def _keep_user_text_event(item) -> bool:
    if not isinstance(item, dict):
        return False
    return item.get("type") in ("speech_stopped", "token_usage")


class VoiceConsumer(AsyncWebsocketConsumer):
    """
    Django Channels consumer that bridges OpenAI Realtime WebSocket protocol
    into Voice's threading pipeline.

    Replaces voice/asri_voice/api/openai_realtime/websocket_router.py by:
    - Building the pipeline via build_pipeline_from_yaml() (no FastAPI/uvicorn)
    - Handling WebSocket ↔ Queue bridging directly in async methods
    - Reusing RealtimeService for protocol translation (stateless per-event)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pipeline_result: Optional[dict] = None
        self._service = None
        self._session_id: Optional[str] = None
        self._send_task: Optional[asyncio.Task] = None
        self._audio_response_done = False
        self._pending_output_sentinel = None
        self._text_only = False
        self._active = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        global _active_session

        force = self._get_query_param("force")
        if force and force.lower() in ("1", "true", "yes"):
            if _active_session is not None:
                logger.info("Force-closing existing voice session")
                try:
                    await _active_session.close(code=3001)
                except Exception:
                    pass
                # Give the closed session time to clean up
                for _ in range(50):
                    if _active_session is None:
                        break
                    await asyncio.sleep(0.1)
        elif _active_session is not None:
            logger.warning("Rejected voice connection: session already active")
            await self.accept()
            await self.send_json({
                "type": "error",
                "error": {
                    "type": "session_limit_reached",
                    "message": "Only one concurrent session is supported. "
                               "Disconnect the existing client first, "
                               "or add ?force=true to replace it.",
                },
            })
            await self.close(code=3008)
            return

        await self.accept()

        try:
            await self._start_pipeline()
        except Exception as e:
            logger.error("Failed to start voice pipeline: %s", e, exc_info=True)
            await self.send_json({
                "type": "error",
                "error": {"type": "pipeline_start_failed", "message": str(e)},
            })
            await self.close(code=3011)
            return

        _active_session = self
        self._session_id = self._service.register()
        self._service.runtime_config.start_connection(self._session_id)
        self._active = True

        # Clean session state before use
        self._clean_session()

        # Set modalities
        modalities = getattr(
            self._service.runtime_config.session, "modalities", None
        )
        if modalities is None or "audio" not in modalities:
            self._service.runtime_config.session.modalities = ["text", "audio"]

        logger.info("Voice client connected (session %s)", self._session_id)
        await self.send_json(
            self._service.build_session_created(self._session_id)
        )

    async def receive(self, text_data=None, bytes_data=None):
        if not self._active or not text_data:
            return
        try:
            raw = json.loads(text_data)
        except json.JSONDecodeError:
            return

        await self._handle_client_event(raw)

    async def disconnect(self, code):
        global _active_session
        self._active = False

        # Stop send loop
        if self._send_task and not self._send_task.done():
            self._send_task.cancel()
            try:
                await self._send_task
            except (asyncio.CancelledError, Exception):
                pass

        # Clean up pipeline
        if self._pipeline_result:
            self._clean_session(wait_for_reset=True)
            if self._service:
                self._service.unregister(self._session_id or "")
                if not self._service._conns:
                    tr = self._service.tool_registry
                    if tr is not None and hasattr(tr, "clear_dynamic_tools"):
                        tr.clear_dynamic_tools()
                    self._service.runtime_config.reset()

            # Stop pipeline threads
            manager = self._pipeline_result.get("manager")
            if manager:
                queues = self._pipeline_result["queues"]
                queues["stop_event"].set()
                manager.stop()
            self._pipeline_result = None

        if _active_session is self:
            _active_session = None

        logger.info("Voice client disconnected (session %s, code %s)",
                     self._session_id, code)

    # ------------------------------------------------------------------
    # Pipeline management
    # ------------------------------------------------------------------

    async def _start_pipeline(self):
        """Build and start the voice pipeline from YAML config."""
        config_path = self._resolve_config_path()

        # Resolve tenant_id (must match admin UI's tenant for config lookup)
        tenant_id = self._resolve_tenant_id()

        # Read Django config (LLM, prompt, tools) for override
        django_config = None
        try:
            from voice_django.django_config_reader import DjangoConfigReader
            reader = DjangoConfigReader(tenant_id=tenant_id)
            django_config = await reader.read_all()
            logger.info("Loaded Django config for tenant=%s", tenant_id)
        except Exception as e:
            logger.warning("Could not load Django config, using YAML only: %s", e)

        # Run in thread to avoid blocking the event loop
        from main import build_pipeline_from_yaml

        result = await asyncio.to_thread(
            build_pipeline_from_yaml, config_path, "django", django_config
        )

        self._pipeline_result = result
        queues = result["queues"]
        runtime_config = result["runtime_config"]

        # Create RealtimeService for protocol translation
        from api.openai_realtime.service import RealtimeService

        self._service = RealtimeService(
            runtime_config=runtime_config,
            text_prompt_queue=queues["text_prompt_queue"],
            should_listen=queues["should_listen"],
            tool_registry=result.get("tool_registry"),
        )

        # Start pipeline threads
        result["manager"].start()

        # Start send loop
        self._send_task = asyncio.create_task(self._send_loop())

    # ------------------------------------------------------------------
    # Client event handling (WebSocket → pipeline queues)
    # ------------------------------------------------------------------

    async def _handle_client_event(self, raw: dict):
        """Parse and dispatch a client event to the pipeline."""
        event = self._service.parse_client_event(raw)
        if event is None:
            # Handle custom events
            if raw.get("type") == "conversation.history.set":
                self._service.handle_conversation_history_set(raw)
                return
            await self.send_json(
                self._service.make_error(
                    f"Unknown or invalid event: {raw.get('type')}",
                    "unknown_or_invalid_event",
                )
            )
            return

        from openai.types.realtime import (
            InputAudioBufferAppendEvent,
            InputAudioBufferCommitEvent,
            SessionUpdateEvent,
            ConversationItemCreateEvent,
            ResponseCreateEvent,
            ResponseCancelEvent,
        )

        queues = self._pipeline_result["queues"]

        if isinstance(event, InputAudioBufferAppendEvent):
            chunks = self._service.handle_audio_append(self._session_id, event)
            for chunk in chunks:
                queues["recv_audio_chunks_queue"].put(chunk)

        elif isinstance(event, InputAudioBufferCommitEvent):
            err = self._service.handle_audio_commit(self._session_id)
            if err:
                await self.send_json(err)

        elif isinstance(event, SessionUpdateEvent):
            err = self._service.handle_session_update(event)
            if err:
                await self.send_json(err)

        elif isinstance(event, ConversationItemCreateEvent):
            events = self._service.handle_conversation_item_create(
                self._session_id, event
            )
            if events:
                for ev in events:
                    await self.send_json(ev)

        elif isinstance(event, ResponseCreateEvent):
            result = self._service.handle_response_create(self._session_id, event)
            if result:
                cancel_scope = queues["cancel_scope"]
                if result.type != "error" and cancel_scope:
                    cancel_scope.new_response()
                await self.send_json(result)

        elif isinstance(event, ResponseCancelEvent):
            queues = self._pipeline_result["queues"]
            cancel_scope = queues["cancel_scope"]
            was_active = self._service._state(self._session_id).in_response
            if was_active and cancel_scope:
                cancel_scope.cancel()
            self._flush_queue(
                queues["send_audio_chunks_queue"], preserve=_keep_audio_sentinel
            )
            self._flush_queue(
                queues["text_output_queue"], preserve=_keep_user_text_event
            )
            events = self._service.handle_response_cancel(self._session_id)
            if events:
                for ev in events:
                    await self.send_json(ev)
            response_playing = queues.get("response_playing")
            if response_playing:
                response_playing.clear()

    # ------------------------------------------------------------------
    # Send loop (pipeline queues → WebSocket)
    # ------------------------------------------------------------------

    async def _send_loop(self):
        """Poll pipeline output queues and send events to the WebSocket client."""
        queues = self._pipeline_result["queues"]
        output_queue = queues["send_audio_chunks_queue"]
        text_output_queue = queues["text_output_queue"]
        cancel_scope = queues["cancel_scope"]
        stop_event = queues["stop_event"]
        should_listen = queues["should_listen"]
        response_playing = queues.get("response_playing")
        internal_queues = [
            queues["stt_output_queue"],
            queues["text_prompt_queue"],
            queues["lm_response_queue"],
            queues["lm_processed_queue"],
        ]

        from pipeline.control import SESSION_END, is_control_message

        while self._active and not stop_event.is_set():
            try:
                # --- Process text events first ---
                try:
                    text_msg = text_output_queue.get_nowait()
                    msg_type = text_msg.get("type")
                    is_speech_start = msg_type == "speech_started"

                    if is_speech_start:
                        self._audio_response_done = False

                    if msg_type == "iteration_done":
                        self._audio_response_done = False

                    msg_gen = text_msg.get("generation")
                    if (
                        cancel_scope
                        and msg_gen is not None
                        and cancel_scope.is_stale(msg_gen)
                    ):
                        continue

                    was_in_response = False
                    if is_speech_start and self._session_id:
                        was_in_response = self._service._state(
                            self._session_id
                        ).in_response
                    cancelled_for_speech = (
                        is_speech_start
                        and was_in_response
                        and self._service.runtime_config.interrupt_response_enabled
                    )

                    if cancelled_for_speech:
                        if cancel_scope:
                            cancel_scope.cancel()
                        self._flush_queue(output_queue)
                        self._flush_queue(
                            text_output_queue, preserve=_keep_user_text_event
                        )
                        for q in internal_queues:
                            self._flush_queue(q)
                        self._pending_output_sentinel = None
                        if response_playing and response_playing.is_set():
                            response_playing.clear()

                    if self._audio_response_done and msg_type == "assistant_text":
                        pass  # drop stale
                    else:
                        events = self._service.translate_pipeline_text(
                            self._session_id, text_msg
                        )
                        if events:
                            for ev in events:
                                await self.send_json(ev)

                    if cancelled_for_speech:
                        if cancel_scope:
                            cancel_scope.response_done()
                    elif is_speech_start and was_in_response:
                        pass  # interrupt disabled
                except Empty:
                    pass

                # --- Process audio output ---
                try:
                    if self._pending_output_sentinel is not None:
                        audio_chunk = self._pending_output_sentinel
                        self._pending_output_sentinel = None
                    else:
                        audio_chunk = output_queue.get_nowait()

                    # END sentinel
                    if isinstance(audio_chunk, bytes) and audio_chunk == b"END":
                        events = self._service.finish_audio_response(self._session_id)
                        for ev in events:
                            await self.send_json(ev)
                        break

                    # RESPONSE_DONE sentinel
                    if (
                        isinstance(audio_chunk, bytes)
                        and audio_chunk == b"__RESPONSE_DONE__"
                    ):
                        pending_text = []
                        deferred_text = []
                        while True:
                            try:
                                tm = text_output_queue.get_nowait()
                            except Empty:
                                break
                            if tm.get("type") == "llm_metrics":
                                pending_text.append(tm)
                            else:
                                deferred_text.append(tm)

                        events = self._service.finish_audio_response(
                            self._session_id
                        )
                        for tm in pending_text:
                            events.extend(
                                self._service.translate_pipeline_text(
                                    self._session_id, tm
                                )
                            )
                        for tm in deferred_text:
                            events.extend(
                                self._service.translate_pipeline_text(
                                    self._session_id, tm
                                )
                            )
                        for ev in events:
                            await self.send_json(ev)
                        self._audio_response_done = True
                        if response_playing:
                            response_playing.clear()
                        if cancel_scope:
                            cancel_scope.response_done()
                        should_listen.set()
                        continue

                    if is_control_message(audio_chunk, SESSION_END.kind):
                        continue

                    if cancel_scope and cancel_scope.discarding:
                        if cancel_scope.discarding_duration > 5.0:
                            cancel_scope.response_done()
                        else:
                            continue

                    if self._text_only:
                        continue

                    audio_chunk = self._to_audio_bytes(audio_chunk)
                    audio_batch = bytearray(audio_chunk)

                    while len(audio_batch) < MAX_AUDIO_BATCH_BYTES:
                        try:
                            next_chunk = output_queue.get_nowait()
                        except Empty:
                            break
                        if (
                            isinstance(next_chunk, bytes)
                            and next_chunk in {b"END", b"__RESPONSE_DONE__"}
                        ) or is_control_message(next_chunk, SESSION_END.kind):
                            self._pending_output_sentinel = next_chunk
                            break
                        next_audio = self._to_audio_bytes(next_chunk)
                        if len(audio_batch) + len(next_audio) > MAX_AUDIO_BATCH_BYTES:
                            self._pending_output_sentinel = next_chunk
                            break
                        audio_batch.extend(next_audio)

                    if response_playing and not response_playing.is_set():
                        response_playing.set()
                        should_listen.set()

                    events = self._service.encode_audio_chunk(
                        self._session_id, bytes(audio_batch)
                    )
                    for ev in events:
                        await self.send_json(ev)
                except Empty:
                    pass

                await asyncio.sleep(0.01)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Voice send loop error: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def _flush_queue(self, q: Queue, *, preserve: Optional[Callable] = None):
        """Drain a queue, optionally preserving items matching *preserve*."""
        from pipeline.fork_queue import ForkQueue

        if isinstance(q, ForkQueue):
            for downstream in q.downstreams:
                self._flush_queue(downstream, preserve=preserve)
            return

        preserved = []
        while True:
            try:
                item = q.get_nowait()
                if preserve and preserve(item):
                    preserved.append(item)
            except Empty:
                break
        if preserved:
            with q.mutex:
                for item in reversed(preserved):
                    q.queue.appendleft(item)
                q.not_empty.notify(len(preserved))

    def _clean_session(
        self,
        preserve: Optional[Callable] = None,
        *,
        signal_input_end: bool = True,
        wait_for_reset: bool = False,
    ):
        """Reset session state and flush all pipeline queues."""
        if not self._pipeline_result:
            return

        queues = self._pipeline_result["queues"]
        cancel_scope = queues["cancel_scope"]
        input_queue = queues["recv_audio_chunks_queue"]
        output_queue = queues["send_audio_chunks_queue"]
        text_output_queue = queues["text_output_queue"]
        should_listen = queues["should_listen"]
        response_playing = queues.get("response_playing")

        from pipeline.control import SESSION_END

        internal_queues = [
            queues["stt_output_queue"],
            queues["text_prompt_queue"],
            queues["lm_response_queue"],
            queues["lm_processed_queue"],
        ]

        self._audio_response_done = False
        self._pending_output_sentinel = None

        if cancel_scope:
            cancel_scope.cancel()
        self._flush_queue(input_queue)
        self._flush_queue(output_queue, preserve=preserve)
        self._flush_queue(text_output_queue, preserve=preserve)
        for q in internal_queues:
            self._flush_queue(q)
        if signal_input_end:
            input_queue.put(SESSION_END)
        for q in internal_queues:
            q.put(SESSION_END)
        if response_playing:
            response_playing.clear()
        if cancel_scope:
            cancel_scope.reset()
        should_listen.set()

        if wait_for_reset:
            import time
            time.sleep(0.3)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _to_audio_bytes(audio_chunk) -> bytes:
        if hasattr(audio_chunk, "tobytes"):
            return audio_chunk.tobytes()
        return audio_chunk

    async def send_json(self, data):
        """Send JSON data (dict or Pydantic model) through WebSocket."""
        if isinstance(data, dict):
            payload = data
        elif hasattr(data, "model_dump"):
            payload = data.model_dump()
        else:
            payload = data
        await self.send(text_data=json.dumps(payload, ensure_ascii=False))

    def _get_query_param(self, name: str) -> Optional[str]:
        """Extract a query parameter from the connection scope."""
        query_string = self.scope.get("query_string", b"").decode()
        if not query_string:
            return None
        params = dict(
            param.split("=", 1)
            for param in query_string.split("&")
            if "=" in param
        )
        return params.get(name)

    def _resolve_config_path(self) -> str:
        """Resolve the voice YAML config path.

        Priority:
        1. VOICE_CONFIG_PATH environment variable (absolute or relative to project root).
        2. ``?config=filename.yaml`` query parameter, restricted to voice/configs/.
        3. Default ``voice/configs/asri-voice.yaml``.
        """
        env_path = os.environ.get("VOICE_CONFIG_PATH")
        if env_path:
            if os.path.isabs(env_path):
                return env_path
            project_root = self._project_root()
            return os.path.join(project_root, env_path)

        config_name = self._get_query_param("config")
        if config_name:
            # Reject path traversal and hidden files
            if re.match(r"^[A-Za-z0-9_\-]+\.ya?ml$", config_name):
                project_root = self._project_root()
                return os.path.join(project_root, "voice", "configs", config_name)
            logger.warning("Invalid config query parameter: %s", config_name)

        project_root = self._project_root()
        return os.path.join(project_root, "voice", "configs", "asri-voice.yaml")

    def _project_root(self) -> str:
        """Return the project root directory."""
        return os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
        )

    def _resolve_tenant_id(self) -> str:
        """Resolve tenant_id for Django config lookup.

        Priority:
        1. ``tenant_id`` query parameter in WebSocket URL
        2. ``X-Tenant-Id`` HTTP header
        3. Bearer token → TenantRegistry resolution
        4. ``'default'`` fallback (matches admin UI's DefaultAdminAuthProvider)
        """
        # 1. Query parameter
        tenant_id = self._get_query_param("tenant_id")
        if tenant_id:
            return tenant_id

        # 2. X-Tenant-Id header
        headers = dict(self.scope.get("headers", []))
        raw = headers.get(b"x-tenant-id", b"")
        if raw:
            return raw.decode()

        # 3. Bearer token → TenantRegistry
        raw_token = self._get_bearer_token()
        if raw_token:
            try:
                from apps.tenant.registry import get_tenant_registry
                registry = get_tenant_registry()
                resolved = registry.get_tenant_id_by_token(raw_token)
                if resolved:
                    return resolved
            except Exception as e:
                logger.warning("Failed to resolve tenant from token: %s", e)

        # 4. Fallback: 'default' (matches admin UI default)
        return "default"

    def _get_bearer_token(self) -> Optional[str]:
        """Extract Bearer token from connection scope."""
        headers = dict(self.scope.get("headers", []))
        auth_value = headers.get(b"authorization", b"").decode()
        if auth_value.startswith("Bearer "):
            return auth_value[7:].strip() or None
        return None

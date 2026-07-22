import asyncio
import logging
from contextlib import asynccontextmanager
from queue import Empty, Queue
from threading import Event as ThreadingEvent
from typing import Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from api.openai_realtime.service import RealtimeService, ServerEvent
from pipeline.cancel_scope import CancelScope
from pipeline.control import SESSION_END, is_control_message

from openai.types.realtime import (
    InputAudioBufferAppendEvent,
    InputAudioBufferCommitEvent,
    SessionUpdateEvent,
    ConversationItemCreateEvent,
    ResponseCreateEvent,
    ResponseCancelEvent,
)

logger = logging.getLogger(__name__)
MAX_AUDIO_BATCH_BYTES = 6400


async def _send_event(ws: WebSocket, event: ServerEvent) -> None:
    try:
        payload = event if isinstance(event, dict) else event.model_dump()
        await ws.send_json(payload)
    except Exception as e:
        logger.error(f"Failed to send event to client: {e}")


async def _send_events(ws: WebSocket, events: list[ServerEvent]) -> None:
    for event in events:
        await _send_event(ws, event)


def _keep_audio_sentinel(item) -> bool:
    return isinstance(item, bytes) and item == b"__RESPONSE_DONE__"


def _keep_user_text_event(item) -> bool:
    if not isinstance(item, dict):
        return False
    return item.get("type") in ("speech_stopped", "token_usage")


def create_app(
    service: RealtimeService,
    input_queue: Queue,
    output_queue: Queue,
    text_output_queue: Queue,
    should_listen: ThreadingEvent,
    response_playing: ThreadingEvent | None,
    cancel_scope: CancelScope | None,
    stop_event: ThreadingEvent,
    chat_ref=None,
    internal_queues: list[Queue] | None = None,
) -> FastAPI:

    # Shared between _send_loop and clean_session — reset on disconnect
    _audio_response_done = False
    _pending_output_sentinel = None

    def _flush_queue(q: Queue, *, preserve: Callable | None = None) -> None:
        """Drain a queue, optionally preserving items matching *preserve*.

        Preserved items are re-inserted at the **front** of the queue
        (atomically under the queue's mutex) so they are processed before
        anything a pipeline thread may have enqueued during the drain.

        If *q* is a ForkQueue, flush each downstream queue instead
        (ForkQueue is write-only and has no items of its own).
        """
        from pipeline.fork_queue import ForkQueue
        if isinstance(q, ForkQueue):
            for downstream in q.downstreams:
                _flush_queue(downstream, preserve=preserve)
            return
        preserved: list = []
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
        
    def clean_session(preserve: Callable | None = None, *, signal_input_end: bool = True, wait_for_reset: bool = False):
        # Invalidate in-flight LLM/TTS work (cooperative cancel via is_stale), then
        # flush queues. reset() clears discarding only; generation stays bumped.
        # Blocking HTTP reads are not interrupted here; see OpenApiModelHandler.process.
        nonlocal _audio_response_done, _pending_output_sentinel
        _audio_response_done = False
        _pending_output_sentinel = None
        if cancel_scope:
            cancel_scope.cancel()
        _flush_queue(input_queue)
        _flush_queue(output_queue, preserve=preserve)
        _flush_queue(text_output_queue, preserve=preserve)
        for q in (internal_queues or []):
            _flush_queue(q)
        if signal_input_end:
            input_queue.put(SESSION_END)
        # Send SESSION_END directly to internal queues so LLM chat state,
        # LM output processing, and TTS all reset immediately.  Relying
        # only on propagation from input_queue can race with reconnect:
        # the next connection may flush queues before SESSION_END reaches
        # the LLM, leaving old conversation history alive.
        if internal_queues:
            for q in internal_queues:
                q.put(SESSION_END)
        if response_playing:
            response_playing.clear()
        if cancel_scope:
            cancel_scope.reset()
        should_listen.set()
        # Optionally wait for handlers to process SESSION_END and call
        # on_session_end().  This ensures state is fully cleared before
        # the next connection reuses the server.
        if wait_for_reset:
            import time
            time.sleep(0.3)

    def _to_audio_bytes(audio_chunk) -> bytes:
        if hasattr(audio_chunk, "tobytes"):
            return audio_chunk.tobytes()
        return audio_chunk

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.websockets = {}
        app.state.active_session: str | None = None
        app.state.text_only = False
        app.state.send_task = asyncio.create_task(_send_loop())
        yield
        app.state.send_task.cancel()
        try:
            await app.state.send_task
        except asyncio.CancelledError:
            pass
        for ws in list(app.state.websockets.values()):
            try:
                await ws.close()
            except Exception:
                pass

    app = FastAPI(lifespan=lifespan)

    async def _force_close_existing_sessions():
        """Close all existing WebSocket sessions to make room for a new one."""
        for sid, existing_ws in list(app.state.websockets.items()):
            logger.info(f"Force-closing existing session {sid}")
            try:
                await existing_ws.close(
                    code=1001,
                    reason="Session replaced by a new connection",
                )
            except Exception as e:
                logger.warning(f"Error closing session {sid}: {e}")
        # Give the closed sessions a moment to run their finally blocks
        for _ in range(50):
            if not app.state.websockets:
                break
            await asyncio.sleep(0.1)

    async def _handle_realtime_connection(ws: WebSocket, text_only: bool = False):
        """Shared connection handler for both /v1/realtime/audio and /v1/realtime/text."""
        await ws.accept()

        force = ws.query_params.get("force", "").lower() in ("1", "true", "yes")

        if app.state.websockets:
            if force:
                await _force_close_existing_sessions()
            else:
                logger.warning("Rejected connection: a session is already active")
                await _send_event(
                    ws,
                    service.make_error(
                        "Only one concurrent session is supported. "
                        "Disconnect the existing client first, "
                        "or add ?force=true to replace it.",
                        _type="session_limit_reached",
                    ),
                )
                await ws.close(code=1008, reason="Only one concurrent session is supported")
                return

        session_id = service.register()
        service.runtime_config.start_connection(session_id)
        app.state.websockets[session_id] = ws
        app.state.active_session = session_id
        app.state.text_only = text_only
        mode_label = "text-only" if text_only else "audio"
        logger.info(f"Client connected (session {session_id}, mode={mode_label})")

        # Set modalities based on endpoint
        if text_only:
            service.runtime_config.session.modalities = ["text"]
            logger.info("Text-only mode: modalities set to ['text']")
        else:
            modalities = getattr(service.runtime_config.session, "modalities", None)
            if modalities is None or "audio" not in modalities:
                service.runtime_config.session.modalities = ["text", "audio"]

        # Defensive: drain edge queues and reset events so stale data from a
        # previous session that survived SESSION_END propagation doesn't leak.
        clean_session()

        try:
            await _send_event(ws, service.build_session_created(session_id))

            while not stop_event.is_set():
                try:
                    raw = await asyncio.wait_for(ws.receive_json(), timeout=0.1)
                except asyncio.TimeoutError:
                    continue

                event = service.parse_client_event(raw)
                if event is None:
                    # Custom eval-only events (no Pydantic model needed)
                    if raw.get("type") == "conversation.history.set":
                        service.handle_conversation_history_set(raw)
                        continue
                    await _send_event(
                        ws, service.make_error(f"Unknown or invalid event: {raw.get('type')}", "unknown_or_invalid_event")
                    )
                    continue

                if isinstance(event, InputAudioBufferAppendEvent):
                    chunks = service.handle_audio_append(session_id, event)
                    for chunk in chunks:
                        input_queue.put(chunk)

                elif isinstance(event, InputAudioBufferCommitEvent):
                    err = service.handle_audio_commit(session_id)
                    if err:
                        await _send_event(ws, err)

                elif isinstance(event, SessionUpdateEvent):
                    err = service.handle_session_update(event)
                    if err:
                        await _send_event(ws, err)

                elif isinstance(event, ConversationItemCreateEvent):
                    events = service.handle_conversation_item_create(session_id, event)
                    if events:
                        await _send_events(ws, events)

                elif isinstance(event, ResponseCreateEvent):
                    result = service.handle_response_create(session_id, event)
                    if result:
                        if result.type != "error" and cancel_scope:
                            cancel_scope.new_response()
                        await _send_event(ws, result)

                elif isinstance(event, ResponseCancelEvent):
                    was_active = service._state(session_id).in_response
                    if was_active and cancel_scope:
                        cancel_scope.cancel()
                    _flush_queue(output_queue, preserve=_keep_audio_sentinel)
                    _flush_queue(text_output_queue, preserve=_keep_user_text_event)
                    events = service.handle_response_cancel(session_id)
                    if events:
                        await _send_events(ws, events)
                    if response_playing:
                        response_playing.clear()

        except WebSocketDisconnect:
            logger.info(f"Client {session_id} disconnected")
        except Exception as e:
            logger.error(f"Client {session_id} error: {type(e).__name__}: {e}", exc_info=True)
        finally:
            clean_session(wait_for_reset=True)
            service.unregister(session_id)
            if not service._conns:
                if service.tool_registry is not None and hasattr(service.tool_registry, "clear_dynamic_tools"):
                    service.tool_registry.clear_dynamic_tools()
                service.runtime_config.reset()
                logger.info("Last client disconnected, reset RuntimeConfig/tool registry and sent SESSION_END")
            app.state.websockets.pop(session_id, None)
            app.state.active_session = None
            app.state.text_only = False
            logger.info(f"Client {session_id} removed")

    @app.websocket("/v1/realtime")
    async def realtime_endpoint(ws: WebSocket):
        await _handle_realtime_connection(ws, text_only=False)

    @app.websocket("/v1/realtime/audio")
    async def realtime_audio_endpoint(ws: WebSocket):
        await _handle_realtime_connection(ws, text_only=False)

    @app.websocket("/v1/realtime/text")
    async def realtime_text_endpoint(ws: WebSocket):
        await _handle_realtime_connection(ws, text_only=True)

    @app.post("/v1/force-disconnect")
    async def force_disconnect():
        """Force-close the active session so a new client can connect."""
        if not app.state.websockets:
            return {"status": "ok", "message": "No active session"}
        await _force_close_existing_sessions()
        return {"status": "ok", "message": "Active session force-closed"}

    @app.get("/v1/usage")
    async def usage_endpoint():
        return service.get_usage()

    @app.get("/v1/debug/messages")
    async def debug_messages():
        if chat_ref is None:
            return {"messages": [], "error": "chat_ref not configured"}
        return {"messages": chat_ref.to_list()}

    @app.get("/v1/debug/session")
    async def debug_session():
        return {
            "active_session": app.state.active_session,
            "websocket_count": len(app.state.websockets),
            "text_only": app.state.text_only,
        }

    async def _send_loop():
        """Poll pipeline output queues and send to each connected client."""
        nonlocal _audio_response_done, _pending_output_sentinel
        while not stop_event.is_set():
            try:
                # Process text events first (speech_started cancels active response)
                if text_output_queue:
                    try:
                        text_msg = text_output_queue.get_nowait()
                        msg_type = text_msg.get("type")
                        is_speech_start = msg_type == "speech_started"

                        if is_speech_start:
                            _audio_response_done = False

                        # iteration_done signals a new agentloop iteration is coming;
                        # reset the gate so subsequent assistant_text is not dropped.
                        if msg_type == "iteration_done":
                            _audio_response_done = False

                        msg_gen = text_msg.get("generation")
                        if (
                            cancel_scope
                            and msg_gen is not None
                            and cancel_scope.is_stale(msg_gen)
                        ):
                            logger.debug("Dropping stale text event %s (gen=%s)", msg_type, msg_gen)
                            continue

                        # Capture response state before translate modifies it. To change when multiple sessions are supported.
                        was_in_response = False
                        if is_speech_start and app.state.active_session:
                            was_in_response = service._state(app.state.active_session).in_response
                        cancelled_for_speech = (
                            is_speech_start
                            and was_in_response
                            and service.runtime_config.interrupt_response_enabled
                        )

                        if cancelled_for_speech:
                            if cancel_scope:
                                cancel_scope.cancel()
                            _flush_queue(output_queue)  # discard stale audio + __RESPONSE_DONE__ from cancelled response
                            _flush_queue(text_output_queue, preserve=_keep_user_text_event)
                            # Flush internal queues too — stale text from the
                            # cancelled response would otherwise leak into TTS
                            # (gen is already bumped, so PrefetchHandler can't
                            #  distinguish old sentence from new response).
                            for q in (internal_queues or []):
                                _flush_queue(q)
                            # Race-3 fix: unconditionally clear the pending
                            # output sentinel. Previously only cleared when it
                            # held __RESPONSE_DONE__, leaving a stale audio
                            # ndarray that would be sent on the next loop
                            # iteration ("residual audio after interrupt").
                            _pending_output_sentinel = None
                            if response_playing and response_playing.is_set():
                                response_playing.clear()

                        if _audio_response_done and msg_type == "assistant_text":
                            logger.debug("Dropping stale assistant_text after audio response done")
                        else:
                            for cid in service.connection_ids:
                                ws = app.state.websockets.get(cid)
                                if ws:
                                    events = service.translate_pipeline_text(cid, text_msg)
                                    if events:
                                        await _send_events(ws, events)

                        if cancelled_for_speech:
                            # Clear discarding so the NEW response's audio can
                            # flow. Stale audio is guarded by:
                            #   - PrefetchHandler gen checks (drops stale TTS
                            #     chunks at emit time)
                            #   - cancel_scope.is_stale(gen) in TTS handlers
                            #   - the unconditional sentinel clear above
                            # The discarding flag stays set only for the
                            # duration of this synchronous block, so there is
                            # no window where new audio is wrongly dropped.
                            if cancel_scope:
                                cancel_scope.response_done()
                            logger.info("Speech during response: cancelled, queue flushed")
                        elif is_speech_start and was_in_response:
                            logger.info("Speech during response: interrupt_response disabled, ignoring")
                    except Empty:
                        pass

                try:
                    if _pending_output_sentinel is not None:
                        audio_chunk = _pending_output_sentinel
                        _pending_output_sentinel = None
                    else:
                        audio_chunk = output_queue.get_nowait()

                    if isinstance(audio_chunk, bytes) and audio_chunk == b"END":
                        for cid in service.connection_ids:
                            ws = app.state.websockets.get(cid)
                            if ws:
                                await _send_events(ws, service.finish_audio_response(cid))
                        break

                    if isinstance(audio_chunk, bytes) and audio_chunk == b"__RESPONSE_DONE__":
                        # Drain any pending llm_metrics from text_output_queue so they
                        # are sent in the SAME batch as response.done. Without this,
                        # llm_metrics is published on the text queue (separate from
                        # this audio queue) and may arrive on the wire AFTER
                        # response.done — which races against client-side teardown
                        # and produces null server latencies in eval results.
                        #
                        # Non-llm_metrics items (e.g. assistant_text from a new turn)
                        # are sent in the same batch BEFORE _audio_response_done is set,
                        # so they aren't dropped by the gate on the next iteration.
                        pending_text_msgs: list[dict] = []
                        deferred_text_msgs: list[dict] = []
                        while True:
                            try:
                                tm = text_output_queue.get_nowait()
                            except Empty:
                                break
                            if tm.get("type") == "llm_metrics":
                                pending_text_msgs.append(tm)
                            else:
                                deferred_text_msgs.append(tm)

                        for cid in service.connection_ids:
                            ws = app.state.websockets.get(cid)
                            if ws:
                                events = service.finish_audio_response(cid)
                                for tm in pending_text_msgs:
                                    events.extend(service.translate_pipeline_text(cid, tm))
                                for tm in deferred_text_msgs:
                                    events.extend(service.translate_pipeline_text(cid, tm))
                                await _send_events(ws, events)
                        _audio_response_done = True
                        if response_playing:
                            response_playing.clear()
                        if cancel_scope:
                            cancel_scope.response_done()
                        should_listen.set()
                        logger.info("Response complete, listening re-enabled")
                        continue

                    if is_control_message(audio_chunk, SESSION_END.kind):
                        continue

                    if cancel_scope and cancel_scope.discarding:
                        if cancel_scope.discarding_duration > 5.0:
                            logger.warning(
                                "CancelScope.discarding stuck for %.1fs — force-clearing",
                                cancel_scope.discarding_duration,
                            )
                            cancel_scope.response_done()
                        else:
                            continue

                    # Text-only mode: discard audio chunks, only sentinels matter
                    if app.state.text_only:
                        continue

                    audio_chunk = _to_audio_bytes(audio_chunk)

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
                            _pending_output_sentinel = next_chunk
                            break

                        next_audio = _to_audio_bytes(next_chunk)
                        if len(audio_batch) + len(next_audio) > MAX_AUDIO_BATCH_BYTES:
                            _pending_output_sentinel = next_chunk
                            break
                        audio_batch.extend(next_audio)

                    if response_playing and not response_playing.is_set():
                        response_playing.set()
                        should_listen.set()

                    for cid in service.connection_ids:
                        ws = app.state.websockets.get(cid)
                        if ws:
                            await _send_events(ws, service.encode_audio_chunk(cid, bytes(audio_batch)))
                except Empty:
                    pass

                await asyncio.sleep(0.01)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Send loop error: {e}")

    return app

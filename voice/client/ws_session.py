"""WebSocket session helpers for the replay client.

These functions wrap the low-level WebSocket messages that the realtime
server expects:

* ``session.update`` — negotiate modalities (text only for replay).
* ``conversation.history.set`` — send the seed conversation history
  before streaming the current turn's audio.

The helpers are intentionally small and side-effect free so they can be
unit tested in isolation.
"""

from __future__ import annotations

import json
from typing import Any


async def send_session_update(ws, *, modalities: list[str] | None = None) -> None:
    """Send a ``session.update`` message to configure the realtime session.

    Parameters
    ----------
    ws:
        An open ``websockets`` connection.
    modalities:
        List of output modalities to request.  Defaults to ``["text"]``,
        which is what the replay client uses (no TTS synthesis needed).
    """
    if modalities is None:
        modalities = ["text"]
    session = {
        "type": "realtime",
        "audio": {"input": {}, "output": {}},
        "modalities": modalities,
    }
    await ws.send(json.dumps({"type": "session.update", "session": session}))


async def send_history(
    ws,
    *,
    history_payload: dict[str, Any],
    trace_level: str = "replay",
    disable_response_generation: bool = True,
) -> None:
    """Send a ``conversation.history.set`` message to seed the conversation.

    Parameters
    ----------
    ws:
        An open ``websockets`` connection.
    history_payload:
        Dict with keys like ``messages``, ``audio_paths``, ``tools``,
        ``tool_mock_examples``, ``extra_instructions``.
    trace_level:
        Server event verbosity.  Use ``"replay"`` to receive
        prompt/message snapshots for SFT sample construction.
    disable_response_generation:
        If True (default), the server will not generate a response after
        the audio is transcribed — the replay client only needs the
        heartbeat thinking events.
    """
    history_event: dict[str, Any] = {
        "type": "conversation.history.set",
        "messages": history_payload.get("messages", []),
        "audio_paths": history_payload.get("audio_paths", []),
    }
    if disable_response_generation:
        history_event["disable_response_generation"] = True
    if trace_level:
        history_event["trace_level"] = trace_level
    if history_payload.get("tools") is not None:
        history_event["tools"] = history_payload.get("tools")
        history_event["tool_choice"] = "auto"
    if history_payload.get("tool_mock_examples") is not None:
        history_event["tool_mock_examples"] = history_payload.get("tool_mock_examples")
    if history_payload.get("extra_instructions"):
        history_event["extra_instructions"] = history_payload.get("extra_instructions")
    await ws.send(json.dumps(history_event, ensure_ascii=False))

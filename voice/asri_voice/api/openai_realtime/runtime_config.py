from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from openai.types.realtime import RealtimeSessionCreateRequest
from openai.types.realtime.realtime_audio_config import RealtimeAudioConfig
from openai.types.realtime.realtime_audio_config_input import RealtimeAudioConfigInput
from openai.types.realtime.realtime_audio_config_output import RealtimeAudioConfigOutput


def _apply_update(current: BaseModel, update: BaseModel) -> None:
    """Apply explicitly-set fields from *update* onto *current* in-place,
    recursing into nested BaseModel children so partial nested updates
    don't overwrite unset fields.

    Only fields present in update.model_fields_set (i.e. actually
    sent by the client) are considered.
    """
    for field_name in update.model_fields_set:
        new_val = getattr(update, field_name)
        old_val = getattr(current, field_name, None)
        if isinstance(new_val, BaseModel) and isinstance(old_val, BaseModel):
            _apply_update(old_val, new_val)
        else:
            setattr(current, field_name, new_val)


class RuntimeConfig(BaseModel):
    """
    Shared mutable configuration written by the RealtimeService on
    session.update and read by pipeline handlers (VAD, LLM, TTS) during
    processing.  Python's GIL makes simple attribute reads/writes atomic,
    so no explicit locking is needed for primitive values.

    The canonical state lives in 'session' (a full
    'RealtimeSessionCreateRequest').
    """

    model_config = ConfigDict(validate_assignment=True, arbitrary_types_allowed=True)

    server_agent_loop: bool = False
    current_session_id: str | None = None
    current_user_id: str = "anonymous_user"
    extra_instructions: str = ""
    trace_level: str = "infer"
    disable_response_generation: bool = False
    tool_mock_examples: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    session: RealtimeSessionCreateRequest = Field(
        default_factory=lambda: RealtimeSessionCreateRequest(type="realtime"),
        validate_default=True,
    )

    @field_validator("session", mode="after")
    @classmethod
    def _ensure_audio_structure(cls, v: RealtimeSessionCreateRequest) -> RealtimeSessionCreateRequest:
        """Guarantee 'audio.input' and 'audio.output' are never None."""
        if v.audio is None:
            v.audio = RealtimeAudioConfig()
        if v.audio.input is None:
            v.audio.input = RealtimeAudioConfigInput()
        if v.audio.output is None:
            v.audio.output = RealtimeAudioConfigOutput()
        return v

    @property
    def interrupt_response_enabled(self) -> bool:
        """Whether barge-in should cancel an active response.

        Reads 'turn_detection.interrupt_response' from the session config,
        handling both Pydantic models ('ServerVad') and plain dicts.
        Defaults to 'True' (OpenAI API default).
        """
        td = self.session.audio.input.turn_detection
        if td is None:
            return True
        if hasattr(td, "interrupt_response"):
            val = td.interrupt_response
        elif isinstance(td, dict):
            val = td.get("interrupt_response", True)
        else:
            return True
        return val if val is not None else True

    def apply_session_update(self, update: RealtimeSessionCreateRequest) -> None:
        """Merge non-None, explicitly-set fields from 'update' into the
        current 'session', preserving any fields not present in the update."""
        _apply_update(self.session, update)

    def reset(self) -> None:
        """Reset session to defaults, discarding all accumulated state from
        previous connections (instructions, tools, voice, turn_detection, etc.)."""
        self.session = RealtimeSessionCreateRequest(type="realtime")
        self.current_session_id = None
        self.current_user_id = "anonymous_user"
        self.extra_instructions = ""
        self.trace_level = "infer"
        self.disable_response_generation = False
        self.tool_mock_examples = {}

    def start_connection(self, session_id: str, user_id: str = "anonymous_user") -> None:
        """Record the active backend session identity for tool execution."""
        self.current_session_id = session_id
        self.current_user_id = user_id or "anonymous_user"

    def tool_context(self) -> dict:
        """Context values injected into server-side tool calls."""
        return {
            "session_id": self.current_session_id or "unknown_session",
            "user_id": self.current_user_id or "anonymous_user",
            "tools": self.session.tools,
            "extra_instructions": self.extra_instructions,
            "tool_mock_examples": self.tool_mock_examples,
        }

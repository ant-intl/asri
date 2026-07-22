"""
Bridge module: reads LLM/Tool/Prompt config from Django's multi-tenant
registries and provides Voice-compatible interfaces.

LLM, Prompt, Tools, and MCP are reused from the chatbot's active
configuration.  Only Voice-specific settings (VAD/STT/TTS/behavior)
come from VoiceAgentConfig.

Usage (from Django context, e.g. VoiceConsumer._start_pipeline):
    from voice_django.django_config_reader import DjangoConfigReader
    reader = DjangoConfigReader(tenant_id="example")
    django_cfg = await reader.read_all()
    # Apply overrides to handler_kwargs_map before build_pipeline()
"""
import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DjangoConfigReader:
    """Reads Voice-relevant config from Django's DB-backed registries.

    LLM/Prompt/Tools/MCP are read from the chatbot's active config.
    Voice-specific settings (VAD/STT/TTS/behavior) are read from
    VoiceAgentConfig.voice_settings.
    """

    def __init__(self, tenant_id: str = "example"):
        self.tenant_id = tenant_id
        self._voice_config = None  # cached VoiceAgentConfig instance

    # ------------------------------------------------------------------
    # VoiceAgentConfig
    # ------------------------------------------------------------------

    async def get_voice_agent_config(self) -> Optional[Any]:
        """Return the active VoiceAgentConfig for this tenant (or None)."""
        if self._voice_config is not None:
            return self._voice_config
        try:
            from apps.entities import VoiceAgentConfig
            self._voice_config = await VoiceAgentConfig.objects.filter(
                tenant_id=self.tenant_id, is_active=True,
            ).afirst()
            return self._voice_config
        except Exception as e:
            logger.warning("Failed to read VoiceAgentConfig: %s", e)
            return None

    # ------------------------------------------------------------------
    # LLM (reuses chatbot default)
    # ------------------------------------------------------------------

    async def get_llm_config(self) -> Optional[dict[str, Any]]:
        """Get LLM provider config from chatbot's active configuration."""
        try:
            from apps.integrations.llm.registry import LLMRegistry
            provider = await LLMRegistry.get_provider_from_config(self.tenant_id)
            if provider is None:
                return None
            return {
                "model_name": provider.model_name,
                "base_url": provider.api_base,
                "api_key": provider.api_key,
                "provider_type": provider.get_provider_type(),
            }
        except Exception as e:
            logger.warning("Failed to read LLM config from Django: %s", e)
            return None

    # ------------------------------------------------------------------
    # Tools (reuses chatbot default)
    # ------------------------------------------------------------------

    async def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get tool schemas in OpenAI function-calling format from chatbot."""
        try:
            from apps.integrations.tool.base import ToolRegistry
            schemas = ToolRegistry.list_tools_with_schemas(self.tenant_id)
            return schemas or []
        except Exception as e:
            logger.warning("Failed to read tool schemas from Django: %s", e)
            return []

    # ------------------------------------------------------------------
    # System Prompt (reuses chatbot default)
    # ------------------------------------------------------------------

    async def get_system_prompt(self) -> Optional[str]:
        """Get system prompt from chatbot's active PromptTemplate."""
        try:
            from apps.chatbot.models.prompt_template import PromptTemplate
            prompt_obj = await PromptTemplate.objects.filter(
                tenant_id=self.tenant_id, is_active=True,
            ).afirst()
            if prompt_obj is None:
                return None
            return self._extract_prompt_text(prompt_obj)
        except Exception as e:
            logger.warning("Failed to read system prompt from Django: %s", e)
            return None

    @staticmethod
    def _extract_prompt_text(prompt_obj) -> Optional[str]:
        """Extract prompt text from a PromptTemplate instance."""
        # Prefer layers (new format), fallback to system_template
        if prompt_obj.layers:
            active_layers = sorted(
                [l for l in prompt_obj.layers if l.get("is_active", True)],
                key=lambda l: l.get("order", 0),
            )
            parts = [l.get("template", "") for l in active_layers if l.get("template")]
            if parts:
                return "\n\n".join(parts)
        return prompt_obj.system_template or None

    # ------------------------------------------------------------------
    # MCP Tools (reuses chatbot default)
    # ------------------------------------------------------------------

    async def get_mcp_tools(self) -> list[dict[str, Any]]:
        """Discover MCP tool schemas from registered MCP servers."""
        try:
            from apps.integrations.mcp.mcp_server_registry import MCPServerRegistry
            tools = await MCPServerRegistry.discover_tools(self.tenant_id)
            if not tools:
                return []
            schemas = []
            for tool in tools:
                if hasattr(tool, "to_openai_schema"):
                    schemas.append(tool.to_openai_schema())
                elif hasattr(tool, "schema"):
                    schemas.append(tool.schema)
            return schemas
        except Exception as e:
            logger.warning("Failed to discover MCP tools from Django: %s", e)
            return []

    # ------------------------------------------------------------------
    # voice_settings
    # ------------------------------------------------------------------

    async def get_voice_settings(self) -> dict[str, Any]:
        """Return voice_settings dict from VoiceAgentConfig (or empty)."""
        voice_cfg = await self.get_voice_agent_config()
        if voice_cfg and voice_cfg.voice_settings:
            return voice_cfg.voice_settings
        return {}

    # ------------------------------------------------------------------
    # read_all
    # ------------------------------------------------------------------

    async def read_all(self) -> dict[str, Any]:
        """Read all config at once. Returns dict with keys:
        llm_config, tool_schemas, system_prompt, mcp_tools, voice_settings
        """
        # Ensure voice_config is loaded first (needed by get_voice_settings)
        await self.get_voice_agent_config()

        llm_config, tool_schemas, system_prompt, mcp_tools, voice_settings = (
            await asyncio.gather(
                self.get_llm_config(),
                self.get_tool_schemas(),
                self.get_system_prompt(),
                self.get_mcp_tools(),
                self.get_voice_settings(),
            )
        )
        return {
            "llm_config": llm_config,
            "tool_schemas": tool_schemas,
            "system_prompt": system_prompt,
            "mcp_tools": mcp_tools,
            "voice_settings": voice_settings,
            "tenant_id": self.tenant_id,
        }


# ======================================================================
# Apply config to handler kwargs
# ======================================================================

def apply_django_config_to_handler_kwargs(
    django_config: dict[str, Any],
    handler_kwargs_map: dict[str, Any],
    module_kwargs=None,
    vad_handler_kwargs=None,
):
    """Apply Django config to Voice handler kwargs (sync, post-read).

    Parameters
    ----------
    django_config : dict
        Output of DjangoConfigReader.read_all().
    handler_kwargs_map : dict
        Maps args_prefix → kwargs dict (already renamed).
    module_kwargs : optional
        ModuleArguments for system prompt override.
    vad_handler_kwargs : optional
        VAD handler kwargs (separate from handler_kwargs_map because VAD
        is a base handler, not registered in the handler registry).
    """
    # 1. LLM config → open_api handler kwargs
    llm_cfg = django_config.get("llm_config")
    if llm_cfg:
        open_api_kwargs = handler_kwargs_map.get("open_api", {})
        if isinstance(open_api_kwargs, dict):
            if llm_cfg.get("model_name"):
                open_api_kwargs["model_name"] = llm_cfg["model_name"]
            if llm_cfg.get("base_url"):
                open_api_kwargs["base_url"] = llm_cfg["base_url"]
            if llm_cfg.get("api_key"):
                open_api_kwargs["api_key"] = llm_cfg["api_key"]
            handler_kwargs_map["open_api"] = open_api_kwargs
            logger.info(
                "Applied Django LLM config: model=%s, base_url=%s",
                llm_cfg.get("model_name"), llm_cfg.get("base_url"),
            )

    # 2. System prompt → open_api kwargs (overriding system_prompt_file)
    system_prompt = django_config.get("system_prompt")
    if system_prompt and module_kwargs is not None:
        open_api_kwargs = handler_kwargs_map.get("open_api", {})
        if isinstance(open_api_kwargs, dict):
            open_api_kwargs["init_chat_prompt"] = system_prompt
            handler_kwargs_map["open_api"] = open_api_kwargs
            # Prevent build_pipeline from overwriting with file-based prompt
            module_kwargs.system_prompt_file = None
            logger.info(
                "Applied Django system prompt (%d chars), cleared system_prompt_file",
                len(system_prompt)
            )

    # 3. voice_settings → handler kwargs overrides
    voice_settings = django_config.get("voice_settings") or {}
    if voice_settings:
        _apply_voice_settings(
            voice_settings, handler_kwargs_map, module_kwargs, vad_handler_kwargs
        )

    # 4. Django tool schemas + MCP tools are registered directly into the
    #    Voice ``tool_registry`` after ``build_pipeline`` returns (see
    #    ``build_pipeline_from_yaml`` in main.py).  No need to inject
    #    ``django_tool_schemas`` into handler kwargs anymore — both the main
    #    LLM and Heartbeat LLM see all tools through the shared registry.


def _apply_voice_settings(
    voice_settings: dict[str, Any],
    handler_kwargs_map: dict[str, Any],
    module_kwargs=None,
    vad_handler_kwargs=None,
):
    """Map voice_settings JSON to handler kwargs.

    VAD parameters are written to ``vad_handler_kwargs`` (the dedicated VAD
    argument object) because VAD is a base handler not in the handler
    registry's ``handler_kwargs_map``.

    Expected voice_settings structure:
    {
        "vad": {"thresh": 0.5, "min_silence_ms": 500, ...},
        "stt": {"backend": "vadasr", "vadasr_url": "...", ...},
        "tts": {"backend": "omnivoice", "base_url": "...", ...},
        "enable_barge_in": true,
        "enable_heartbeat_interaction": true,
        "heartbeat": {...}
    }
    """
    # VAD parameters
    vad = voice_settings.get("vad")
    if vad and isinstance(vad, dict):
        # Write to vad_handler_kwargs (the actual VAD arg object)
        target = vad_handler_kwargs if vad_handler_kwargs is not None else handler_kwargs_map.get("vad", {})
        if hasattr(target, '__dict__'):
            # dataclass instance
            for key in ("thresh", "min_silence_ms", "min_speech_ms",
                        "speech_pad_ms", "sample_rate"):
                if key in vad:
                    setattr(target, key, vad[key])
        elif isinstance(target, dict):
            for key in ("thresh", "min_silence_ms", "min_speech_ms",
                        "speech_pad_ms", "sample_rate"):
                if key in vad:
                    target[key] = vad[key]
            if vad_handler_kwargs is not None:
                handler_kwargs_map["vad"] = target
        logger.info("Applied voice_settings.vad: %s", vad)

    # STT parameters
    stt = voice_settings.get("stt")
    if stt and isinstance(stt, dict):
        # Determine which ASR handler prefix to use based on backend
        stt_backend = stt.get("backend", "")
        asr_prefix = _stt_backend_to_prefix(stt_backend)
        if asr_prefix:
            asr_kwargs = handler_kwargs_map.get(asr_prefix, {})
            if isinstance(asr_kwargs, dict):
                for key, val in stt.items():
                    if key == "backend":
                        continue
                    # Skip keys that still carry the handler prefix
                    # (e.g. "vadasr_url" from old saved configs).
                    # After rename_args the handler expects stripped
                    # names like "url", "timeout", etc.
                    if key.startswith(asr_prefix + "_"):
                        logger.warning(
                            "Skipping old-format STT key '%s' (prefix '%s' already stripped)",
                            key, asr_prefix,
                        )
                        continue
                    asr_kwargs[key] = val
                handler_kwargs_map[asr_prefix] = asr_kwargs
                logger.info("Applied voice_settings.stt → %s", asr_prefix)
        # Update module_kwargs.stt so the main pipeline creates the correct handler
        if stt_backend and module_kwargs is not None:
            if module_kwargs.stt != stt_backend:
                logger.info(
                    "Overriding module_kwargs.stt: %s → %s (from voice_settings)",
                    module_kwargs.stt, stt_backend,
                )
                module_kwargs.stt = stt_backend

    # TTS parameters
    tts = voice_settings.get("tts")
    if tts and isinstance(tts, dict):
        tts_backend = tts.get("backend", "")
        tts_prefix = _tts_backend_to_prefix(tts_backend)
        if tts_prefix:
            tts_kwargs = handler_kwargs_map.get(tts_prefix, {})
            if isinstance(tts_kwargs, dict):
                for key, val in tts.items():
                    if key == "backend":
                        continue
                    # Skip keys that still carry the handler prefix
                    if key.startswith(tts_prefix + "_"):
                        logger.warning(
                            "Skipping old-format TTS key '%s' (prefix '%s' already stripped)",
                            key, tts_prefix,
                        )
                        continue
                    tts_kwargs[key] = val
                handler_kwargs_map[tts_prefix] = tts_kwargs
                logger.info("Applied voice_settings.tts → %s", tts_prefix)
        # Update module_kwargs.tts so the main pipeline creates the correct handler
        if tts_backend and module_kwargs is not None:
            if module_kwargs.tts != tts_backend:
                logger.info(
                    "Overriding module_kwargs.tts: %s → %s (from voice_settings)",
                    module_kwargs.tts, tts_backend,
                )
                module_kwargs.tts = tts_backend

    # Behavior toggles
    if "enable_barge_in" in voice_settings:
        if module_kwargs is not None:
            module_kwargs.enable_barge_in = voice_settings["enable_barge_in"]
            logger.info(
                "Applied enable_barge_in=%s",
                voice_settings["enable_barge_in"],
            )

    if "enable_heartbeat_interaction" in voice_settings:
        if module_kwargs is not None:
            module_kwargs.enable_heartbeat_interaction = (
                voice_settings["enable_heartbeat_interaction"]
            )
            logger.info(
                "Applied enable_heartbeat_interaction=%s",
                voice_settings["enable_heartbeat_interaction"],
            )

    # Heartbeat config
    heartbeat = voice_settings.get("heartbeat")
    if heartbeat and isinstance(heartbeat, dict):
        heartbeat_kwargs = handler_kwargs_map.get("heartbeat_interaction", {})
        if isinstance(heartbeat_kwargs, dict):
            heartbeat_kwargs.update(heartbeat)
            handler_kwargs_map["heartbeat_interaction"] = heartbeat_kwargs
            logger.info("Applied voice_settings.heartbeat")


def _stt_backend_to_prefix(backend: str) -> str:
    """Map STT backend name to handler kwargs prefix.

    Matches the args_prefix values defined in HandlerRegistry
    (voice/asri_voice/pipeline/handler_registry.py).
    """
    mapping = {
        "vadasr": "vadasr",
        "qwen3_asr": "qwen3_asr",
        "qwen3_asr_streaming": "qwen3_asr_streaming",
        "sensevoice": "sensevoice_stt",
        "openai_whisper": "openai_whisper_stt",
        "elevenlabs": "elevenlabs_stt",
        "dashscope": "dashscope_stt",
    }
    return mapping.get(backend, "")


def _tts_backend_to_prefix(backend: str) -> str:
    """Map TTS backend name to handler kwargs prefix.

    Matches the args_prefix values defined in HandlerRegistry
    (voice/asri_voice/pipeline/handler_registry.py).
    """
    mapping = {
        "omnivoice": "omnivoice_tts",
        "qwen3_tts": "qwen3_tts",
        "qwen3_local": "qwen3_local",
        "openai_tts": "openai_tts",
        "elevenlabs": "elevenlabs_tts",
        "dashscope": "dashscope_tts",
    }
    return mapping.get(backend, "")

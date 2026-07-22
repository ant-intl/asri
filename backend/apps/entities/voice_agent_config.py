"""
VoiceAgentConfig model for managing voice agent specific configurations.

Only stores Voice-specific settings (VAD, STT, TTS, barge-in, heartbeat).
LLM / Prompt / Tools / MCP are reused from the chatbot's active configuration.
"""
from django.db import models

from .fields import JsonTextField


class VoiceAgentConfig(models.Model):
    """Configuration for the Voice Agent pipeline.

    Only Voice-specific settings are stored here.  LLM provider,
    prompt template, tool selections, and MCP server selections are
    all reused from the chatbot's currently active configuration.

    Fields:
        voice_settings: JSON dict with VAD/STT/TTS/behavior config
    """

    id = models.BigAutoField(primary_key=True)
    tenant_id = models.CharField(
        max_length=64,
        default='default',
        db_index=True,
        help_text='Tenant identifier',
    )
    name = models.CharField(
        max_length=64,
        default='default',
        help_text='Configuration name (one active config per tenant)',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Whether this configuration is active',
    )

    # --- Voice-specific settings ---
    voice_settings = JsonTextField(
        default=dict,
        help_text=(
            'Voice-specific configuration JSON. Structure:\n'
            '{\n'
            '  "stt": {"backend": "vadasr", "vadasr_url": "...", "timeout": 10.0},\n'
            '  "tts": {"backend": "omnivoice", "base_url": "http://localhost:18003", "num_step": 32},\n'
            '  "vad": {"thresh": 0.5, "min_silence_ms": 500, "min_speech_ms": 200, "speech_pad_ms": 300},\n'
            '  "enable_barge_in": true,\n'
            '  "enable_heartbeat_interaction": true,\n'
            '  "heartbeat": {"mode": "streaming_asr", ...}\n'
            '}'
        ),
    )

    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chatbot_voice_agent_config'
        verbose_name = 'Voice Agent Config'
        verbose_name_plural = 'Voice Agent Configs'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'name'],
                name='uk_voice_agent_tenant_name',
            ),
        ]

    def __str__(self) -> str:
        return f"VoiceAgentConfig({self.tenant_id}/{self.name})"

    def save(self, *args, **kwargs):
        # Ensure only one active config per tenant
        if self.is_active:
            VoiceAgentConfig.objects.filter(
                tenant_id=self.tenant_id, is_active=True,
            ).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

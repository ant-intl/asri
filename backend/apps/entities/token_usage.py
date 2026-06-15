"""
TokenUsage model for persisting LLM token usage statistics.

Tracks prompt, completion, and cached tokens per LLM call
to enable cache hit rate monitoring and cost analysis.
"""
from django.db import models

from .fields import FloatCharField, JsonTextField


class TokenUsage(models.Model):
    """
    Model representing token usage for a single LLM call.

    Each record corresponds to one llm_end event in the agent trace,
    capturing the token counts and cache metrics for that call.
    """

    id = models.BigAutoField(primary_key=True)
    tenant_id = models.CharField(
        max_length=64,
        default='default',
        db_index=True,
        help_text='Tenant identifier',
    )
    session_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text='Associated chat session ID',
    )
    user_id = models.CharField(
        max_length=128,
        db_index=True,
        blank=True,
        default='',
        help_text='User identifier',
    )
    llm_provider = models.CharField(
        max_length=64,
        blank=True,
        default='',
        db_index=True,
        help_text='LLM provider name (e.g., openai, ucloud)',
    )
    model_name = models.CharField(
        max_length=128,
        blank=True,
        default='',
        help_text='LLM model name (e.g., gpt-4, qwen3-32b)',
    )
    prompt_tokens = models.IntegerField(
        default=0,
        help_text='Number of prompt tokens',
    )
    completion_tokens = models.IntegerField(
        default=0,
        help_text='Number of completion tokens',
    )
    cached_tokens = models.IntegerField(
        default=0,
        help_text='Number of cached (KV cache hit) tokens',
    )
    total_tokens = models.IntegerField(
        default=0,
        help_text='Total tokens (prompt + completion, excluding cached)',
    )
    cache_hit_rate = FloatCharField(
        help_text='Cache hit rate as a decimal (0.0 ~ 1.0)',
    )
    duration_ms = FloatCharField(
        help_text='LLM call duration in milliseconds',
    )
    chunk_count = models.IntegerField(
        default=0,
        help_text='Number of content chunks received',
    )
    ttft_ms = FloatCharField(
        help_text='Time to first token in milliseconds',
    )
    tpot_ms = FloatCharField(
        help_text='Average time per output token in milliseconds',
    )
    finish_reason = models.CharField(
        max_length=32,
        blank=True,
        default='',
        help_text='Reason for completion (stop, length, etc.)',
    )
    metadata = JsonTextField(
        default=dict,
        help_text='Additional metadata for this LLM call',
    )
    gmt_create = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        help_text='Record creation time',
    )
    gmt_modified = models.DateTimeField(
        auto_now=True,
        help_text='Record modification time',
    )

    class Meta:
        db_table = 'chatbot_token_usage'
        ordering = ['-gmt_create']
        verbose_name = 'Token Usage Record'
        verbose_name_plural = 'Token Usage Records'
        indexes = [
            models.Index(fields=['tenant_id', 'gmt_create']),
            models.Index(fields=['session_id', 'gmt_create']),
            models.Index(fields=['model_name', 'gmt_create']),
        ]

    def __str__(self) -> str:
        return (
            f"[{self.model_name or '?'}] "
            f"prompt={self.prompt_tokens} "
            f"cached={self.cached_tokens} "
            f"hit_rate={self.cache_hit_rate:.1%}"
        )

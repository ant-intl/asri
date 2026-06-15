"""
SessionContext model for storing complete LLM conversation context.

Stores the full messages array (excluding system prompt) used by the LLM,
including tool_calls, tool results, and intermediate reasoning steps.
This enables subsequent requests in the same session to use complete
context data following the Interleaved Thinking pattern.
"""
from django.db import models

from .fields import JsonTextField


class SessionContext(models.Model):
    """
    Stores the complete LLM conversation context for a session.

    The ``messages`` field holds the full message list sent to the LLM
    (excluding the system prompt which is regenerated per request).
    Supports two formats depending on the prompt mode:

    Native function_calling::

        [
          {"role": "user", "content": "..."},
          {"role": "assistant", "content": null, "tool_calls": [...]},
          {"role": "tool", "tool_call_id": "...", "content": "..."},
          {"role": "assistant", "content": "final answer"},
        ]

    Text-based (interleaved thinking)::

        [
          {"role": "user", "content": "..."},
          {"role": "assistant", "content": "<think>...</think><answer>...</answer>"},
        ]
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
        unique=True,
        help_text='Associated chat session ID',
    )
    messages = JsonTextField(
        default=list,
        help_text='Complete LLM context messages (excluding system prompt)',
    )
    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chatbot_session_context'
        verbose_name = 'Session Context'
        verbose_name_plural = 'Session Contexts'

    def __str__(self) -> str:
        msg_count = len(self.messages) if self.messages else 0
        return f"Context for {self.session_id} ({msg_count} messages)"

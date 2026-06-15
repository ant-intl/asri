"""
ChatMessage model for storing conversation messages.
"""
import uuid
from django.db import models

from .fields import JsonTextField


class ChatMessage(models.Model):
    """
    Model representing a single message in a chat session.
    
    Supports different roles (user, assistant, system, tool) and message types
    (text, thought, action, observation) for ReAct agent workflow.
    """
    
    class Role(models.TextChoices):
        USER = 'user', 'User'
        ASSISTANT = 'assistant', 'Assistant'
        SYSTEM = 'system', 'System'
        TOOL = 'tool', 'Tool'
    
    class MessageType(models.TextChoices):
        TEXT = 'text', 'Text'
        THOUGHT = 'thought', 'Thought'
        ACTION = 'action', 'Action'
        OBSERVATION = 'observation', 'Observation'
    
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.CharField(
        max_length=64,
        default='default',
        db_index=True,
        help_text='Tenant identifier',
    )
    message_id = models.CharField(
        max_length=64, 
        unique=True, 
        default=uuid.uuid4,
        help_text='Unique message identifier'
    )
    session_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text='Associated chat session ID'
    )
    role = models.CharField(
        max_length=16, 
        choices=Role.choices,
        help_text='Message sender role'
    )
    content = models.TextField(
        help_text='Message content'
    )
    message_type = models.CharField(
        max_length=16, 
        choices=MessageType.choices, 
        default=MessageType.TEXT,
        help_text='Type of message'
    )
    parent_message_id = models.CharField(
        max_length=64, 
        null=True, 
        blank=True,
        db_index=True,
        help_text='Parent message ID for multi-answer scenarios'
    )
    group_id = models.CharField(
        max_length=64, 
        null=True, 
        blank=True,
        db_index=True,
        help_text='Group ID for multi-question scenarios'
    )
    token_count = models.IntegerField(
        default=0,
        help_text='Token count for this message'
    )
    metadata = JsonTextField(
        default=dict,
        help_text='Additional message metadata'
    )
    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'chatbot_message'
        ordering = ['gmt_create']
        verbose_name = 'Chat Message'
        verbose_name_plural = 'Chat Messages'
        indexes = [
            models.Index(fields=['session_id', 'gmt_create']),
        ]
    
    def __str__(self) -> str:
        content_preview = self.content[:50] + '...' if len(self.content) > 50 else self.content
        return f"[{self.role}] {content_preview}"
    
    def save(self, *args, **kwargs):
        if not self.message_id:
            self.message_id = str(uuid.uuid4())
        super().save(*args, **kwargs)

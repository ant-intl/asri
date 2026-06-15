"""
ChatSession model for managing conversation sessions.
"""
import uuid
from django.db import models

from .fields import JsonTextField


class ChatSession(models.Model):
    """
    Model representing a chat session.
    
    A session contains multiple messages and tracks the conversation state.
    """
    
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Active'
        ARCHIVED = 'archived', 'Archived'
        DELETED = 'deleted', 'Deleted'
    
    class AgentType(models.TextChoices):
        REACT = 'react', 'ChatAgent'
        SIMPLE = 'simple', 'Simple Agent'
    
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
        default=uuid.uuid4,
        help_text='Unique session identifier'
    )
    user_id = models.CharField(
        max_length=128, 
        db_index=True,
        help_text='User identifier'
    )
    title = models.CharField(
        max_length=256, 
        blank=True, 
        default='',
        help_text='Session title'
    )
    status = models.CharField(
        max_length=16, 
        choices=Status.choices, 
        default=Status.ACTIVE,
        db_index=True,
        help_text='Session status'
    )
    llm_provider_id = models.BigIntegerField(
        null=True,
        blank=True,
        db_index=True,
        help_text='LLM provider configuration ID'
    )
    agent_type = models.CharField(
        max_length=32, 
        choices=AgentType.choices, 
        default=AgentType.REACT,
        help_text='Agent type for this session'
    )
    external_source = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        help_text='External system identifier (e.g., crm, customer-service)',
    )
    external_session_id = models.CharField(
        max_length=128,
        null=True,
        blank=True,
        db_index=True,
        help_text='External system session ID for third-party integration',
    )
    metadata = JsonTextField(
        default=dict,
        help_text='Additional session metadata'
    )
    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'chatbot_session'
        ordering = ['-gmt_create']
        verbose_name = 'Chat Session'
        verbose_name_plural = 'Chat Sessions'
    
    def __str__(self) -> str:
        return f"{self.session_id} - {self.title or 'Untitled'}"
    
    def save(self, *args, **kwargs):
        if not self.session_id:
            self.session_id = str(uuid.uuid4())
        super().save(*args, **kwargs)

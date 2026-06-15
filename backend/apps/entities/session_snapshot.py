"""
Session Snapshot model.

Captures the complete agent configuration (LLM provider, prompt template,
skills, tools, RAG) at a point in time so that sessions can be recreated
with identical configuration or compared side-by-side in the Playground.
"""
import uuid

from django.db import models

from .fields import JsonTextField


class SessionSnapshot(models.Model):
    """Session Snapshot Model

    Packages the complete configuration required for a session into a snapshot, supporting:
    - Creating a new session from a snapshot (using frozen configuration)
    - Selecting different snapshots for comparison in the Playground

    snapshot_data stores the following content (without API Keys, only reference IDs):
    - agent_type: agent type
    - llm_provider_ref: LLM Provider reference (provider_config_id)
    - prompt: frozen PromptTemplate content
    - skills: list of active Skills
    - tools: list of active Tools
    - rag_providers: list of active RAG Providers
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    tenant_id = models.CharField(
        max_length=64,
        default='example',
        help_text='租户标识',
    )

    name = models.CharField(
        max_length=128,
        help_text='快照名称',
    )

    description = models.TextField(
        blank=True,
        default='',
        help_text='快照描述',
    )

    source_session_id = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        help_text='来源会话 ID，null 表示手动创建',
    )

    # Snapshot data (complete configuration)
    snapshot_data = JsonTextField(
        default=dict,
        help_text="复合配置快照，JSON 格式",
    )

    tags = JsonTextField(
        default=list,
        help_text='标签，用于分类/筛选',
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text='是否可用',
    )

    created_by = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text='创建者标识',
    )

    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chatbot_session_snapshot'
        ordering = ['-gmt_create']
        indexes = [
            models.Index(
                fields=['tenant_id', 'gmt_create'],
                name='idx_ss_tenant_created',
            ),
            models.Index(
                fields=['tenant_id', 'is_active'],
                name='idx_ss_tenant_active',
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant_id})"

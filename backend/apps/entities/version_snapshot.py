"""
Version Snapshot model for tracking prompt template and skill history.
"""
import uuid

from django.db import models

from .fields import JsonTextField


class VersionSnapshot(models.Model):
    """Version snapshot model.

    Unified management of version history for PromptTemplate and Skill.
    Logically associated with the parent entity via entity_type + entity_id, without foreign keys.

    Each version stores a complete snapshot (snapshot_data); switching versions writes directly back to the parent entity.
    """

    # Entity type enum
    class EntityType(models.TextChoices):
        PROMPT_TEMPLATE = 'prompt_template', 'Prompt Template'
        SKILL = 'skill', 'Skill'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    tenant_id = models.CharField(
        max_length=64,
        default='example',
        help_text='Tenant identifier',
    )

    # Associated parent entity (logical association, no foreign key)
    entity_type = models.CharField(
        max_length=32,
        choices=EntityType.choices,
        db_index=True,
        help_text="Entity type: prompt_template or skill",
    )
    entity_id = models.CharField(
        max_length=64,
        db_index=True,
        help_text="ID of the associated entity (PromptTemplate.id or Skill.skill_id)",
    )

    # Version info
    version_number = models.PositiveIntegerField(
        help_text="Version number, auto-incremented within the same entity",
    )
    label = models.CharField(
        max_length=128,
        blank=True,
        default='',
        help_text="User-defined version label, e.g. 'v1.0-prod'",
    )
    description = models.TextField(
        blank=True,
        default='',
        help_text="Version change description",
    )

    # Snapshot data (complete content)
    snapshot_data = JsonTextField(
        default=dict,
        help_text="Complete entity snapshot in JSON format",
    )

    # Status
    is_active = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this is the currently active version",
    )

    # Creator (reserved for multi-user scenarios)
    created_by = models.CharField(
        max_length=64,
        blank=True,
        default='',
        help_text="Creator identifier",
    )

    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chatbot_version_snapshot'
        ordering = ['-version_number']
        indexes = [
            models.Index(
                fields=['tenant_id', 'entity_type', 'entity_id', 'version_number'],
                name='idx_v_tenant_entity_number',
            ),
            models.Index(
                fields=['tenant_id', 'entity_type', 'entity_id', 'is_active'],
                name='idx_v_tenant_entity_active',
            ),
        ]

    def __str__(self) -> str:
        return f"{self.entity_type}/{self.entity_id} v{self.version_number}"

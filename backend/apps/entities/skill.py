"""
Skill model for managing conversation skills.
"""
import re
import uuid
from django.db import models
from django.core.validators import RegexValidator

from .fields import JsonTextField

# Skill name validator: only English letters, numbers, underscores, and hyphens
SKILL_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

def validate_skill_name(value: str) -> None:
    """Validate that skill name contains only English letters, numbers, underscores, and hyphens."""
    if not SKILL_NAME_PATTERN.match(value):
        raise ValueError(
            "Skill name must contain only English letters, numbers, underscores (_), "
            "and hyphens (-). Example: 'refund_process' or 'account-management'"
        )


class Skill(models.Model):
    """
    Model representing a conversation skill.

    Skills are used to provide domain-specific knowledge and instructions
    to the AI agent during conversations.
    """

    id = models.BigAutoField(primary_key=True)
    tenant_id = models.CharField(
        max_length=64,
        default='default',
        db_index=True,
        help_text='Tenant identifier',
    )
    skill_id = models.CharField(
        max_length=64,
        unique=True,
        default=uuid.uuid4,
        help_text='Unique skill identifier'
    )
    name = models.CharField(
        max_length=255,
        validators=[validate_skill_name],
        help_text='Skill name (English letters, numbers, underscores, hyphens only)'
    )
    description = models.TextField(
        blank=True,
        default='',
        help_text='Skill description'
    )
    content = models.TextField(
        help_text='SKILL.md format content'
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text='Whether the skill is active'
    )
    metadata = JsonTextField(
        default=dict,
        blank=True,
        help_text='Additional skill metadata'
    )
    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chatbot_skill'
        ordering = ['-gmt_create']
        verbose_name = 'Skill'
        verbose_name_plural = 'Skills'
        unique_together = [['tenant_id', 'name']]

    def __str__(self) -> str:
        return f"{self.name} ({self.tenant_id})"

    def save(self, *args, **kwargs):
        if not self.skill_id:
            self.skill_id = str(uuid.uuid4())
        super().save(*args, **kwargs)

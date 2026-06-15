"""
ToolConfig model for managing tool configurations.
"""
from django.db import models

from .fields import JsonTextField


class ToolConfig(models.Model):
    """
    Model for storing tool and skill configurations.
    """
    
    class ToolType(models.TextChoices):
        TOOL = 'tool', 'Tool'
        SKILL = 'skill', 'Skill'
    
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.CharField(
        max_length=64,
        default='default',
        db_index=True,
        help_text='Tenant identifier',
    )
    name = models.CharField(
        max_length=64,
        help_text='Tool/Skill name'
    )
    tool_type = models.CharField(
        max_length=32, 
        choices=ToolType.choices,
        default=ToolType.TOOL,
        help_text='Tool or Skill'
    )
    description = models.TextField(
        blank=True, 
        default='',
        help_text='Tool description for LLM'
    )
    parameters_schema = JsonTextField(
        default=dict,
        help_text='JSON Schema for tool parameters'
    )
    config_json = JsonTextField(
        default=dict,
        help_text='Additional configuration'
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Whether this tool is active'
    )
    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'chatbot_tool_config'
        verbose_name = 'Tool Config'
        verbose_name_plural = 'Tool Configs'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'name'],
                name='uk_tool_tenant_name',
            ),
        ]
    
    def __str__(self) -> str:
        return f"{self.name} ({self.tool_type})"

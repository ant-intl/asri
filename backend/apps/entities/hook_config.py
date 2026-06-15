"""
HookConfig model for managing hook configurations.

Aligns with Claude Code's settings.json hooks configuration pattern.
Each tenant can define multiple hook instances with custom parameters.
"""
from django.db import models

from .fields import JsonTextField


class HookConfig(models.Model):
    """Hook configuration model.

    Stores hook instance definitions in the database with tenant isolation.
    Each hook instance has a unique ``(tenant_id, hook_name)`` pair and
    can be enabled/disabled via ``is_active``.

    The ``config_json`` field holds hook-specific parameters such as
    tool lists, timeouts, and custom thresholds.
    """

    id = models.BigAutoField(primary_key=True)
    tenant_id = models.CharField(
        max_length=64,
        db_index=True,
        default='default',
        help_text='租户 ID',
    )
    hook_type = models.CharField(
        max_length=64,
        help_text='Hook 类型标识，如 tool_confirmation',
    )
    hook_name = models.CharField(
        max_length=128,
        help_text='Hook 实例名称，同一 tenant 下唯一',
    )
    description = models.TextField(
        default='',
        blank=True,
        help_text='Hook 描述',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='是否启用',
    )
    config_json = JsonTextField(
        default=dict,
        help_text='Hook 自定义参数，如 {"timeout": 30, "tools": ["send_email"]}',
    )
    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chatbot_hook_config'
        ordering = ['-gmt_create']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'hook_name'],
                name='uk_hook_tenant_name',
            ),
        ]

    def __str__(self) -> str:
        return f"{self.hook_name} ({self.hook_type})"

    def save(self, *args, **kwargs):
        """Save and invalidate HookRegistry cache for this tenant."""
        super().save(*args, **kwargs)
        from ..agent.hooks.registry import HookRegistry
        HookRegistry.invalidate_cache(self.tenant_id)

"""
Tenant model for managing tenant configurations and authentication tokens.
"""
import hashlib

from django.db import models

from .fields import JsonTextField


class Tenant(models.Model):
    """
    Stores tenant configuration and authentication token.

    The ``token_hash`` field holds SHA-256(raw_token) so that the
    original token is never persisted in the database.  At runtime
    the full tenant table is cached in :class:`~apps.tenant.registry.TenantRegistry`
    and refreshed every 60 seconds.
    """

    id = models.BigAutoField(primary_key=True)
    tenant_id = models.CharField(
        max_length=64,
        unique=True,
        help_text='Unique tenant identifier',
    )
    name = models.CharField(
        max_length=128,
        help_text='Human-readable tenant name',
    )
    token_hash = models.CharField(
        max_length=128,
        unique=True,
        help_text='SHA-256 hash of the authentication token',
    )
    config_json = JsonTextField(
        default=dict,
        help_text='Tenant-specific configuration (overrides settings.CHATBOT)',
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Whether this tenant is active',
    )
    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chatbot_tenant'
        verbose_name = 'Tenant'
        verbose_name_plural = 'Tenants'

    def __str__(self) -> str:
        return f"{self.tenant_id} ({self.name})"

    @staticmethod
    def hash_token(raw_token: str) -> str:
        """Return the SHA-256 hex digest of *raw_token*."""
        return hashlib.sha256(raw_token.encode()).hexdigest()

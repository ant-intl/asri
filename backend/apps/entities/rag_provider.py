"""
RAGProviderConfig model for managing RAG provider configurations.
"""
from django.db import models

from .fields import JsonTextField


class RAGProviderConfig(models.Model):
    """
    Model for storing RAG (Retrieval-Augmented Generation) provider configurations.
    """
    
    class ProviderType(models.TextChoices):
        HTTP = 'http', 'HTTP Service'
        CUSTOM = 'custom', 'Custom'
    
    id = models.BigAutoField(primary_key=True)
    tenant_id = models.CharField(
        max_length=64,
        default='default',
        db_index=True,
        help_text='Tenant identifier',
    )
    name = models.CharField(
        max_length=64,
        help_text='Configuration name'
    )
    provider_type = models.CharField(
        max_length=32, 
        choices=ProviderType.choices,
        default=ProviderType.HTTP,
        help_text='RAG provider type'
    )
    api_base = models.CharField(
        max_length=512, 
        blank=True, 
        default='',
        help_text='API base URL'
    )
    api_key_encrypted = models.CharField(
        max_length=512, 
        blank=True, 
        default='',
        help_text='Encrypted API key'
    )
    config_json = JsonTextField(
        default=dict,
        help_text='Additional configuration'
    )
    is_default = models.BooleanField(
        default=False,
        help_text='Whether this is the default provider'
    )
    is_active = models.BooleanField(
        default=True,
        help_text='Whether this provider is active'
    )
    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'chatbot_rag_provider'
        verbose_name = 'RAG Provider Config'
        verbose_name_plural = 'RAG Provider Configs'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'name'],
                name='uk_rag_tenant_name',
            ),
        ]
    
    def __str__(self) -> str:
        return f"{self.name} ({self.provider_type})"
    
    def save(self, *args, **kwargs):
        if self.is_default:
            RAGProviderConfig.objects.filter(
                tenant_id=self.tenant_id, is_default=True,
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

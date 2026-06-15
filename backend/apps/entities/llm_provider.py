"""
LLMProviderConfig model for managing LLM provider configurations.
"""
from django.db import models

from .fields import JsonTextField


class LLMProviderConfig(models.Model):
    """
    Model for storing LLM provider configurations.
    
    Supports multiple provider types: OpenAI, Ollama, AsriGateway.
    provider_type is a free-form string validated at the Registry layer,
    not at the database level — this avoids migrations when adding types.
    """
    
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
        help_text='LLM provider type (validated by Registry at runtime)'
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
    model_name = models.CharField(
        max_length=128,
        help_text='Model name to use'
    )
    config_json = JsonTextField(
        default=dict,
        help_text='Additional configuration (temperature, max_tokens, etc.)'
    )
    purpose = models.CharField(
        max_length=32,
        choices=[('chatbot', 'Chatbot'), ('copilot', 'Copilot')],
        default='chatbot',
        help_text='Model purpose (chatbot or copilot)'
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
        db_table = 'chatbot_llm_provider'
        verbose_name = 'LLM Provider Config'
        verbose_name_plural = 'LLM Provider Configs'
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'name'],
                name='uk_llm_tenant_name',
            ),
        ]
    
    def __str__(self) -> str:
        return f"{self.name} ({self.provider_type})"
    
    def save(self, *args, **kwargs):
        # Ensure only one default provider per tenant
        if self.is_default:
            LLMProviderConfig.objects.filter(
                tenant_id=self.tenant_id, is_default=True,
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

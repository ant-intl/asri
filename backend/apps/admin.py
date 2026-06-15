"""
Chatbot admin configuration.
"""
from django.contrib import admin

from .entities import (
    ChatSession, ChatMessage, LLMProviderConfig, RAGProviderConfig,
    ToolConfig, McpServerConfig, McpToolMockConfig, HookConfig,
    TokenUsage,
)

@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    """Admin configuration for ChatSession model."""

    list_display = ['session_id', 'user_id', 'title', 'status', 'agent_type', 'gmt_create']
    list_filter = ['status', 'agent_type', 'gmt_create']
    search_fields = ['session_id', 'user_id', 'title']
    readonly_fields = ['session_id', 'gmt_create', 'gmt_modified']


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    """Admin configuration for ChatMessage model."""

    list_display = ['message_id', 'session_id', 'role', 'message_type', 'token_count', 'gmt_create']
    list_filter = ['role', 'message_type', 'gmt_create']
    search_fields = ['message_id', 'content']
    readonly_fields = ['message_id', 'gmt_create']


@admin.register(LLMProviderConfig)
class LLMProviderConfigAdmin(admin.ModelAdmin):
    """Admin configuration for LLMProviderConfig model."""

    list_display = ['name', 'provider_type', 'model_name', 'is_default', 'is_active', 'gmt_create']
    list_filter = ['provider_type', 'is_default', 'is_active']
    search_fields = ['name', 'model_name']


@admin.register(RAGProviderConfig)
class RAGProviderConfigAdmin(admin.ModelAdmin):
    """Admin configuration for RAGProviderConfig model."""

    list_display = ['name', 'provider_type', 'is_default', 'is_active', 'gmt_create']
    list_filter = ['provider_type', 'is_default', 'is_active']
    search_fields = ['name']


@admin.register(ToolConfig)
class ToolConfigAdmin(admin.ModelAdmin):
    """Admin configuration for ToolConfig model."""

    list_display = ['name', 'tool_type', 'is_active', 'gmt_create']


@admin.register(McpServerConfig)
class McpServerConfigAdmin(admin.ModelAdmin):
    """Admin configuration for McpServerConfig model."""

    list_display = ['name', 'server_id', 'command', 'is_active', 'tenant_id', 'gmt_create']
    list_filter = ['is_active', 'gmt_create']
    search_fields = ['name', 'server_id', 'command']
    readonly_fields = ['gmt_create', 'gmt_modified']


@admin.register(McpToolMockConfig)
class McpToolMockConfigAdmin(admin.ModelAdmin):
    """Admin configuration for McpToolMockConfig model."""

    list_display = ['server_id', 'tool_name', 'enabled', 'mode', 'gmt_create']
    list_filter = ['enabled', 'mode', 'gmt_create']
    search_fields = ['server_id', 'tool_name']
    readonly_fields = ['gmt_create', 'gmt_modified']


@admin.register(HookConfig)
class HookConfigAdmin(admin.ModelAdmin):
    """Admin configuration for HookConfig model."""

    list_display = ['hook_name', 'hook_type', 'tenant_id', 'is_active', 'gmt_create']
    list_filter = ['hook_type', 'is_active', 'tenant_id', 'gmt_create']
    search_fields = ['hook_name', 'description']
    readonly_fields = ['gmt_create', 'gmt_modified']


@admin.register(TokenUsage)
class TokenUsageAdmin(admin.ModelAdmin):
    """Admin configuration for TokenUsage model."""

    list_display = [
        'model_name', 'llm_provider', 'prompt_tokens', 'cached_tokens',
        'cache_hit_rate', 'duration_ms', 'session_id', 'gmt_create',
    ]
    list_filter = ['llm_provider', 'model_name', 'gmt_create']
    search_fields = ['session_id', 'user_id', 'model_name']
    readonly_fields = ['gmt_create']

"""
Chatbot API URL configuration.
"""
from django.urls import path

from .http import (
    admin_config_sync,
    cache_stats,
    chat,
    hook_config,
    llm_config,
    mcp_config,
    message,
    poll_chat,
    session,
    skill,
    snapshot,
    tenant_config,
    tool_config,
    trace,
    version as version_api,
)
from .prompt_template import (
    PromptTemplateListView,
    PromptTemplateDetailView,
    PromptTemplateEnableView,
    PromptTemplateDisableView,
)

app_name = 'chatbot_api'

urlpatterns = [
    # Prompt Template endpoints (admin)
    path('admin/prompt-templates/', PromptTemplateListView.as_view(), name='admin_prompt_template_list'),
    path('admin/prompt-templates/<str:pk>/', PromptTemplateDetailView.as_view(), name='admin_prompt_template_detail'),
    path('admin/prompt-templates/<str:pk>/enable/', PromptTemplateEnableView.as_view(), name='admin_prompt_template_enable'),
    path('admin/prompt-templates/<str:pk>/disable/', PromptTemplateDisableView.as_view(), name='admin_prompt_template_disable'),

    # Admin Skill endpoints (fixed 'example' tenant)
    path('admin/skills/', skill.SkillListView.as_view(), name='admin_skill_list'),
    path('admin/skills/upload/', skill.SkillUploadView.as_view(), name='admin_skill_upload'),
    path('admin/skills/<str:skill_id>/', skill.SkillDetailView.as_view(), name='admin_skill_detail'),
    path('admin/skills/<str:skill_id>/refresh/', skill.SkillRefreshView.as_view(), name='admin_skill_refresh'),

    # Admin Skill enable/disable endpoints (fixed 'example' tenant)

    path('admin/tools/', tool_config.ToolListView.as_view(), name='admin_tool_list'),
    path('admin/skills/<str:skill_id>/enable/', skill.SkillEnableView.as_view(), name='admin_skill_enable'),
    path('admin/skills/<str:skill_id>/disable/', skill.SkillDisableView.as_view(), name='admin_skill_disable'),

    # Admin Tool endpoints (no token required, use 'example' tenant)
    path('admin/tools/<int:pk>/', tool_config.ToolDetailView.as_view(), name='admin_tool_detail'),
    path('admin/tools/<int:pk>/enable/', admin_config_sync.ToolEnableView.as_view(), name='admin_tool_enable'),
    path('admin/tools/<int:pk>/disable/', admin_config_sync.ToolDisableView.as_view(), name='admin_tool_disable'),

    # Built-in Tool toggle endpoint
    path('admin/builtin-tools/<str:tool_name>/toggle/', tool_config.BuiltInToolToggleView.as_view(), name='admin_builtin_tool_toggle'),

    path('admin/llm-providers/', llm_config.LLMProviderListView.as_view(), name='admin_llm_provider_list'),
    path('admin/llm-providers/<int:pk>/', llm_config.LLMProviderDetailView.as_view(), name='admin_llm_provider_detail'),
    path('admin/llm-providers/<int:pk>/enable/', admin_config_sync.ModelEnableView.as_view(), name='admin_model_enable'),
    path('admin/llm-providers/<int:pk>/disable/', admin_config_sync.ModelDisableView.as_view(), name='admin_model_disable'),

    # Admin Chat endpoints (frontend uses these, external apps use the non-admin versions)
    path('admin/chat/', chat.ChatView.as_view(), name='admin_chat'),
    path('admin/chat/interrupt/', chat.ChatInterruptView.as_view(), name='admin_chat_interrupt'),
    path('admin/chat/batch/', chat.BatchChatView.as_view(), name='admin_chat_batch'),
    path('admin/chat/confirm/', chat.ToolConfirmView.as_view(), name='admin_chat_confirm'),

    # Admin Poll Chat endpoints
    path('admin/poll/chat/init/', poll_chat.PollChatInitView.as_view(), name='admin_poll_chat_init'),
    path('admin/poll/chat/chunks/', poll_chat.PollChatChunksView.as_view(), name='admin_poll_chat_chunks'),
    path('admin/poll/chat/cancel/<str:user_message_id>/', poll_chat.PollChatCancelView.as_view(), name='admin_poll_chat_cancel'),

    # Admin Session endpoints
    path('admin/sessions/', session.SessionListView.as_view(), name='admin_session_list'),
    path('admin/sessions/<str:session_id>/', session.SessionDetailView.as_view(), name='admin_session_detail'),
    path('admin/sessions/<str:session_id>/messages/', message.MessageListView.as_view(), name='admin_message_list'),

    # Admin Message endpoints
    path('admin/messages/<str:message_id>/', message.MessageDetailView.as_view(), name='admin_message_detail'),

    # Admin Tenant endpoints
    path('admin/tenants/', tenant_config.TenantListView.as_view(), name='admin_tenant_list'),

    # Version Snapshot endpoints (admin)
    path('admin/versions/diff/', version_api.VersionDiffView.as_view(), name='admin_version_diff'),
    path('admin/versions/', version_api.VersionListView.as_view(), name='admin_version_list'),
    path('admin/versions/<str:version_id>/', version_api.VersionDetailView.as_view(), name='admin_version_detail'),
    path('admin/versions/<str:version_id>/activate/', version_api.VersionActivateView.as_view(), name='admin_version_activate'),

    # Hook configuration endpoints (admin)
    path('admin/hooks/', hook_config.HookListView.as_view(), name='admin_hook_list'),
    path('admin/hooks/<int:pk>/', hook_config.HookDetailView.as_view(), name='admin_hook_detail'),
    path('admin/hooks/<int:pk>/toggle/', hook_config.HookToggleView.as_view(), name='admin_hook_toggle'),

    # MCP Server configuration endpoints
    path('admin/mcp-servers/', mcp_config.mcp_servers, name='admin_mcp_servers'),

    # Session trace observation endpoint (admin)
    path('admin/sessions/<str:session_id>/trace/', trace.SessionTraceView.as_view(), name='admin_session_trace'),
    path('admin/mcp-servers/<str:server_id>/', mcp_config.mcp_server_detail, name='admin_mcp_server_detail'),
    path('admin/mcp-servers/<str:server_id>/toggle/', mcp_config.mcp_server_toggle, name='admin_mcp_server_toggle'),
    path('admin/mcp-servers/<str:server_id>/refresh-tools/', mcp_config.mcp_server_refresh_tools, name='admin_mcp_server_refresh_tools'),
    path('admin/mcp-servers/<str:server_id>/tools/<str:tool_name>/execute/', mcp_config.mcp_tool_execute, name='admin_mcp_tool_execute'),
    path('admin/mcp-servers/<str:server_id>/tools/<str:tool_name>/mock/', mcp_config.mcp_tool_mock, name='admin_mcp_tool_mock'),
    path('admin/mcp-servers/<str:server_id>/tools/<str:tool_name>/mock/toggle/', mcp_config.mcp_tool_mock_toggle, name='admin_mcp_tool_mock_toggle'),

    # Cache monitoring endpoints (admin)
    path('admin/cache-stats/overview/', cache_stats.CacheStatsOverviewView.as_view(), name='admin_cache_stats_overview'),
    path('admin/cache-stats/recent/', cache_stats.CacheStatsRecentView.as_view(), name='admin_cache_stats_recent'),

    # Session Snapshot endpoints (admin)
    path('admin/snapshots/', snapshot.SnapshotListView.as_view(), name='admin_snapshot_list'),
    path('admin/snapshots/<str:snapshot_id>/', snapshot.SnapshotDetailView.as_view(), name='admin_snapshot_detail'),
    path('admin/snapshots/<str:snapshot_id>/config/', snapshot.SnapshotConfigPreviewView.as_view(), name='admin_snapshot_config'),
]

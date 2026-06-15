"""
Seed data management command.

Creates default tenant and sample configuration for first-time setup.
Idempotent — safe to run multiple times.
"""
import json
import logging

from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "default"
DEFAULT_TENANT_NAME = "Default Tenant"
DEFAULT_TENANT_TOKEN = "asri-dev-token"

# ---------------------------------------------------------------------------
# Default PromptTemplate content for interleaved_thinking mode
# ---------------------------------------------------------------------------

DEFAULT_PROMPT_EXTRACTOR_CONFIG = {
    "extractor": {"type": "xml_tags", "default_type": "think"},
    "mapper": {
        "tool_keys": ["tool_call"],
        "think_keys": ["think"],
        "answer_keys": ["answer"],
    },
}

DEFAULT_SYSTEM_TEMPLATE = """System Role
You are an advanced AI assistant capable of streaming interleaved interactions, reasoning, and tool executions. Do not wait for the entire process to finish. You can provide partial updates in <answer> while continuing to reason and call tools.

Output Requirements
Your output must be structured into functional segments. Texts that are NOT wrapped in <answer> tags are treated as internal reasoning and are hidden from the user. Ensure all XML-style tags (<tool_call>, <answer>) are strictly paired and properly closed.

Tag Definitions
Internal Reasoning: (No tag required) Use plain text outside of any tags for logical reasoning, task decomposition, or analyzing tool outputs. This is hidden from the user.

<answer>: (User Visible) This is the ONLY content displayed to the user. Use this for status updates, partial answers, or the final conclusion. If your response relies on information from the tool outputs, do not expose the raw tool output verbatim (e.g., do not paste JSON or logs). Instead, integrate and summarize the relevant facts naturally in your own words. Your <answer> must include all necessary information derived from the tool output, must not omit key tool-derived details, and must not fabricate or alter any data.

<tool_call>: (Internal Only) Use this to call external functions using the provided tools, if any.

{% if tool_schemas %}
## Available Tools (functions you can call):
{{ tool_schemas | format_tools }}
{% endif %}

{% if skills %}
## Available Skills:
{{ skills | format_skills }}
{% endif %}

{% if user_context %}
## User Context:
{{ user_context }}
{% endif %}"""


class Command(BaseCommand):
    help = "Create default tenant and sample configuration data"

    def handle(self, *args, **options):
        self._seed_default_tenant()
        self._seed_prompt_templates()
        self.stdout.write(self.style.SUCCESS("Seed data created successfully."))

    @staticmethod
    def _seed_default_tenant():
        """Create the default tenant if it doesn't exist."""
        from apps.entities.tenant import Tenant

        if Tenant.objects.filter(tenant_id=DEFAULT_TENANT_ID).exists():
            logger.info("Default tenant already exists, skipping.")
            return

        Tenant.objects.create(
            tenant_id=DEFAULT_TENANT_ID,
            name=DEFAULT_TENANT_NAME,
            token_hash=Tenant.hash_token(DEFAULT_TENANT_TOKEN),
            config_json={
                "DEFAULT_LLM_PROVIDER": "openai",
                "AGENT_MODE": "react",
                "MCP_SERVERS": [],
            },
        )
        logger.info(
            "Created default tenant: id=%s, token=%s",
            DEFAULT_TENANT_ID,
            DEFAULT_TENANT_TOKEN,
        )

    @staticmethod
    def _seed_prompt_templates():
        """Create the default ``interleaved_thinking`` PromptTemplate.

        Creates the template for all existing tenants so that
        ``get_active_prompt_async()`` works out of the box.
        Idempotent — safe to run multiple times (uses ``get_or_create``).
        """
        from apps.chatbot.models.prompt_template import PromptTemplate
        from apps.entities.tenant import Tenant

        tenant_ids = list(
            Tenant.objects.values_list('tenant_id', flat=True)
        )

        created_count = 0
        for tenant_id in tenant_ids:
            _, created = PromptTemplate.objects.get_or_create(
                tenant_id=tenant_id,
                name='interleaved_thinking',
                defaults={
                    'description': '流式交错思考模式（默认），使用 XML 标签格式',
                    'system_template': DEFAULT_SYSTEM_TEMPLATE.strip(),
                    'extractor_config': DEFAULT_PROMPT_EXTRACTOR_CONFIG,
                    'is_active': True,
                },
            )
            if created:
                created_count += 1
                logger.info(
                    "Created PromptTemplate: tenant=%s, name=%s",
                    tenant_id, 'interleaved_thinking',
                )

        if created_count:
            logger.info("Total PromptTemplates created: %d", created_count)
        else:
            logger.info("All PromptTemplates already exist, skipping.")

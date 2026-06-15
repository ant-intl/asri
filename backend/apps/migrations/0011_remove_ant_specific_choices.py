"""
Migration: Remove Ant-specific choices from ProviderType and MCP ClientType.

- LLMProviderConfig.provider_type: remove 'cockpit' choice
- McpServerConfig.client_type: remove 'sofapy' choice, update 'http' label
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0010_simplify_mcp_config_to_json'),
    ]

    operations = [
        # Update LLMProviderConfig.provider_type choices (remove cockpit)
        migrations.AlterField(
            model_name='llmproviderconfig',
            name='provider_type',
            field=models.CharField(
                choices=[
                    ('openai', 'OpenAI'),
                    ('ollama', 'Ollama'),
                    ('ucloud', 'UCloud'),
                    ('asri_gateway', 'ASRI Gateway'),
                    ('custom', 'Custom'),
                ],
                db_index=True,
                default='openai',
                max_length=20,
            ),
        ),
        # Update McpServerConfig.client_type choices (remove sofapy, update http label)
        migrations.AlterField(
            model_name='mcpserverconfig',
            name='client_type',
            field=models.CharField(
                choices=[
                    ('stdio', 'Stdio (npx/command)'),
                    ('http', 'HTTP'),
                    ('custom', 'Custom HTTP'),
                ],
                db_index=True,
                default='stdio',
                help_text='MCP client type: stdio, http, or custom',
                max_length=20,
            ),
        ),
    ]

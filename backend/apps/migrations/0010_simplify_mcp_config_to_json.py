"""Simplify MCP server config: replace individual fields with JSON config.

This migration adds client_type and config fields.
The old individual fields (endpoint, merchant_id, etc.) were
removed manually via SQL before this migration was applied.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0009_merge_20260331_1749'),
    ]

    operations = [
        migrations.AddField(
            model_name='mcpserverconfig',
            name='client_type',
            field=models.CharField(
                max_length=20,
                choices=[
                    ('stdio', 'Stdio (npx/command)'),
                    ('http', 'HTTP (Alipay MCP)'),
                    ('custom', 'Custom HTTP'),
                    ('sofapy', 'SofaPy'),
                ],
                default='stdio',
                db_index=True,
                help_text='MCP client type: stdio, http, custom, or sofapy',
            ),
        ),
        migrations.AddField(
            model_name='mcpserverconfig',
            name='config',
            field=models.JSONField(
                default=dict,
                blank=True,
                help_text='Client-specific configuration',
            ),
        ),
        migrations.AlterField(
            model_name='mcpserverconfig',
            name='args',
            field=models.JSONField(
                default=list,
                blank=True,
                help_text='Command arguments as JSON array',
            ),
        ),
        migrations.AlterField(
            model_name='mcpserverconfig',
            name='command',
            field=models.CharField(max_length=500, blank=True, default=''),
        ),
    ]

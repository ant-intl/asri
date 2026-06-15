from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0023_version_snapshot_tenant_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='mcptoolmockconfig',
            name='tenant_id',
            field=models.CharField(
                blank=True,
                db_index=True,
                default='',
                help_text='Tenant identifier',
                max_length=100,
            ),
        ),
        migrations.AlterUniqueTogether(
            name='mcptoolmockconfig',
            unique_together={('tenant_id', 'server_id', 'tool_name')},
        ),
    ]

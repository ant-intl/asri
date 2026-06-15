from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0022_prompttemplate_tenant_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='versionsnapshot',
            name='tenant_id',
            field=models.CharField(
                default='example',
                help_text='租户标识',
                max_length=64,
            ),
        ),
        migrations.RemoveIndex(
            model_name='versionsnapshot',
            name='idx_version_entity_number',
        ),
        migrations.RemoveIndex(
            model_name='versionsnapshot',
            name='idx_version_entity_active',
        ),
        migrations.AddIndex(
            model_name='versionsnapshot',
            index=models.Index(
                fields=['tenant_id', 'entity_type', 'entity_id', 'version_number'],
                name='idx_v_tenant_entity_number',
            ),
        ),
        migrations.AddIndex(
            model_name='versionsnapshot',
            index=models.Index(
                fields=['tenant_id', 'entity_type', 'entity_id', 'is_active'],
                name='idx_v_tenant_entity_active',
            ),
        ),
    ]

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0013_add_external_session_id'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatsession',
            name='external_source',
            field=models.CharField(
                max_length=64,
                null=True,
                blank=True,
                db_index=True,
                help_text='External system identifier (e.g., crm, customer-service)',
            ),
        ),
        migrations.AddIndex(
            model_name='chatsession',
            index=models.Index(
                fields=['external_source', 'external_session_id'],
                name='chatbot_sess_source_external_idx',
            ),
        ),
    ]

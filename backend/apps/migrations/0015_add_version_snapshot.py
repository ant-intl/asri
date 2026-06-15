from django.db import migrations, models
import uuid
import apps.entities.fields


class Migration(migrations.Migration):

    dependencies = [
        ('apps', '0014_add_external_source'),
    ]

    operations = [
        migrations.CreateModel(
            name='VersionSnapshot',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('entity_type', models.CharField(
                    choices=[('prompt_template', 'Prompt Template'), ('skill', 'Skill')],
                    db_index=True,
                    help_text='实体类型：prompt_template 或 skill',
                    max_length=32,
                )),
                ('entity_id', models.CharField(
                    db_index=True,
                    help_text='关联实体的 ID（PromptTemplate.id 或 Skill.skill_id）',
                    max_length=64,
                )),
                ('version_number', models.PositiveIntegerField(help_text='版本号，同一实体内自增')),
                ('label', models.CharField(blank=True, default='', help_text="用户自定义版本标签，如 'v1.0-prod'", max_length=128)),
                ('description', models.TextField(blank=True, default='', help_text='版本变更描述')),
                ('snapshot_data', apps.entities.fields.JsonTextField(default=dict, help_text='实体完整快照，JSON 格式')),
                ('is_active', models.BooleanField(db_index=True, default=False, help_text='是否为当前生效版本')),
                ('created_by', models.CharField(blank=True, default='', help_text='创建者标识', max_length=64)),
                ('gmt_create', models.DateTimeField(auto_now_add=True)),
                ('gmt_modified', models.DateTimeField(auto_now=True)),
            ],
            options={
                'db_table': 'chatbot_version_snapshot',
                'ordering': ['-version_number'],
            },
        ),
        migrations.AddIndex(
            model_name='versionsnapshot',
            index=models.Index(
                fields=['entity_type', 'entity_id', 'version_number'],
                name='idx_version_entity_number',
            ),
        ),
        migrations.AddIndex(
            model_name='versionsnapshot',
            index=models.Index(
                fields=['entity_type', 'entity_id', 'is_active'],
                name='idx_version_entity_active',
            ),
        ),
    ]

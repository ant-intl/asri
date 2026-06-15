"""Merge 0011_remove_ant_specific_choices into the main branch."""
from django.db import migrations


class Migration(migrations.Migration):
    """Merge migration to resolve conflicting leaf nodes."""

    dependencies = [
        ('apps', '0026_chatbot_prompt_new_table'),
        ('apps', '0011_remove_ant_specific_choices'),
    ]

    operations = [
    ]

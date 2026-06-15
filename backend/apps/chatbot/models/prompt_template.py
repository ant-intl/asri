"""
Prompt Template model for database-driven prompt configuration.
"""
import uuid

from django.db import models

from apps.entities.fields import JsonTextField


class PromptTemplate(models.Model):
    """Prompt template configuration model.

    Relationship with the existing Prompt class:
    - The name field corresponds to the Prompt class registration name (e.g. 'react', 'skill_decision')
    - layers is the sole source of prompt content (JSON array); the first layer with target=system
      is equivalent to the old system_template
    - user_template_mode distinguishes message construction modes
    - extractor_config specifies which Extractor to use
    """

    # Message construction mode enum
    class MessageMode(models.TextChoices):
        GENERIC = 'generic', 'Generic mode [system, *history, user]'
        CUSTOM = 'custom', 'Custom mode (use user_template)'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Tenant isolation
    tenant_id = models.CharField(max_length=64, db_index=True,
        default='example', help_text='Tenant identifier')

    # Associated with existing Prompt class (no foreign key, logically associated by name field)
    name = models.CharField(max_length=100,
        help_text="Corresponds to the Prompt class registration name, e.g. 'react', 'skill_decision'")

    description = models.TextField(blank=True, help_text="Template description")

    # system_template (kept for backward compatibility with old data, but layers takes priority)
    system_template = models.TextField(blank=True,
        help_text="System Prompt template (Jinja2), empty uses hardcoded default")

    # Message construction mode
    user_template_mode = models.CharField(max_length=20, choices=MessageMode.choices,
        default=MessageMode.GENERIC, help_text="generic=generic mode, custom=custom mode")

    # user_template (only used when user_template_mode=custom)
    user_template = models.TextField(blank=True,
        help_text="User message template (Jinja2), only used in custom mode")

    # layers (sole source of Prompt content, replaces system_template)
    layers = JsonTextField(
        default=list,
        help_text="""Prompt layers configuration (JSON array).
        The first layer with target=system is equivalent to the old system_template.
        Each item contains: name(str), target(system|user), strategy(always|first_turn),
        template(str, Jinja2), order(int), is_active(bool).
        When layers is non-empty, it takes priority over system_template.""",
    )

    # Extractor configuration
    extractor_config = JsonTextField(default=dict,
        help_text="""
        Parser configuration, example:
        {
            "type": "xml_tags",
            "tool_keys": ["tool_call"],
            "think_keys": ["think"],
            "answer_keys": ["answer"]
        }
        type options: xml_tags | json | react
        """)

    # Metadata
    is_active = models.BooleanField(default=True,
        help_text="When enabled, overrides hardcoded defaults")

    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chatbot_prompt'
        ordering = ['-gmt_create']
        constraints = [
            models.UniqueConstraint(
                fields=['tenant_id', 'name'],
                name='uk_prompt_tenant_id_name',
            ),
        ]
        indexes = [
            models.Index(fields=['name']),
            models.Index(fields=['is_active']),
        ]

    def __str__(self):
        return self.name




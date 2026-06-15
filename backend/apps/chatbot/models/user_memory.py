"""
User Memory model for persistent user memory storage.
"""
import uuid

from django.db import models

from apps.entities.fields import JsonTextField


class UserMemory(models.Model):
    """User memory model.

    Stores important user information such as preferences, key facts, goals, etc.
    Logically associated via the user_id field without using foreign keys.
    """

    # Memory category enum
    class Category(models.TextChoices):
        PREFERENCE = 'preference', 'Preference'
        FACT = 'fact', 'Fact'
        GOAL = 'goal', 'Goal'
        OTHER = 'other', 'Other'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # Associated user (no foreign key, logical constraint enforced in code)
    user_id = models.CharField(max_length=64, db_index=True)
    tenant_id = models.CharField(max_length=64, db_index=True, default='')

    # Memory content
    content = models.TextField()

    # Category
    category = models.CharField(
        max_length=32,
        choices=Category.choices,
        default=Category.OTHER
    )

    # Extended metadata
    metadata = JsonTextField(default=dict)

    # Timestamps
    gmt_create = models.DateTimeField(auto_now_add=True)
    gmt_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chatbot_user_memory'
        ordering = ['-gmt_create']
        indexes = [
            models.Index(fields=['user_id', 'tenant_id', '-gmt_create']),
            models.Index(fields=['user_id', 'tenant_id', 'category']),
        ]

    def __str__(self):
        return f"{self.user_id}: {self.content[:50]}"

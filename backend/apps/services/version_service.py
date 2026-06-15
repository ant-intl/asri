"""
VersionService - business logic for version snapshot management.

Provides unified version management for PromptTemplate and Skill entities.
Uses difflib for text diff computation (no external dependencies).
"""
import difflib
import logging
from typing import Any

from django.db import transaction

from apps.entities import VersionSnapshot, Skill
from apps.chatbot.models.prompt_template import PromptTemplate

logger = logging.getLogger(__name__)

# Fields to snapshot for each entity type
PROMPT_SNAPSHOT_FIELDS = [
    'name', 'description', 'system_template',
    'user_template_mode', 'user_template', 'extractor_config',
    'layers',
]
SKILL_SNAPSHOT_FIELDS = [
    'name', 'description', 'content', 'is_active', 'metadata',
]


class VersionService:
    """Business service for managing version snapshots."""

    @staticmethod
    def create_snapshot(
        entity_type: str,
        entity_id: str,
        label: str = '',
        description: str = '',
        created_by: str = '',
        tenant_id: str | None = None,
    ) -> VersionSnapshot:
        """Create a version snapshot for an entity.

        Serializes the current entity state, auto-increments version_number,
        and marks the new snapshot as active (deactivates previous).

        Args:
            entity_type: 'prompt_template' or 'skill'.
            entity_id: The entity's primary key value.
            label: Optional user-given label.
            description: Optional change description.
            created_by: Optional creator identifier.
            tenant_id: If provided, verify the entity belongs to this tenant.

        Returns:
            The created VersionSnapshot.

        Raises:
            ValueError: If entity_type is invalid or entity not found.
        """
        # Load the entity (with optional tenant filter)
        entity = VersionService._load_entity(entity_type, entity_id, tenant_id=tenant_id)
        if entity is None:
            raise ValueError(f"{entity_type} with id '{entity_id}' not found")

        # Get tenant_id from parent entity
        tenant_id = getattr(entity, 'tenant_id', 'example')

        # Serialize entity state
        snapshot_data = VersionService._serialize_entity(entity_type, entity)

        with transaction.atomic():
            # Compute next version number with row lock for concurrency safety
            last_version = (
                VersionSnapshot.objects
                .select_for_update()
                .filter(entity_type=entity_type, entity_id=entity_id)
                .order_by('-version_number')
                .first()
            )
            version_number = (last_version.version_number + 1) if last_version else 1

            # Deactivate previous active snapshots
            VersionSnapshot.objects.filter(
                entity_type=entity_type,
                entity_id=entity_id,
                is_active=True,
            ).update(is_active=False)

            # Create new snapshot
            snapshot = VersionSnapshot.objects.create(
                entity_type=entity_type,
                entity_id=entity_id,
                tenant_id=tenant_id,
                version_number=version_number,
                label=label,
                description=description,
                snapshot_data=snapshot_data,
                is_active=True,
                created_by=created_by,
            )

        logger.info(
            f"Created version snapshot v{version_number} for "
            f"{entity_type}/{entity_id}"
        )
        return snapshot

    @staticmethod
    def list_versions(
        entity_type: str,
        entity_id: str,
        page: int = 1,
        page_size: int = 20,
        tenant_id: str | None = None,
    ) -> tuple[list[VersionSnapshot], int]:
        """List version snapshots for an entity.

        Args:
            entity_type: 'prompt_template' or 'skill'.
            entity_id: The entity's primary key value.
            page: Page number (1-based).
            page_size: Items per page.
            tenant_id: If provided, filter by tenant.

        Returns:
            Tuple of (version list, total count).
        """
        filters: dict = {
            'entity_type': entity_type,
            'entity_id': entity_id,
        }
        if tenant_id:
            filters['tenant_id'] = tenant_id
        queryset = VersionSnapshot.objects.filter(**filters).order_by('-version_number')

        total = queryset.count()
        offset = (page - 1) * page_size
        versions = list(queryset[offset:offset + page_size])
        return versions, total

    @staticmethod
    def get_version(version_id: str, tenant_id: str | None = None) -> VersionSnapshot | None:
        """Get a single version snapshot by ID.

        Args:
            version_id: The snapshot's UUID.
            tenant_id: If provided, verify the snapshot belongs to this tenant.

        Returns:
            VersionSnapshot or None if not found.
        """
        filters: dict = {'pk': version_id}
        if tenant_id:
            filters['tenant_id'] = tenant_id
        try:
            return VersionSnapshot.objects.get(**filters)
        except VersionSnapshot.DoesNotExist:
            return None

    @staticmethod
    def activate_version(version_id: str, tenant_id: str | None = None) -> VersionSnapshot:
        """Activate a version snapshot (rollback to this version).

        Writes the snapshot data back to the parent entity and marks
        this snapshot as active. Does NOT create a new version.

        Args:
            version_id: The snapshot's UUID.
            tenant_id: If provided, verify the snapshot belongs to this tenant.

        Returns:
            The activated VersionSnapshot.

        Raises:
            ValueError: If snapshot not found or entity not found.
        """
        snapshot = VersionService.get_version(version_id, tenant_id=tenant_id)
        if snapshot is None:
            raise ValueError(f"Version snapshot '{version_id}' not found")

        with transaction.atomic():
            # Deactivate other versions for same entity
            VersionSnapshot.objects.filter(
                entity_type=snapshot.entity_type,
                entity_id=snapshot.entity_id,
                is_active=True,
            ).update(is_active=False)

            # Activate target snapshot
            snapshot.is_active = True
            snapshot.save(update_fields=['is_active', 'gmt_modified'])

            # Write snapshot data back to parent entity
            VersionService._restore_entity(snapshot)

        logger.info(
            f"Activated version v{snapshot.version_number} for "
            f"{snapshot.entity_type}/{snapshot.entity_id}"
        )
        return snapshot

    @staticmethod
    def compute_diff(version_id_a: str, version_id_b: str, tenant_id: str | None = None) -> dict[str, Any]:
        """Compute diff between two version snapshots.

        Uses difflib for line-by-line text comparison. JSON fields are
        pretty-printed and compared as text.

        Args:
            version_id_a: First snapshot UUID (typically older).
            version_id_b: Second snapshot UUID (typically newer).
            tenant_id: If provided, verify both snapshots belong to this tenant.

        Returns:
            Structured diff result with per-field line comparisons.

        Raises:
            ValueError: If either snapshot not found or they belong to
                different entity types.
        """
        snap_a = VersionService.get_version(version_id_a, tenant_id=tenant_id)
        snap_b = VersionService.get_version(version_id_b, tenant_id=tenant_id)

        if snap_a is None:
            raise ValueError(f"Version snapshot '{version_id_a}' not found")
        if snap_b is None:
            raise ValueError(f"Version snapshot '{version_id_b}' not found")
        if snap_a.entity_type != snap_b.entity_type:
            raise ValueError("Cannot diff snapshots of different entity types")

        data_a = snap_a.snapshot_data or {}
        data_b = snap_b.snapshot_data or {}

        # Collect all field names from both snapshots
        all_fields = sorted(set(list(data_a.keys()) + list(data_b.keys())))

        fields_diff: dict[str, dict[str, Any]] = {}
        for field_name in all_fields:
            value_a = data_a.get(field_name, '')
            value_b = data_b.get(field_name, '')

            # Determine field type and convert to text
            if isinstance(value_a, (dict, list)) or isinstance(value_b, (dict, list)):
                import json
                text_a = json.dumps(value_a, indent=2, ensure_ascii=False)
                text_b = json.dumps(value_b, indent=2, ensure_ascii=False)
                field_type = 'json'
            else:
                text_a = str(value_a) if value_a is not None else ''
                text_b = str(value_b) if value_b is not None else ''
                field_type = 'text'

            lines = VersionService._compute_line_diff(text_a, text_b)
            fields_diff[field_name] = {
                'type': field_type,
                'lines': lines,
            }

        return {
            'version_a': {
                'id': str(snap_a.id),
                'version_number': snap_a.version_number,
                'label': snap_a.label,
            },
            'version_b': {
                'id': str(snap_b.id),
                'version_number': snap_b.version_number,
                'label': snap_b.label,
            },
            'fields': fields_diff,
        }

    @staticmethod
    def update_version_label(
        version_id: str,
        label: str = '',
        description: str = '',
        tenant_id: str | None = None,
    ) -> VersionSnapshot | None:
        """Update the label and/or description of a version snapshot.

        Args:
            version_id: The snapshot's UUID.
            label: New label value.
            description: New description value.
            tenant_id: If provided, verify the snapshot belongs to this tenant.

        Returns:
            Updated VersionSnapshot or None if not found.
        """
        filters: dict = {'pk': version_id}
        if tenant_id:
            filters['tenant_id'] = tenant_id
        try:
            snapshot = VersionSnapshot.objects.get(**filters)
            snapshot.label = label
            snapshot.description = description
            snapshot.save(update_fields=['label', 'description', 'gmt_modified'])
            return snapshot
        except VersionSnapshot.DoesNotExist:
            return None

    @staticmethod
    def delete_version(version_id: str, tenant_id: str | None = None) -> bool:
        """Delete a version snapshot.

        Prevents deletion of the currently active version.

        Args:
            version_id: The snapshot's UUID.
            tenant_id: If provided, verify the snapshot belongs to this tenant.

        Returns:
            True if deleted, False if not found or is active.

        Raises:
            ValueError: If attempting to delete the active version.
        """
        filters: dict = {'pk': version_id}
        if tenant_id:
            filters['tenant_id'] = tenant_id
        try:
            snapshot = VersionSnapshot.objects.get(**filters)
            if snapshot.is_active:
                raise ValueError("Cannot delete the currently active version")

            snapshot.delete()
            logger.info(f"Deleted version snapshot '{version_id}'")
            return True
        except VersionSnapshot.DoesNotExist:
            return False

    # ---- Internal helpers ----

    @staticmethod
    def _load_entity(entity_type: str, entity_id: str, tenant_id: str | None = None) -> Any:
        """Load an entity from the database by type and ID.

        Args:
            entity_type: 'prompt_template' or 'skill'.
            entity_id: The entity's primary key value.
            tenant_id: If provided, filter by tenant for security.

        Returns:
            The model instance, or None if not found.
        """
        try:
            if entity_type == VersionSnapshot.EntityType.PROMPT_TEMPLATE:
                filters: dict = {'pk': entity_id}
                if tenant_id:
                    filters['tenant_id'] = tenant_id
                return PromptTemplate.objects.get(**filters)
            elif entity_type == VersionSnapshot.EntityType.SKILL:
                filters = {'skill_id': entity_id}
                if tenant_id:
                    filters['tenant_id'] = tenant_id
                return Skill.objects.get(**filters)
            else:
                raise ValueError(f"Unknown entity_type: {entity_type}")
        except (PromptTemplate.DoesNotExist, Skill.DoesNotExist):
            return None

    @staticmethod
    def _serialize_entity(entity_type: str, entity: Any) -> dict[str, Any]:
        """Serialize an entity's fields into a snapshot dict.

        Args:
            entity_type: 'prompt_template' or 'skill'.
            entity: The model instance.

        Returns:
            Dict of field name -> value.
        """
        if entity_type == VersionSnapshot.EntityType.PROMPT_TEMPLATE:
            fields = PROMPT_SNAPSHOT_FIELDS
        else:
            fields = SKILL_SNAPSHOT_FIELDS

        return {field: getattr(entity, field, '') for field in fields}

    @staticmethod
    def _restore_entity(snapshot: VersionSnapshot) -> None:
        """Restore entity fields from snapshot data.

        Args:
            snapshot: The VersionSnapshot whose data to restore.
        """
        data = snapshot.snapshot_data
        entity_type = snapshot.entity_type
        entity_id = snapshot.entity_id

        if entity_type == VersionSnapshot.EntityType.PROMPT_TEMPLATE:
            try:
                template = PromptTemplate.objects.get(pk=entity_id)
                for field in PROMPT_SNAPSHOT_FIELDS:
                    if field in data:
                        setattr(template, field, data[field])
                template.save()
                logger.info(f"Restored prompt template '{entity_id}' from snapshot")
            except PromptTemplate.DoesNotExist:
                logger.error(f"PromptTemplate '{entity_id}' not found for restore")

        elif entity_type == VersionSnapshot.EntityType.SKILL:
            try:
                skill = Skill.objects.get(skill_id=entity_id)
                for field in SKILL_SNAPSHOT_FIELDS:
                    if field in data:
                        setattr(skill, field, data[field])
                skill.save()

                # Refresh skill in registry
                from apps.services.skill_service import SkillService
                SkillService.refresh_skill(str(skill.skill_id), skill.tenant_id)

                logger.info(f"Restored skill '{entity_id}' from snapshot")
            except Skill.DoesNotExist:
                logger.error(f"Skill '{entity_id}' not found for restore")

    @staticmethod
    def _compute_line_diff(text_a: str, text_b: str) -> list[dict[str, Any]]:
        """Compute line-by-line diff between two texts using difflib.

        Args:
            text_a: Original text.
            text_b: Modified text.

        Returns:
            List of diff line entries with type, content, and line numbers.
        """
        lines_a = text_a.splitlines(keepends=True)
        lines_b = text_b.splitlines(keepends=True)

        # Use unified diff to identify changes
        matcher = difflib.SequenceMatcher(None, lines_a, lines_b)
        result: list[dict[str, Any]] = []

        line_num_a = 0
        line_num_b = 0

        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                for k in range(i2 - i1):
                    line_num_a += 1
                    line_num_b += 1
                    result.append({
                        'type': 'unchanged',
                        'content': lines_a[i1 + k].rstrip('\n\r'),
                        'line_a': line_num_a,
                        'line_b': line_num_b,
                    })
            elif tag == 'replace':
                # Removed lines from a
                for k in range(i1, i2):
                    line_num_a += 1
                    result.append({
                        'type': 'removed',
                        'content': lines_a[k].rstrip('\n\r'),
                        'line_a': line_num_a,
                        'line_b': None,
                    })
                # Added lines from b
                for k in range(j1, j2):
                    line_num_b += 1
                    result.append({
                        'type': 'added',
                        'content': lines_b[k].rstrip('\n\r'),
                        'line_a': None,
                        'line_b': line_num_b,
                    })
            elif tag == 'delete':
                for k in range(i1, i2):
                    line_num_a += 1
                    result.append({
                        'type': 'removed',
                        'content': lines_a[k].rstrip('\n\r'),
                        'line_a': line_num_a,
                        'line_b': None,
                    })
            elif tag == 'insert':
                for k in range(j1, j2):
                    line_num_b += 1
                    result.append({
                        'type': 'added',
                        'content': lines_b[k].rstrip('\n\r'),
                        'line_a': None,
                        'line_b': line_num_b,
                    })

        return result

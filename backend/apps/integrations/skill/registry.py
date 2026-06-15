"""
Skill registry with tenant-scoped extensions.
"""
import logging
from typing import Optional

from .base import BaseSkill, SkillRegistry as BaseRegistry

logger = logging.getLogger(__name__)


class SkillRegistry(BaseRegistry):
    """Skill registry with extended functionality."""

    @classmethod
    def _get_skill_bucket(
        cls,
        skills_json_path: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> dict[str, BaseSkill]:
        """Return the appropriate skill bucket.

        When *skills_json_path* is provided, look up skills from the
        path-based index (e.g. ``remote://doc_id``).  Otherwise fall back
        to the current tenant's bucket.

        Args:
            skills_json_path: Source path for path-based lookup.
            tenant_id: Explicit tenant ID to use. Falls back to contextvar
                when not provided.
        """
        if skills_json_path:
            result = cls._skills_by_path.get(skills_json_path, {})
            logger.debug(
                f"_get_skill_bucket: path={skills_json_path}, "
                f"available_paths={list(cls._skills_by_path.keys())}, "
                f"skills_count={len(result)}"
            )
            return result
        if tenant_id is None:
            from ...tenant.context import get_current_tenant_id
            tenant_id = get_current_tenant_id()
        result = cls._skills.get(tenant_id, {})
        logger.debug(
            f"_get_skill_bucket: tenant_id={tenant_id}, "
            f"available_tenants={list(cls._skills.keys())}, "
            f"skills_count={len(result)}"
        )
        return result

    @classmethod
    def list_skills_with_descriptions(
        cls,
        skills_json_path: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> list[dict]:
        """Return skill name/description/content dicts.

        Args:
            skills_json_path: If provided, return skills loaded from this
                source path instead of the current tenant's skills.
            tenant_id: Explicit tenant ID to use. Falls back to contextvar
                when not provided.
        """
        bucket = cls._get_skill_bucket(skills_json_path, tenant_id=tenant_id)
        skills = [
            {
                "name": skill.name,
                "description": skill.description,
                "content": getattr(skill, 'content', ''),
                "skill_dir": getattr(skill, 'skill_dir', None),
            }
            for skill in bucket.values()
        ]
        skills.sort(key=lambda s: s['name'])
        return skills

    @classmethod
    def create_and_register_tools(cls, tenant_id: Optional[str], config: dict) -> bool:
        """Create and register SkillLoadTool based on configuration.

        Args:
            tenant_id: Tenant ID for isolation
            config: Tool configuration dict, should contain:
                - skills_json_path: Source path for skills (e.g. ``remote://doc_id``)

        Returns:
            True if successful, False otherwise
        """
        from apps.integrations.tool.base import ToolRegistry

        if not config:
            logger.debug("No skill tool config provided, skipping")
            return False

        try:
            success = ToolRegistry.create_and_register(
                name='skill_load',
                tenant_id=tenant_id,
                config=config,
                instance_name='skill_load',
                class_type='skill_load',
            )
            if success:
                logger.info(f"Registered skill_load tool for tenant '{tenant_id}'")
            return success
        except Exception as e:
            logger.error(f"Failed to register skill_load tool: {e}")
            return False

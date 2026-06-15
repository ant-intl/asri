"""
Tenant-aware skill loading dispatcher.

Supports ``SKILLS_LOADER`` — a Python dotted path to a callable
returning ``list[BaseSkill]``.
"""
import logging
from typing import Optional

from django.utils.module_loading import import_string

from .base import BaseSkill, SkillRegistry

logger = logging.getLogger(__name__)


def load_skills_for_tenant(config: dict, tenant_id: Optional[str] = None) -> int:
    """Load and register skills for a tenant based on its configuration.

    Args:
        config: Merged tenant configuration dict.
        tenant_id: Tenant to register skills for. ``None`` means global default.

    Returns:
        Number of skills successfully registered.
    """
    loader_path = config.get('SKILLS_LOADER')
    if not loader_path:
        return 0

    try:
        fn = import_string(loader_path)
        skills = fn()
        count = 0
        for skill in skills:
            if isinstance(skill, BaseSkill):
                SkillRegistry.register(skill, tenant_id=tenant_id)
                count += 1
            else:
                logger.warning(
                    f"SKILLS_LOADER '{loader_path}' returned non-BaseSkill "
                    f"object: {type(skill).__name__}"
                )
        logger.info(
            f"Loaded {count} skills via SKILLS_LOADER '{loader_path}' "
            f"(tenant={tenant_id})"
        )
        return count
    except Exception as e:
        logger.error(
            f"Failed to load skills via SKILLS_LOADER '{loader_path}' "
            f"(tenant={tenant_id}): {e}"
        )
        return 0

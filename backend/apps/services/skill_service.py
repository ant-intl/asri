"""
SkillService - business logic for skill management (filesystem-only).
"""
import logging

from apps.utils.skill_paths import get_tenant_skills_dir

logger = logging.getLogger(__name__)


class SkillService:
    """Business service for managing skills."""

    @staticmethod
    def load_all_tenant_skills() -> None:
        """Load filesystem skills for all known tenants.

        Called during application startup.  For each active tenant, scans
        ``{SKILLS_ROOT}/{tenant_id}/skills/`` and registers each
        ``SKILL.md`` as a :class:`FilesystemSkill`.
        """
        from apps.integrations.skill.filesystem_skill_loader import scan_skills
        from apps.tenant.registry import get_tenant_registry

        try:
            registry = get_tenant_registry()
            tenant_ids = registry.list_tenant_ids()
            for tenant_id in tenant_ids:
                if tenant_id:
                    base_dir = get_tenant_skills_dir(tenant_id)
                    scan_skills(base_dir=base_dir, tenant_id=tenant_id)
        except Exception as e:
            logger.debug(f"Could not load filesystem skills: {e}")
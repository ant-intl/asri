"""
Base Skill abstract class and tenant-scoped registry.
"""
from abc import ABC, abstractmethod
from typing import Any, Optional

_SENTINEL = object()


class BaseSkill(ABC):
    """Abstract base class for skills (complex multi-step capabilities)."""

    name: str = ''
    description: str = ''
    parameters_schema: dict = {}

    @abstractmethod
    async def execute(self, input_text: str, context: Any) -> str:
        """Execute the skill and return result."""
        pass


class SkillRegistry:
    """Tenant-scoped registry for skill instances.

    Skills are stored in a two-level dict keyed by ``(tenant_id, skill_name)``.
    Query methods automatically resolve the current tenant from contextvars.
    When a tenant has no skills configured, an empty list is returned (no
    fallback to the global default bucket).

    A secondary index ``_skills_by_path`` maps the source path (e.g.
    ``remote://doc_id``) to its skill set, allowing request-level overrides
    of the skill collection via ``skills_json_path``.
    """

    # {tenant_id: {skill_name: BaseSkill}}
    _skills: dict[Optional[str], dict[str, BaseSkill]] = {}
    # {source_path: {skill_name: BaseSkill}}
    _skills_by_path: dict[str, dict[str, BaseSkill]] = {}

    @classmethod
    def register(
        cls,
        skill: BaseSkill,
        tenant_id: Optional[str] = None,
        source_path: Optional[str] = None,
    ) -> None:
        """Register a skill under a specific tenant bucket.

        Args:
            skill: Skill instance to register.
            tenant_id: Tenant to register for. ``None`` means global default.
            source_path: Source path used for path-based lookups (e.g. ``remote://doc_id``).
        """
        bucket = cls._skills.setdefault(tenant_id, {})
        bucket[skill.name.lower()] = skill
        if source_path:
            path_bucket = cls._skills_by_path.setdefault(source_path, {})
            path_bucket[skill.name.lower()] = skill
        import logging
        logging.getLogger(__name__).debug(
            f"Registered skill '{skill.name}' for tenant_id={tenant_id}, "
            f"source_path={source_path}. "
            f"Total tenants in _skills: {list(cls._skills.keys())}"
        )

    @classmethod
    def get_skill(cls, name: str) -> Optional[BaseSkill]:
        """Get a skill by name for the current tenant.

        Looks up the skill in the current tenant's bucket only.
        No fallback to the global default bucket.
        """
        from ...tenant.context import get_current_tenant_id
        tenant_id = get_current_tenant_id()
        bucket = cls._skills.get(tenant_id, {})
        return bucket.get(name.lower())

    @classmethod
    def list_skills(cls) -> list[str]:
        """List all registered skill names for the current tenant."""
        from ...tenant.context import get_current_tenant_id
        tenant_id = get_current_tenant_id()
        bucket = cls._skills.get(tenant_id, {})
        return list(bucket.keys())

    @classmethod
    def clear(cls, tenant_id: Any = _SENTINEL) -> None:
        """Clear skill cache.

        Args:
            tenant_id: If omitted, clears **all** tenants.
                If provided (including ``None``), clears only that tenant.
        """
        if tenant_id is _SENTINEL:
            cls._skills.clear()
            cls._skills_by_path.clear()
        else:
            cls._skills.pop(tenant_id, None)

    @classmethod
    def clear_by_source(cls, source_path: str, tenant_id: Optional[str] = None) -> None:
        """Clear all skills registered under a specific source path.

        Removes skills from both ``_skills_by_path`` and the tenant bucket
        in ``_skills``.

        Args:
            source_path: The source path (e.g. ``remote://doc_id``).
            tenant_id: Tenant whose bucket should also be cleaned.
        """
        removed = cls._skills_by_path.pop(source_path, {})
        if tenant_id is not None and removed:
            bucket = cls._skills.get(tenant_id, {})
            for name in removed:
                bucket.pop(name, None)

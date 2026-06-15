"""
Centralised helpers for resolving skill filesystem paths.

Directory layout::

    {SKILLS_ROOT}/{tenant_id}/skills/{skill_name}/SKILL.md

``SKILLS_ROOT`` is read from Django settings (set via ``ASRI_SKILLS_DIR``
environment variable, defaulting to ``<project_root>/data/``).
"""
from pathlib import Path

from django.conf import settings


def get_skills_root() -> Path:
    """Return the absolute ``SKILLS_ROOT`` path as a :class:`~pathlib.Path`."""
    return Path(settings.SKILLS_ROOT)


def get_tenant_skills_dir(tenant_id: str) -> str:
    """Return absolute path for a tenant's skill directory.

    Layout: ``{SKILLS_ROOT}/{tenant_id}/skills/``

    Args:
        tenant_id: The tenant identifier (e.g. ``"example"``).

    Returns:
        Absolute path string (directory may not exist yet).
    """
    return str(get_skills_root() / tenant_id / "skills")

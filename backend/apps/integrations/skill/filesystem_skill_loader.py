"""
Filesystem skill loader — scan a directory tree and register FilesystemSkills.

Usage::

    from filesystem_skill_loader import scan_skills

    scan_skills("data/skills", tenant_id="default")
"""
import logging
import os
import re

from .base import SkillRegistry
from .filesystem_skill import FilesystemSkill

logger = logging.getLogger(__name__)


def parse_frontmatter(filepath: str) -> tuple[str, str] | None:
    """Extract ``name`` and ``description`` from YAML frontmatter.

    Parses the ``---`` … ``---`` block at the top of a markdown file
    using a simple regex (avoids a hard dependency on PyYAML).

    Returns ``(name, description)``, or ``None`` if either field is
    missing.
    """
    try:
        with open(filepath, "r", encoding="utf-8") as fh:
            content = fh.read()
    except (OSError, UnicodeDecodeError):
        return None

    # Match the YAML frontmatter block
    m = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return None

    frontmatter = m.group(1)
    name_match = re.search(r"^name\s*:\s*(.+)", frontmatter, re.MULTILINE)
    desc_match = re.search(r"^description\s*:\s*(.+)", frontmatter, re.MULTILINE)

    if not name_match:
        return None

    name = name_match.group(1).strip()
    description = desc_match.group(1).strip() if desc_match else ""
    return name, description


def scan_skills(base_dir: str = "data/skills", tenant_id: str = "default") -> int:
    """Scan *base_dir* and register every subdirectory containing
    ``SKILL.md`` as a :class:`FilesystemSkill`.

    Only the ``name`` and ``description`` from the YAML frontmatter are
    extracted at registration time — the full ``SKILL.md`` content and
    references are loaded on demand when the LLM uses
    :func:`view_text_file`.

    Args:
        base_dir: Root directory to scan.
        tenant_id: Tenant ID to register skills under.

    Returns:
        Number of skills registered.
    """
    if not os.path.isdir(base_dir):
        logger.debug("Filesystem skill directory '%s' not found, skipping", base_dir)
        return 0

    count = 0
    for entry in os.scandir(base_dir):
        if not entry.is_dir():
            continue
        md_path = os.path.join(entry.path, "SKILL.md")
        if not os.path.isfile(md_path):
            continue

        parsed = parse_frontmatter(md_path)
        if parsed is None:
            logger.warning("Skipping '%s': missing or invalid frontmatter", entry.name)
            continue

        name, description = parsed
        skill = FilesystemSkill(
            name=name,
            description=description,
            skill_dir=entry.path,
        )
        SkillRegistry.register(skill, tenant_id=tenant_id)
        count += 1
        logger.info("Registered filesystem skill '%s' (tenant=%s)", name, tenant_id)

    logger.info("Loaded %d filesystem skills from '%s' (tenant=%s)", count, base_dir, tenant_id)
    return count

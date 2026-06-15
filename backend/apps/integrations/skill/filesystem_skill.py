"""
FilesystemSkill — skill loaded from a local filesystem directory.

Follows the agentskills.io standard: each skill is a directory with
SKILL.md, references/, script/, and optionally assets/.
"""
import os
import re
from typing import Any

from .base import BaseSkill


class FilesystemSkill(BaseSkill):
    """Skill loaded from a local filesystem directory."""

    def __init__(self, name: str, description: str, skill_dir: str):
        self.name = name
        self.description = description
        self.skill_dir = skill_dir
        self._parsed_instructions: str | None = None

    @property
    def instructions(self) -> str | None:
        """Extract ``## Instructions`` (or ``## Usage``) section from SKILL.md."""
        if self._parsed_instructions is None:
            content = self._read_skill_md()
            if content is None:
                self._parsed_instructions = ""
            else:
                self._parsed_instructions = (
                    self._extract_section(content, "Instructions")
                    or self._extract_section(content, "Usage")
                    or ""
                )
        return self._parsed_instructions or None

    @property
    def ref_names(self) -> list[str]:
        """List files in the ``references/`` directory (if it exists)."""
        ref_dir = os.path.join(self.skill_dir, "references")
        if not os.path.isdir(ref_dir):
            return []
        return sorted(os.listdir(ref_dir))

    def load_reference(self, name: str) -> str | None:
        """Read a single reference file by name.

        Args:
            name: Filename (e.g. ``conversion-formulas.md``).

        Returns:
            File content, or ``None`` if the file is not found.
        """
        ref_dir = os.path.join(self.skill_dir, "references")
        target = os.path.normpath(os.path.join(ref_dir, name))
        # Prevent directory traversal
        if not target.startswith(os.path.normpath(ref_dir)):
            return None
        if not os.path.isfile(target):
            return None
        try:
            with open(target, "r", encoding="utf-8") as fh:
                return fh.read()
        except (OSError, UnicodeDecodeError):
            return None

    @property
    def content(self) -> str:
        """Return the full SKILL.md content (read on demand)."""
        content = self._read_skill_md()
        return content or ""

    def _read_skill_md(self) -> str | None:
        """Read SKILL.md from the skill directory."""
        md_path = os.path.join(self.skill_dir, "SKILL.md")
        if not os.path.isfile(md_path):
            return None
        try:
            with open(md_path, "r", encoding="utf-8") as fh:
                return fh.read()
        except (OSError, UnicodeDecodeError):
            return None

    @staticmethod
    def _extract_section(content: str, section_name: str) -> str | None:
        """Extract a markdown section by heading name."""
        pattern = re.compile(
            rf"^##?\s*{re.escape(section_name)}\s*\n(.*?)(?=^##|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        match = pattern.search(content)
        return match.group(1).strip() if match else None

    async def execute(self, input_text: str, context: Any) -> str:
        """Return the full SKILL.md content when executed directly."""
        return self.content

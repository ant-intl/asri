"""
JSON-based Skill definition and parser.

Provides ``JSONSkill`` (a BaseSkill backed by markdown content) and
``SkillLoader`` (a parser that converts knowledge-platform JSON items
into ``JSONSkill`` instances).
"""
import re
import logging
from typing import Any

from .base import BaseSkill

logger = logging.getLogger(__name__)

# Patterns for extracting name/description from skill markdown content
NAME_PATTERN = re.compile(r'\nname:(?P<name>.*?)\n', re.S)
DESCRIPTION_PATTERN = re.compile(r'\ndescription:(?P<description>.*?)\n', re.S)


class JSONSkill(BaseSkill):
    """
    A skill loaded from JSON configuration.

    The execute() method returns the skill's full markdown content,
    which serves as reference material for the agent to follow
    when handling the user's request.
    """

    def __init__(
        self,
        name: str,
        description: str,
        content: str,
        doc_id: str = '',
        dataset_id: str = '',
        slice_id: str = '',
        labels: list | None = None,
        features: list | None = None,
    ):
        self.name = name
        self.description = description
        self.content = content
        self.doc_id = doc_id
        self.dataset_id = dataset_id
        self.slice_id = slice_id
        self.labels = labels or []
        self.features = features or []

    async def execute(self, input_text: str, context: Any) -> str:
        """
        Return the full skill content as reference material.

        Args:
            input_text: User query or additional context
            context: AgentContext instance

        Returns:
            The skill's complete markdown content
        """
        return self.content


class SkillLoader:
    """Parser utility for converting knowledge-platform JSON items into JSONSkill instances."""

    @staticmethod
    def _parse_skill(item: dict) -> JSONSkill | None:
        """
        Parse a single skill entry from JSON.

        Args:
            item: Dict with 'content', 'validStatus', 'title', etc.

        Returns:
            JSONSkill instance or None if invalid
        """
        # Filter invalid skills
        if item.get('validStatus') != 'VALID':
            return None

        content = item.get('content', '')
        if not content:
            return None

        # Extract name from markdown content
        name_match = NAME_PATTERN.search(content)
        if name_match:
            name = name_match.group('name').strip()
        else:
            # Fallback to title field
            name = item.get('title', '').strip()
            if not name:
                return None

        # Extract description from markdown content
        desc_match = DESCRIPTION_PATTERN.search(content)
        description = desc_match.group('description').strip() if desc_match else ''

        return JSONSkill(
            name=name,
            description=description,
            content=content,
            doc_id=item.get('docId', ''),
            dataset_id=item.get('datasetId', ''),
            slice_id=item.get('sliceId', ''),
            labels=item.get('labels', []),
            features=item.get('features', []),
        )

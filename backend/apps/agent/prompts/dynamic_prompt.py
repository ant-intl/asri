"""Dynamic prompt implementation that loads all configuration from database."""
from typing import Dict, Any, TYPE_CHECKING

from .base import BaseSystemPrompt
from .template_engine import PromptTemplateEngine

if TYPE_CHECKING:
    from ...chatbot.models.prompt_template import PromptTemplate


class DynamicPrompt(BaseSystemPrompt):
    """Dynamic prompt that loads all configuration from database.

    This class allows using arbitrary prompt names that are not hardcoded
    in the application. All configuration (templates, extractor_config, etc.)
    is loaded from the PromptTemplate database model.

    Priority:
    1. Database template (must exist and be active)
    2. Raises error if not found (no hardcoded fallback)

    Note:
        The template data is pre-loaded by the factory function (create_prompt/create_prompt_async)
        and passed to the constructor to avoid repeated database queries.
    """

    def __init__(self, name: str, db_template: 'PromptTemplate' = None):
        """Initialize with a prompt name and optional pre-loaded template.

        Args:
            name: The prompt name, must match a PromptTemplate.name in database.
            db_template: Optional pre-loaded PromptTemplate instance. If provided,
                it will be used instead of querying the database. This avoids
                repeated database queries when the factory function has already
                loaded the template.
        """
        self._name = name
        self._db_template = db_template

    @classmethod
    def from_frozen(cls, frozen_data: dict) -> 'DynamicPrompt':
        """Create DynamicPrompt from frozen snapshot data dict.

        Reconstructs a DynamicPrompt instance from snapshot-frozen
        PromptTemplate fields so that ``render()`` and ``build_messages()``
        work identically to the original prompt at snapshot time —
        without any live database queries.

        Args:
            frozen_data: The ``prompt`` dict from ``snapshot_data``,
                containing ``system_template``, ``user_template``,
                ``user_template_mode``, ``layers``, ``extractor_config``,
                and ``name``.

        Returns:
            A DynamicPrompt instance backed by frozen data.
        """
        from types import SimpleNamespace
        tmpl = SimpleNamespace()
        tmpl.system_template = frozen_data.get('system_template', '') or ''
        tmpl.user_template = frozen_data.get('user_template', '') or ''
        tmpl.user_template_mode = frozen_data.get('user_template_mode', 'generic')
        tmpl.layers = frozen_data.get('layers', []) or []
        tmpl.extractor_config = frozen_data.get('extractor_config', {}) or {}
        tmpl.id = frozen_data.get('prompt_id')
        name = frozen_data.get('name', 'snapshot')
        return cls(name, db_template=tmpl)

    @property
    def prompt_name(self) -> str:
        """Return the prompt name for database lookup."""
        return self._name

    @property
    def user_template_mode(self) -> 'PromptTemplate.MessageMode':
        """Get message mode from database template.

        This property overrides the base class default to use the
        user_template_mode value from the database template.

        Returns:
            The user_template_mode from the database template,
            or GENERIC as default if template not loaded.
        """
        if self._db_template:
            from ...chatbot.models.prompt_template import PromptTemplate
            mode = self._db_template.user_template_mode
            if mode == 'custom':
                return PromptTemplate.MessageMode.CUSTOM
        from ...chatbot.models.prompt_template import PromptTemplate
        return PromptTemplate.MessageMode.GENERIC

    def _get_db_template(self) -> 'PromptTemplate | None':
        """Return the pre-loaded template if available.

        This method overrides the base class method to use the pre-loaded
        template data provided by the factory function, avoiding repeated
        database queries.

        Returns:
            The pre-loaded PromptTemplate instance, or None if not available.
        """
        return self._db_template

    async def _get_db_template_async(self) -> 'PromptTemplate | None':
        """Return the pre-loaded template (async version).

        This method overrides the base class method to use the pre-loaded
        template data provided by the factory function.

        Returns:
            The pre-loaded PromptTemplate instance, or None if not available.
        """
        return self._db_template

    def _get_hardcoded_template(self) -> str:
        """Dynamic prompts require database configuration.

        Raises:
            RuntimeError: Always, since dynamic prompts must have DB config.
        """
        raise RuntimeError(
            f"DynamicPrompt '{self._name}' requires a database template. "
            f"Please create a PromptTemplate with name='{self._name}' and enable it."
        )

    def parse_response(self, response: str) -> Dict[str, Any]:
        """Parse LLM response using extractor configuration from database.

        Uses the extractor_config from the database template to determine
        how to parse the response.

        Args:
            response: The raw LLM response text.

        Returns:
            Dict with standardized keys based on extractor config.
        """
        from ...agent.pipeline.output_parser import OutputParserFactory

        config = self.get_extractor_config()
        extractor_cfg = config.get('extractor', {})
        mapper_cfg = config.get('mapper', {})

        extractor, mapper = OutputParserFactory.create(extractor_cfg, mapper_cfg)
        extracted = extractor.extract(response)
        mapped = mapper.map(extracted)

        return {
            'thought': mapped.get('think', ''),
            'action': mapped.get('tool_call', ''),
            'action_input': mapped.get('tool_input', {}),
            'raw': response,
        }

    def format_user_prompt(self, query: str, **kwargs) -> str:
        """Format user prompt using database template or return query as-is.

        If the database has a user_template, it will be rendered with the
        provided context. Otherwise, returns the query unchanged.

        Args:
            query: The user's query text.
            **kwargs: Additional context (history, skills, etc.)

        Returns:
            Formatted user prompt string.
        """
        if self._db_template and self._db_template.user_template:
            return PromptTemplateEngine.render(
                self._db_template.user_template,
                query=query,
                **kwargs
            )
        return query

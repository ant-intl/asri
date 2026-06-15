"""
Base system prompt abstract class.

All prompt types must inherit from BaseSystemPrompt and implement
render(), parse_response(), and format_user_prompt().
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, Any

logger = logging.getLogger(__name__)

from asgiref.sync import sync_to_async

from .template_engine import PromptTemplateEngine

if TYPE_CHECKING:
    from ...chatbot.models.prompt_template import PromptTemplate


class BaseSystemPrompt(ABC):
    """Abstract base class for system prompts.

    Each subclass encapsulates:
    - A system prompt template (with optional dynamic data injection)
    - A response parser that understands the output format defined by the prompt
    - A user prompt formatter

    Supports database-driven templates via PromptTemplate model.
    """

    # =========================================================================
    # Abstract Properties (subclasses must implement)
    # =========================================================================

    @property
    @abstractmethod
    def prompt_name(self) -> str:
        """Template name for database lookup.

        Should match a PromptTemplate.name value (e.g., 'react', 'skill_decision').
        """
        pass

    # =========================================================================
    # Properties (can be overridden by subclasses)
    # =========================================================================

    @property
    def user_template_mode(self) -> 'PromptTemplate.MessageMode':
        """Message construction mode.

        Default: GENERIC mode (messages structure: [system, *history, user])
        Subclasses like InterleavedThinking can override to use CUSTOM mode.
        """
        from ...chatbot.models.prompt_template import PromptTemplate
        return PromptTemplate.MessageMode.GENERIC

    # =========================================================================
    # Template Loading Hooks
    # =========================================================================

    def _get_db_template_sync(self) -> 'PromptTemplate | None':
        """Load template configuration from database (sync version).

        Respects the current tenant context (set by middleware/WebSocket
        consumer).  Falls back to global lookup when no tenant context
        is available.

        Returns:
            PromptTemplate instance if found and is_active=True, None otherwise.
        """
        try:
            from ...chatbot.models.prompt_template import PromptTemplate
            filters: dict = {'name': self.prompt_name, 'is_active': True}
            try:
                from apps.tenant.context import get_current_tenant_id
                tenant_id = get_current_tenant_id()
                if tenant_id:
                    filters['tenant_id'] = tenant_id
            except ImportError:
                pass
            return PromptTemplate.objects.filter(**filters).first()
        except Exception:
            return None

    async def _get_db_template_async(self) -> 'PromptTemplate | None':
        """Load template configuration from database (async version).

        Returns:
            PromptTemplate instance if found and is_active=True, None otherwise.
        """
        return await sync_to_async(self._get_db_template_sync, thread_sensitive=False)()

    def _get_db_template(self) -> 'PromptTemplate | None':
        """Load template configuration from database.

        Returns:
            PromptTemplate instance if found and is_active=True, None otherwise.
        """
        try:
            # Check if we're in an async context
            asyncio.get_running_loop()
            # We're in async context, but this is a sync method
            # Return None to avoid SynchronousOnlyOperation
            # The caller should use _get_db_template_async() instead
            return None
        except RuntimeError:
            # Not in async context, safe to use sync ORM
            return self._get_db_template_sync()

    def _get_active_layers(self) -> list:
        """Get active layers from the PromptTemplate's JSON field.

        Returns:
            List of active layer dicts ordered by target/order,
            or empty list if no template or no layers configured.
        """
        db_template = self._get_db_template()
        if db_template is None:
            return []
        try:
            layers = db_template.layers or []
            active = [l for l in layers if l.get('is_active', True)]
            return sorted(active, key=lambda l: (l.get('target', ''), l.get('order', 0)))
        except Exception:
            return []

    def _get_hardcoded_template(self) -> str:
        """Return the hardcoded template string.

        Subclasses must implement this to return their default template.
        """
        raise NotImplementedError("Subclasses must implement _get_hardcoded_template()")

    # =========================================================================
    # Template Rendering
    # =========================================================================

    def render(self, **kwargs) -> str:
        """Render the system prompt using Jinja2.

        Priority:
        1. ``db_template.system_template`` (implicit first system layer)
        2. System layers from ``db_template.layers`` (appended after)
        3. Hardcoded template fallback
        """
        db_template = self._get_db_template()
        if db_template:
            parts = []

            # 1. system_template is the implicit first system layer
            if db_template.system_template:
                try:
                    rendered = PromptTemplateEngine.render(
                        db_template.system_template, **kwargs
                    ).strip()
                    if rendered:
                        parts.append(rendered)
                except Exception as e:
                    logger.warning("Failed to render system_template: %s", e)

            # 2. Additional system layers from JSON field
            layers = db_template.layers or []
            system_layers = sorted(
                [l for l in layers
                 if l.get('target') == 'system' and l.get('is_active', True)],
                key=lambda l: l.get('order', 0),
            )
            for layer in system_layers:
                try:
                    rendered = PromptTemplateEngine.render(
                        layer['template'], **kwargs
                    ).strip()
                    if rendered:
                        parts.append(rendered)
                except Exception as e:
                    logger.warning(
                        "Failed to render system layer '%s': %s",
                        layer.get('name'), e,
                    )

            if parts:
                return '\n\n'.join(parts)

        # 3. Deprecated hardcoded fallback
        hardcoded = self._get_hardcoded_template()
        if hardcoded:
            return PromptTemplateEngine.render(hardcoded, **kwargs)
        raise RuntimeError(
            f"No system prompt configured for '{self.prompt_name}'. "
            f"Please create an active PromptTemplate with name='{self.prompt_name}' "
            f"and a non-empty system_template or layers."
        )

    # =========================================================================
    # Abstract Methods (subclasses must implement)
    # =========================================================================

    @abstractmethod
    def parse_response(self, response: str) -> Dict[str, Any]:
        """Parse an LLM response produced under this prompt's format.

        Returns:
            Dict with standard keys: 'thought', 'action', 'action_input', 'raw'.
        """

    @abstractmethod
    def format_user_prompt(self, query: str, **kwargs) -> str:
        """Format the user message content.

        Args:
            query: The user's query text.
            **kwargs: Additional context (history, knowledge, etc.)

        Returns:
            Formatted user prompt string.
        """

    def format_observation(self, observation: str) -> dict:
        """Format an observation into a message dict for the LLM.

        Default format: ``{'role': 'user', 'content': 'Observation: {observation}'}``.
        Subclasses may override for custom formats (e.g. ``<tool_ans>`` tags).
        """
        return {'role': 'user', 'content': f'Observation: {observation}'}

    def requires_skills(self) -> bool:
        """Whether this prompt needs a skill list injected via render().

        Default ``True`` — all prompts should have skills available.
        Subclasses that explicitly don't need skills can override to ``False``.
        """
        return True

    # =========================================================================
    # Extractor Configuration
    # =========================================================================

    default_extractor_config: dict = {
        'extractor': {
            'type': 'xml_tags',
            'default_type': 'think',
        },
        'mapper': {
            'tool_keys': ['tool_call'],
            'think_keys': ['think'],
            'answer_keys': ['answer'],
        }
    }

    def get_extractor_config(self) -> dict:
        """Get extractor configuration for this prompt.

        Priority:
        1. Database template's extractor_config (if exists and is_active)
        2. Subclass default_extractor_config property

        Returns:
            Dict with 'extractor' and 'mapper' keys.
        """
        db_template = self._get_db_template()
        if db_template and db_template.extractor_config:
            return db_template.extractor_config
        return self.default_extractor_config

    async def get_extractor_config_async(self) -> dict:
        """Get extractor configuration for this prompt (async version).

        Priority:
        1. Database template's extractor_config (if exists and is_active)
        2. Subclass default_extractor_config property

        Returns:
            Dict with 'extractor' and 'mapper' keys.
        """
        db_template = await self._get_db_template_async()
        if db_template and db_template.extractor_config:
            return db_template.extractor_config
        return self.default_extractor_config

    # =========================================================================
    # History Conversion
    # =========================================================================

    def history_to_prompt_format(self, generic_history: list[dict]) -> list[dict]:
        """Convert generic storage-format history to this prompt's format.

        The generic format uses standard OpenAI message roles (user,
        assistant with ``tool_calls``, tool).  Each prompt subclass may
        override this to transform the history into its specific format
        (e.g. converting ``role: tool`` messages to ``<tool_ans>`` tags).

        Default: return the history as-is (suitable for prompts that
        consume standard OpenAI message lists).
        """
        return list(generic_history) if generic_history else []

    def normalize_context_messages(self, working_messages: list[dict]) -> list[dict]:
        """Normalize runtime working messages to generic storage format.

        After the LLM loop completes, the accumulated messages may be in
        a prompt-specific format.  This method converts them back to the
        generic storage format for persistence in ``session_context``.

        Default: filter out system messages, return the rest as-is
        (suitable for native function_calling where messages are already
        in standard OpenAI format).
        """
        return [m for m in working_messages if m.get('role') != 'system']

    def _build_messages_with_layers(
        self,
        query: str,
        history: list[dict] | None = None,
        skills: list[dict] | None = None,
        tool_schemas: list[dict] | None = None,
        tool_ans: str | list | None = None,
        **kwargs,
    ) -> list[dict]:
        """Build messages using PromptTemplate.layers configuration.

        Layers are dicts read from the PromptTemplate's JSON field.
        System layers are concatenated into the system message.
        User layers are prepended to the user query on applicable turns.
        """
        layers = self._get_active_layers()

        # Separate by target
        system_layers = [l for l in layers if l.get('target') == 'system']
        user_layers = [l for l in layers if l.get('target') == 'user']

        render_kwargs = dict(
            query=query,
            history=history,
            skills=skills,
            tool_schemas=tool_schemas,
            tool_ans=tool_ans,
            **kwargs,
        )

        # 1. Build system message from system_template + system layers
        system_parts = []

        # 1a. system_template is the implicit first system layer
        db_template = self._get_db_template()
        if db_template and db_template.system_template:
            try:
                rendered = PromptTemplateEngine.render(
                    db_template.system_template, **render_kwargs
                ).strip()
                if rendered:
                    system_parts.append(rendered)
            except Exception as e:
                logger.warning("Failed to render system_template: %s", e)

        # 1b. Additional system layers from JSON field
        for layer in system_layers:
            strategy = layer.get('strategy', 'always')
            if strategy == 'always' or (strategy == 'first_turn' and not tool_ans):
                try:
                    rendered = PromptTemplateEngine.render(layer['template'], **render_kwargs).strip()
                    if rendered:
                        system_parts.append(rendered)
                except Exception as e:
                    logger.warning("Failed to render system layer '%s': %s", layer.get('name'), e)

        system_content = '\n\n'.join(system_parts)
        messages = [{'role': 'system', 'content': system_content}]

        # 2. Add history
        if history:
            messages.extend(history)

        # 3. Render user layer content
        #     Layer content must be rendered regardless of tool_ans so that
        #     first_turn injection into history works on every ReAct iteration.
        always_parts = []
        first_turn_parts = []

        for layer in user_layers:
            strategy = layer.get('strategy', 'always')
            try:
                rendered = PromptTemplateEngine.render(layer['template'], **render_kwargs).strip()
                if not rendered:
                    continue
            except Exception as e:
                logger.warning("Failed to render user layer '%s': %s", layer.get('name'), e)
                continue

            if strategy == 'always':
                always_parts.append(rendered)
            elif strategy == 'first_turn':
                first_turn_parts.append(rendered)

        # 3a. Inject first_turn layers into the first historical user message
        #     so the LLM sees user_context in the same position every turn.
        #     This MUST happen regardless of tool_ans, otherwise the first
        #     user message in history will lack its layer content on ReAct
        #     iterations after the first.
        if first_turn_parts and history:
            first_turn_content = '\n\n'.join(first_turn_parts)
            for i, msg in enumerate(messages):
                if msg.get('role') == 'user':
                    # Shallow copy to avoid mutating _generic_messages dicts
                    new_msg = dict(msg)
                    new_msg['content'] = first_turn_content + '\n\n' + msg['content']
                    messages[i] = new_msg
                    break

        # 3b. Build current user message (only on first ReAct turn)
        if not tool_ans:
            user_parts = list(always_parts)
            if first_turn_parts and not history:
                user_parts.extend(first_turn_parts)

            if user_parts:
                user_content = '\n\n'.join(user_parts) + '\n\n' + query
            else:
                user_content = query

            # Avoid duplicate user message (safety guard)
            if not history or history[-1].get('role') != 'user' or history[-1].get('content') != user_content:
                messages.append({'role': 'user', 'content': user_content})

        return messages

    def build_messages(
        self,
        query: str,
        history: list[dict] | None = None,
        skills: list[dict] | None = None,
        tool_schemas: list[dict] | None = None,
        tool_ans: str | list | None = None,
        **kwargs,
    ) -> list[dict]:
        """Build the complete LLM message list.

        Default implementation: ``[system, *history, user_prompt]``.
        Subclasses may override to change the message structure
        (e.g. embedding history/tools inside the user message content).
        """
        from ...chatbot.models.prompt_template import PromptTemplate

        # Layers only apply in GENERIC mode. CUSTOM mode subclasses manage
        # their own message structure, which is incompatible with the fixed
        # [system, *history, user] layout that layers produce.
        if self.user_template_mode == PromptTemplate.MessageMode.GENERIC and self._get_active_layers():
            return self._build_messages_with_layers(
                query=query,
                history=history,
                skills=skills,
                tool_schemas=tool_schemas,
                tool_ans=tool_ans,
                **kwargs,
            )

        # 1. Render system prompt
        system_content = self.render(
            query=query,
            history=history,
            skills=skills,
            tool_schemas=tool_schemas,
            tool_ans=tool_ans,
            **kwargs,
        )
        messages = [{'role': 'system', 'content': system_content}]

        # 2. Determine user message format based on user_template_mode
        if self.user_template_mode == PromptTemplate.MessageMode.GENERIC:
            # Generic mode: [system, *history, user]
            # The user message is always the raw query — no template wrapping.
            if history:
                messages.extend(history)
            if not tool_ans:
                if not history or history[-1].get('role') != 'user' or history[-1].get('content') != query:
                    messages.append({'role': 'user', 'content': query})
        else:
            # Custom mode: use user_template from DB or subclass fallback
            db_template = self._get_db_template()
            if db_template and db_template.user_template:
                user_content = PromptTemplateEngine.render(
                    db_template.user_template,
                    query=query,
                    history=history,
                    skills=skills,
                    tool_schemas=tool_schemas,
                    tool_ans=tool_ans,
                    **kwargs
                )
            else:
                # Fallback to subclass implementation
                user_content = self._render_custom_user_message(
                    query, history, skills, tool_schemas, tool_ans, **kwargs
                )
            messages.append({'role': 'user', 'content': user_content})

        return messages

    def _render_custom_user_message(
        self,
        query: str,
        history: list[dict] | None = None,
        skills: list[dict] | None = None,
        tool_schemas: list[dict] | None = None,
        tool_ans: str | list | None = None,
        **kwargs,
    ) -> str:
        """Render custom user message content.

        Default implementation uses format_user_prompt().
        Subclasses with custom message formats (like InterleavedThinking)
        can override this method.
        """
        return self.format_user_prompt(query, **kwargs)

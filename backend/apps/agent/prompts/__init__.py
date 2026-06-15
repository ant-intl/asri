"""
System prompt package.

Public API:
- BaseSystemPrompt — abstract base class
- DynamicPrompt — DB-driven prompt implementation
- create_prompt(mode) — factory function (sync)
- create_prompt_async(mode) — factory function (async)
- get_active_prompt_async(tenant_id) — get active prompt for tenant (async)
- PromptTemplateEngine — Jinja2 template rendering engine
"""
import logging
from typing import TYPE_CHECKING

from asgiref.sync import sync_to_async

from .base import BaseSystemPrompt
from .dynamic_prompt import DynamicPrompt
from .template_engine import PromptTemplateEngine

if TYPE_CHECKING:
    from ...chatbot.models.prompt_template import PromptTemplate

__all__ = [
    'BaseSystemPrompt',
    'DynamicPrompt',
    'PromptTemplateEngine',
    'create_prompt',
    'create_prompt_async',
    'get_active_prompt_async',
]


def _get_db_template_sync(mode: str) -> 'PromptTemplate | None':
    """Get full template from database (sync version).

    Respects the current tenant context (set by middleware/WebSocket
    consumer).  Falls back to global lookup when no tenant context
    is available.

    Args:
        mode: The prompt mode name to load.

    Returns:
        PromptTemplate instance if found and is active, None otherwise.
    """
    try:
        from ...chatbot.models.prompt_template import PromptTemplate
        filters: dict = {'name': mode, 'is_active': True}
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


def create_prompt(mode: str) -> BaseSystemPrompt:
    """Create a prompt instance by mode name.

    Loads the prompt configuration from the database. The PromptTemplate
    record must exist and be active (is_active=True).

    This function works in both sync and async contexts. In async contexts,
    it uses a thread pool to safely execute the database query.

    Args:
        mode: Prompt mode name. Must match a PromptTemplate.name in database.

    Returns:
        A DynamicPrompt instance configured from the database.

    Raises:
        ValueError: If no active PromptTemplate is found for the given mode.
    """
    db_template = None
    try:
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            in_async = loop is not None
        except RuntimeError:
            in_async = False

        if not in_async:
            db_template = _get_db_template_sync(mode)
    except Exception as e:
        logging.getLogger(__name__).debug(
            f"Database check skipped for prompt {mode!r}: {e}"
        )

    if db_template:
        return DynamicPrompt(mode, db_template=db_template)

    raise ValueError(
        f"Unknown prompt mode: {mode!r}. "
        f"Please create a PromptTemplate with name={mode!r} and is_active=True. "
        f"Note: If calling from async context, use create_prompt_async() instead."
    )


async def create_prompt_async(mode: str) -> BaseSystemPrompt:
    """Create a prompt instance by mode name (async version).

    Loads the prompt configuration from the database. The PromptTemplate
    record must exist and be active (is_active=True).

    Args:
        mode: Prompt mode name. Must match a PromptTemplate.name in database.

    Returns:
        A DynamicPrompt instance configured from the database.

    Raises:
        ValueError: If no active PromptTemplate is found for the given mode.
    """
    db_template = await sync_to_async(_get_db_template_sync, thread_sensitive=False)(mode)
    if db_template:
        return DynamicPrompt(mode, db_template=db_template)

    raise ValueError(
        f"Unknown prompt mode: {mode!r}. "
        f"Please create a PromptTemplate with name={mode!r} and is_active=True."
    )


async def get_active_prompt_async(tenant_id: str | None = None) -> BaseSystemPrompt:
    """Get the active PromptTemplate for the given tenant.

    Queries the database for ``is_active=True`` and filters by tenant_id.
    This is the replacement for the old ``REACT_PROMPT_MODE`` config lookup —
    instead of reading a mode name from config and then looking up the
    template, this function goes directly to the database.

    Args:
        tenant_id: Tenant ID.  Falls back to the current request context
            when ``None``.

    Returns:
        A :class:`DynamicPrompt` instance.

    Raises:
        ValueError: If no active PromptTemplate is found.
    """
    from ...chatbot.models.prompt_template import PromptTemplate

    filters: dict = {'is_active': True}
    if tenant_id:
        filters['tenant_id'] = tenant_id
    else:
        try:
            from apps.tenant.context import get_current_tenant_id
            tid = get_current_tenant_id()
            if tid:
                filters['tenant_id'] = tid
        except ImportError:
            pass

    db_template = await sync_to_async(
        PromptTemplate.objects.filter(**filters).first,
        thread_sensitive=False,
    )()
    if db_template is None:
        raise ValueError(
            "No active PromptTemplate found. "
            "Please create a PromptTemplate with is_active=True."
        )
    return DynamicPrompt(db_template.name, db_template=db_template)

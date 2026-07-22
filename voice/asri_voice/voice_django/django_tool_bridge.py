"""Bridge module: wraps Django async ``BaseTool.execute()`` into a sync
callable that Voice's ``ToolRegistry`` can invoke.

Voice's tool pipeline runs in threads and calls ``fn(**kwargs)``
synchronously.  Django tools are ``async def execute(input_text, context)``.
This bridge closes the gap with ``asyncio.run`` (or a thread-pool fallback
when an event-loop is already running).

Voice business tools are now defined as Django ``BaseTool`` subclasses
(see ``apps/integrations/tool/asri_voice_tool.py``).  The bridge reads
``hidden_fields`` and ``tool_policy`` from the Django tool instance and
passes them to Voice's ``ToolRegistry.register()`` so the execution layer
(cancel scope, policy, idempotency) can apply them.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = [
    "make_django_bridge_fn",
    "get_django_hidden_fields",
    "get_django_tool_policy",
]


def make_django_bridge_fn(tool_name: str, tenant_id: str) -> Callable[..., str]:
    """Return a sync callable that invokes a Django ``BaseTool``.

    The returned function accepts arbitrary keyword arguments (the tool
    parameters from the LLM, already enriched with hidden fields by the
    Voice ``ToolRegistry``), serialises them to JSON, and delegates to
    ``tool.execute(input_text, context)``.
    """

    def _bridge_fn(_tool_context: dict | None = None, **kwargs: Any) -> str:
        from apps.integrations.tool.base import ToolRegistry as DjangoToolRegistry

        django_registry = DjangoToolRegistry()
        tool = django_registry.get_tool(tool_name, tenant_id=tenant_id)
        if tool is None:
            return f"Error: Django tool '{tool_name}' not found"

        input_text = json.dumps(kwargs, ensure_ascii=False)
        context: dict[str, Any] = {"tenant_id": tenant_id}
        if _tool_context:
            context.update(_tool_context)

        try:
            return asyncio.run(tool.execute(input_text, context))
        except RuntimeError:
            # An event loop is already running (rare in Voice threads).
            # Fall back to a dedicated thread.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, tool.execute(input_text, context))
                return future.result(timeout=30)
        except Exception as exc:
            logger.exception("Django tool '%s' execution failed", tool_name)
            return f"Error executing tool '{tool_name}': {exc}"

    _bridge_fn.__name__ = f"django_bridge_{tool_name}"
    return _bridge_fn


def get_django_hidden_fields(tool_name: str, tenant_id: str) -> list[str]:
    """Return the ``hidden_fields`` declared by a Django ``BaseTool``."""
    try:
        from apps.integrations.tool.base import ToolRegistry as DjangoToolRegistry

        django_registry = DjangoToolRegistry()
        tool = django_registry.get_tool(tool_name, tenant_id=tenant_id)
        if tool is not None:
            return list(getattr(tool, "hidden_fields", []) or [])
    except Exception:
        logger.debug("Could not read hidden_fields for '%s'", tool_name, exc_info=True)
    return []


def get_django_tool_policy(tool_name: str, tenant_id: str):
    """Convert the Django ``tool_policy`` string to Voice's ``ToolPolicy``.

    Django ``BaseTool`` declares ``tool_policy: str`` ("read" / "write") and
    optional ``tool_allowed_sources: tuple[str, ...] | None``.  This function
    reads those attributes and returns the corresponding Voice ``ToolPolicy``
    instance.
    """
    from handlers.llm.tool_call.tool_execution import ToolPolicy

    try:
        from apps.integrations.tool.base import ToolRegistry as DjangoToolRegistry

        django_registry = DjangoToolRegistry()
        tool = django_registry.get_tool(tool_name, tenant_id=tenant_id)
        if tool is not None:
            policy_str = getattr(tool, "tool_policy", "read")
            sources = getattr(tool, "tool_allowed_sources", None)
            if policy_str == "write":
                if sources:
                    return ToolPolicy.write(allowed_sources=sources)
                return ToolPolicy.write()
            return ToolPolicy.read()
    except Exception:
        logger.debug("Could not read tool_policy for '%s'", tool_name, exc_info=True)
    return ToolPolicy.read()

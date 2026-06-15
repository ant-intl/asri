"""
RAG Registry - Factory for creating and registering RAG tools and providers.

External packages can register RAG providers via ``entry_points('asri.rag_providers')``.
"""
import logging
from typing import Optional

from .base import BaseRAGProvider

logger = logging.getLogger(__name__)


class RAGRegistry:
    """Registry for creating and registering RAG tools.

    Responsible for:
    1. Managing RAG provider classes (with entry_points discovery)
    2. Creating RAGSearchTool instances based on configuration
    3. Registering them to ToolRegistry
    """

    _provider_classes: dict[str, type[BaseRAGProvider]] = {}
    _plugins_discovered: bool = False

    @classmethod
    def register_provider(cls, name: str, provider_class: type[BaseRAGProvider]) -> None:
        """Register a RAG provider class."""
        cls._provider_classes[name] = provider_class
        logger.info(f"Registered RAG provider: {name}")

    @classmethod
    def discover_plugins(cls) -> None:
        """Auto-discover RAG providers via entry_points('asri.rag_providers')."""
        if cls._plugins_discovered:
            return
        cls._plugins_discovered = True
        try:
            from importlib.metadata import entry_points
            for ep in entry_points(group='asri.rag_providers'):
                try:
                    cls.register_provider(ep.name, ep.load())
                except Exception as e:
                    logger.warning(f"Failed to load RAG plugin '{ep.name}': {e}")
        except Exception as e:
            logger.debug(f"RAG entry_points discovery skipped: {e}")

    @classmethod
    def create_provider(
        cls,
        config: dict,
        tenant_id: Optional[str] = None,
    ) -> Optional[BaseRAGProvider]:
        """Create a RAG provider from config.

        Args:
            config: Tool configuration dict (may contain 'provider_type', 'rag_url', etc.)
            tenant_id: Tenant ID for isolation.

        Returns:
            Provider instance or None if no matching provider is registered.
        """
        cls.discover_plugins()

        provider_type = config.get('provider_type', '')
        if provider_type and provider_type in cls._provider_classes:
            provider_cls = cls._provider_classes[provider_type]
            return provider_cls(**config)

        # If only one provider is registered, use it as default
        if len(cls._provider_classes) == 1:
            provider_cls = next(iter(cls._provider_classes.values()))
            return provider_cls(**config)

        logger.warning("No RAG provider available. Install a RAG plugin package.")
        return None

    @classmethod
    def create_and_register_tools(
        cls, tenant_id: Optional[str], tool_name: str, config: dict
    ) -> int:
        """Create and register RAG tool based on configuration.

        Args:
            tenant_id: Tenant ID for isolation
            tool_name: Tool instance name from config (required, unique)
            config: Tool configuration dict with rag_url

        Returns:
            Number of tools registered (0 or 1)
        """
        from apps.integrations.tool.base import ToolRegistry

        if not config:
            logger.debug("No RAG config provided, skipping")
            return 0

        # Validate rag_url is present
        if not config.get('rag_url'):
            logger.warning(f"RAG config missing 'rag_url', skipping '{tool_name}'")
            return 0

        try:
            success = ToolRegistry.create_and_register(
                name='rag_search',
                tenant_id=tenant_id,
                config=config,
                instance_name=tool_name,
                class_type='rag_search',
            )
            if success:
                logger.info(f"Registered RAG tool: {tool_name}")
                return 1
            return 0
        except Exception as e:
            logger.error(f"Failed to register RAG tool '{tool_name}': {e}")
            return 0

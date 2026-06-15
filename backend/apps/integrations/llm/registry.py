"""
LLM Provider registry for managing provider instances.

Supports data-driven provider creation via ``config_keys`` and
plugin discovery via ``entry_points('asri.llm_providers')``.
"""
import logging
from typing import Dict, Optional, Type

from .base import BaseLLMProvider
from .openai_provider import OpenAIProvider
from .ollama_provider import OllamaProvider
from .asri_gateway_provider import AsriGatewayProvider

logger = logging.getLogger(__name__)


class LLMRegistry:
    """
    Registry for managing LLM provider instances.
    
    Provides factory methods to create and retrieve provider instances
    based on configuration.  Instances are cached per-tenant.

    New providers can be added by:
    1. Calling ``register_provider()`` at runtime.
    2. Publishing a package with ``entry_points(group='asri.llm_providers')``.
    """
    
    _provider_classes: Dict[str, Type[BaseLLMProvider]] = {
        'openai': OpenAIProvider,
        'ollama': OllamaProvider,
        'asri_gateway': AsriGatewayProvider,
    }
    
    # Tenant-scoped cache: {tenant_id: {cache_key: provider}}
    _instances: Dict[Optional[str], Dict[str, BaseLLMProvider]] = {}

    _plugins_discovered: bool = False
    
    @classmethod
    def register_provider(
        cls,
        provider_type: str,
        provider_class: Type[BaseLLMProvider]
    ) -> None:
        """Register a new provider type."""
        cls._provider_classes[provider_type] = provider_class
        logger.info(f"Registered LLM provider: {provider_type}")

    @classmethod
    def discover_plugins(cls) -> None:
        """Auto-discover LLM providers from installed packages via entry_points.

        Scans ``entry_points(group='asri.llm_providers')`` and registers
        each discovered provider class.  Safe to call multiple times.
        """
        if cls._plugins_discovered:
            return
        cls._plugins_discovered = True

        try:
            from importlib.metadata import entry_points
            eps = entry_points(group='asri.llm_providers')
            for ep in eps:
                try:
                    provider_class = ep.load()
                    cls.register_provider(ep.name, provider_class)
                    logger.info(f"Discovered LLM plugin: {ep.name}")
                except Exception as e:
                    logger.warning(f"Failed to load LLM plugin '{ep.name}': {e}")
        except Exception as e:
            logger.debug(f"entry_points discovery skipped: {e}")

    @classmethod
    def create_provider(
        cls,
        provider_type: str,
        **kwargs
    ) -> BaseLLMProvider:
        """
        Create a new provider instance.
        
        Args:
            provider_type: Type of provider ('openai', 'ollama', etc.)
            **kwargs: Provider-specific configuration
        
        Returns:
            Configured provider instance
        """
        provider_class = cls._provider_classes.get(provider_type)
        
        if not provider_class:
            raise ValueError(f"Unknown provider type: {provider_type}")
        
        return provider_class(**kwargs)
    
    def get_provider(
        self,
        provider_type: str,
        name: str = None,
        **kwargs
    ) -> BaseLLMProvider:
        """
        Get or create a provider instance.
        
        Args:
            provider_type: Type of provider
            name: Optional name for caching
            **kwargs: Provider configuration
        
        Returns:
            Provider instance
        """
        from ...tenant.context import get_current_tenant_id

        tenant_id = get_current_tenant_id()
        cache_key = name or f"{provider_type}_default"

        tenant_cache = self._instances.setdefault(tenant_id, {})

        if cache_key not in tenant_cache:
            tenant_cache[cache_key] = self.create_provider(
                provider_type,
                **kwargs
            )
        
        return tenant_cache[cache_key]

    @classmethod
    async def get_provider_from_config(
        cls,
        tenant_id: str = None
    ) -> BaseLLMProvider:
        """Get provider from LLMProviderConfig table or tenant config snapshot.

        Priority:
        1. LLMProviderConfig table (default provider for tenant)
        2. DB-based config (TenantRegistry): chatbot_tenant table

        Args:
            tenant_id: Tenant ID for tenant-specific config

        Returns:
            Provider instance configured from tenant config

        Raises:
            ValueError: If no provider config found for the tenant
        """
        from ...tenant.context import get_current_tenant_id

        if not tenant_id:
            tenant_id = get_current_tenant_id()

        logger.info(f"get_provider_from_config called with tenant_id={tenant_id}")

        cache_key = f"{tenant_id}:model_config"

        tenant_cache = cls._instances.setdefault(tenant_id, {})

        # 1. Try LLMProviderConfig table first (default provider)
        model_data = await cls._load_from_llm_provider_config_async(tenant_id)
        logger.info(f"LLMProviderConfig data: {model_data}")

        # 2. If not found, fallback to DB config (TenantRegistry)
        if not model_data:
            from ...tenant.registry import get_tenant_registry
            registry = get_tenant_registry()
            model_data = registry.get_model_config(tenant_id)
            logger.info(f"TenantRegistry config data: {model_data}")

        if not model_data:
            raise ValueError("未配置 LLM Provider，请在 Admin 页面 /admin/ 中配置")

        # Create provider from config
        provider = cls._create_from_config(model_data)
        tenant_cache[cache_key] = provider
        return provider

    @classmethod
    async def get_provider_for_purpose(
        cls,
        purpose: str = 'copilot',
        tenant_id: str = None
    ) -> BaseLLMProvider:
        """Get provider for specific purpose (copilot/chatbot) from LLMProviderConfig table.

        Args:
            purpose: Model purpose ('copilot' or 'chatbot')
            tenant_id: Tenant ID for tenant-specific config

        Returns:
            Provider instance configured for the specified purpose

        Raises:
            ValueError: If no model config found for the specified purpose
        """
        from ...tenant.context import get_current_tenant_id

        if not tenant_id:
            tenant_id = get_current_tenant_id()

        logger.info(f"get_provider_for_purpose called with purpose={purpose}, tenant_id={tenant_id}")

        cache_key = f"{tenant_id}:purpose_{purpose}"

        # Check cache
        tenant_cache = cls._instances.setdefault(tenant_id, {})
        if cache_key in tenant_cache:
            logger.info(f"Returning cached provider for {cache_key}")
            return tenant_cache[cache_key]

        # Load from LLMProviderConfig table with purpose filter
        model_data = await cls._load_from_llm_provider_config_for_purpose_async(tenant_id, purpose)
        logger.info(f"LLMProviderConfig for purpose '{purpose}': {model_data}")

        if not model_data:
            raise ValueError("未配置 LLM Provider，请在 Admin 页面 /admin/ 中配置")

        # Create provider from config
        provider = cls._create_from_config(model_data)
        tenant_cache[cache_key] = provider
        logger.info(f"Created and cached provider for purpose '{purpose}'")
        return provider

    @classmethod
    async def _load_from_llm_provider_config_for_purpose_async(cls, tenant_id: str, purpose: str) -> dict:
        """Async version: Load provider config from LLMProviderConfig table filtered by purpose."""
        try:
            from asgiref.sync import sync_to_async
            from ...entities import LLMProviderConfig

            @sync_to_async(thread_sensitive=False)
            def _do_query():
                return LLMProviderConfig.objects.filter(
                    tenant_id=tenant_id,
                    is_active=True,
                    purpose=purpose,
                ).first()

            provider_config = await _do_query()

            if not provider_config:
                logger.debug(f"No LLMProviderConfig found for tenant {tenant_id} with purpose {purpose}")
                return {}

            logger.info(
                f"Loaded LLMProviderConfig for tenant {tenant_id}, purpose {purpose}: "
                f"{provider_config.name} ({provider_config.provider_type})"
            )

            return {
                'provider_type': provider_config.provider_type,
                'api_base': provider_config.api_base,
                'api_key': provider_config.api_key_encrypted,
                'model_name': provider_config.model_name,
                'config': provider_config.config_json or {},
            }
        except Exception as e:
            logger.warning(f"Failed to load LLMProviderConfig for purpose {purpose}: {e}")
            return {}

    @classmethod
    async def _load_from_llm_provider_config_async(cls, tenant_id: str) -> dict:
        """Async version: Load default provider config from LLMProviderConfig table."""
        try:
            from asgiref.sync import sync_to_async
            from ...entities import LLMProviderConfig

            @sync_to_async(thread_sensitive=False)
            def _do_query():
                return LLMProviderConfig.objects.filter(
                    tenant_id=tenant_id,
                    is_active=True,
                    is_default=True,
                ).first()

            provider_config = await _do_query()

            if not provider_config:
                logger.debug(f"No default LLMProviderConfig found for tenant {tenant_id}")
                return {}

            logger.info(
                f"Loaded LLMProviderConfig for tenant {tenant_id}: "
                f"{provider_config.name} ({provider_config.provider_type})"
            )

            return {
                'provider_type': provider_config.provider_type,
                'api_base': provider_config.api_base,
                'api_key': provider_config.api_key_encrypted,
                'model_name': provider_config.model_name,
                'config': provider_config.config_json or {},
            }
        except Exception as e:
            logger.warning(f"Failed to load LLMProviderConfig: {e}")
            return {}

    @classmethod
    def _load_from_llm_provider_config(cls, tenant_id: str) -> dict:
        """Load default provider config from LLMProviderConfig table."""
        try:
            import asyncio
            from ...entities import LLMProviderConfig

            try:
                asyncio.get_running_loop()
                is_async = True
            except RuntimeError:
                is_async = False

            def _do_query():
                return LLMProviderConfig.objects.filter(
                    tenant_id=tenant_id,
                    is_active=True,
                    is_default=True,
                ).first()

            if is_async:
                from asgiref.sync import sync_to_async
                provider_config = asyncio.get_event_loop().run_until_complete(
                    sync_to_async(_do_query)()
                )
            else:
                provider_config = _do_query()

            if not provider_config:
                logger.debug(f"No default LLMProviderConfig found for tenant {tenant_id}")
                return {}

            logger.info(
                f"Loaded LLMProviderConfig for tenant {tenant_id}: "
                f"{provider_config.name} ({provider_config.provider_type})"
            )

            return {
                'provider_type': provider_config.provider_type,
                'api_base': provider_config.api_base,
                'api_key': provider_config.api_key_encrypted,
                'model_name': provider_config.model_name,
                'config': provider_config.config_json or {},
            }
        except Exception as e:
            logger.warning(f"Failed to load LLMProviderConfig: {e}")
            return {}

    @classmethod
    def _create_from_config(cls, config: dict) -> BaseLLMProvider:
        """Create provider from config dict - unified factory logic.

        Args:
            config: Model configuration dict with keys:
                - provider_type, model_name, api_base, api_key, config

        Returns:
            Configured provider instance
        """
        provider_type = config.get('provider_type')
        provider_cls = cls._provider_classes.get(provider_type)

        if not provider_cls:
            raise ValueError(f"Unknown provider: {provider_type}")

        return provider_cls(
            api_base=config.get('api_base', ''),
            api_key=config.get('api_key', ''),
            model_name=config.get('model_name', ''),
            **(config.get('config', {}) or {})
        )

    def clear_cache(self) -> None:
        """Clear all cached provider instances."""
        self._instances.clear()

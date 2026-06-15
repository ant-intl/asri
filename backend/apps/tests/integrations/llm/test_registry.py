"""
Tests for LLMRegistry implementation.
"""
import pytest
from unittest.mock import patch, MagicMock

from apps.integrations.llm.registry import LLMRegistry
from apps.integrations.llm.openai_provider import OpenAIProvider
from apps.integrations.llm.ollama_provider import OllamaProvider
from apps.integrations.llm.base import BaseLLMProvider


class TestLLMRegistryCreateProvider:
    """Test LLMRegistry.create_provider() method."""

    def test_create_openai_provider(self):
        """Test creating an OpenAI provider."""
        provider = LLMRegistry.create_provider(
            'openai',
            api_base='https://api.openai.com/v1',
            api_key='test-key',
            model_name='gpt-4'
        )

        assert isinstance(provider, OpenAIProvider)
        assert provider.api_key == 'test-key'
        assert provider.model_name == 'gpt-4'

    def test_create_ollama_provider(self):
        """Test creating an Ollama provider."""
        provider = LLMRegistry.create_provider(
            'ollama',
            api_base='http://localhost:11434',
            model_name='llama2'
        )

        assert isinstance(provider, OllamaProvider)
        assert provider.api_base == 'http://localhost:11434'
        assert provider.model_name == 'llama2'

    def test_create_unknown_type_raises(self):
        """Test that unknown provider type raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            LLMRegistry.create_provider('unknown')

        assert 'Unknown provider type' in str(exc_info.value)
        assert 'unknown' in str(exc_info.value)

    def test_create_provider_passes_kwargs(self):
        """Test that extra kwargs are passed to provider."""
        provider = LLMRegistry.create_provider(
            'openai',
            api_key='test',
            timeout=60,
            custom_param='value'
        )

        assert provider.timeout == 60
        assert provider.config.get('custom_param') == 'value'


class TestLLMRegistryRegisterProvider:
    """Test LLMRegistry.register_provider() method."""

    def test_register_new_provider(self):
        """Test registering a new provider type."""
        class TestProvider(BaseLLMProvider):
            async def chat(self, messages, **kwargs):
                return {}

            async def embed(self, text):
                return []

            def get_provider_type(self):
                return 'test'

        # Register the provider
        LLMRegistry.register_provider('test_provider', TestProvider)

        # Create an instance
        provider = LLMRegistry.create_provider('test_provider')

        assert isinstance(provider, TestProvider)
        assert provider.get_provider_type() == 'test'

        # Cleanup: remove the registered provider
        del LLMRegistry._provider_classes['test_provider']

    def test_register_overwrites_existing(self):
        """Test that registering with existing key overwrites."""
        class NewOpenAI(BaseLLMProvider):
            async def chat(self, messages, **kwargs):
                return {'content': 'new'}

            async def embed(self, text):
                return []

            def get_provider_type(self):
                return 'new-openai'

        original_class = LLMRegistry._provider_classes['openai']

        try:
            LLMRegistry.register_provider('openai', NewOpenAI)
            provider = LLMRegistry.create_provider('openai')
            assert isinstance(provider, NewOpenAI)
        finally:
            # Restore original
            LLMRegistry._provider_classes['openai'] = original_class


class TestLLMRegistryGetProvider:
    """Test LLMRegistry.get_provider() method."""

    def test_get_provider_creates_instance(self):
        """Test that get_provider creates a new instance."""
        registry = LLMRegistry()
        provider = registry.get_provider(
            'openai',
            api_key='test-key'
        )

        assert isinstance(provider, OpenAIProvider)

    def test_get_provider_caches_instance(self):
        """Test that get_provider caches instances by name."""
        registry = LLMRegistry()

        provider1 = registry.get_provider('openai', name='my-openai', api_key='key1')
        provider2 = registry.get_provider('openai', name='my-openai', api_key='key2')

        # Should return the same cached instance
        assert provider1 is provider2
        assert provider1.api_key == 'key1'  # Original key, not updated

    def test_get_provider_different_names_different_instances(self):
        """Test that different names create different instances."""
        registry = LLMRegistry()

        provider1 = registry.get_provider('openai', name='openai-1', api_key='key1')
        provider2 = registry.get_provider('openai', name='openai-2', api_key='key2')

        assert provider1 is not provider2
        assert provider1.api_key == 'key1'
        assert provider2.api_key == 'key2'

    def test_get_provider_default_cache_key(self):
        """Test that get_provider uses default cache key when name not specified."""
        registry = LLMRegistry()

        provider1 = registry.get_provider('openai', api_key='key1')
        provider2 = registry.get_provider('openai', api_key='key2')

        # Both use 'openai_default' as cache key
        assert provider1 is provider2


class TestLLMRegistryClearCache:
    """Test LLMRegistry.clear_cache() method."""

    def test_clear_cache_removes_instances(self):
        """Test that clear_cache removes all cached instances."""
        registry = LLMRegistry()

        # Create some providers
        registry.get_provider('openai', name='test1')
        registry.get_provider('ollama', name='test2')

        # With tenant-scoped cache, instances are nested under tenant key
        tenant_cache = registry._instances.get(None, {})
        assert len(tenant_cache) >= 2

        # Clear cache
        registry.clear_cache()

        assert len(registry._instances) == 0

    def test_clear_cache_allows_recreating(self):
        """Test that after clear_cache, new instances can be created."""
        registry = LLMRegistry()

        provider1 = registry.get_provider('openai', name='test', api_key='old-key')
        registry.clear_cache()
        provider2 = registry.get_provider('openai', name='test', api_key='new-key')

        assert provider1 is not provider2
        assert provider1.api_key == 'old-key'
        assert provider2.api_key == 'new-key'


class TestLLMRegistryProviderClasses:
    """Test LLMRegistry provider class registration."""

    def test_all_providers_registered(self):
        """Test that all expected providers are registered."""
        expected = {'openai', 'ollama', 'asri_gateway'}
        registered = set(LLMRegistry._provider_classes.keys())

        assert expected.issubset(registered)

    def test_provider_classes_are_valid(self):
        """Test that all registered classes are BaseLLMProvider subclasses."""
        for name, cls in LLMRegistry._provider_classes.items():
            assert issubclass(cls, BaseLLMProvider), f"{name} is not a BaseLLMProvider subclass"




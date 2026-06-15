"""
Tests for BaseLLMProvider abstract class constraints.
"""
import pytest
from abc import ABC

from apps.integrations.llm.base import BaseLLMProvider


class TestBaseLLMProviderAbstraction:
    """Test that BaseLLMProvider enforces abstract method implementation."""

    def test_cannot_instantiate_base_class(self):
        """Test that BaseLLMProvider cannot be directly instantiated."""
        with pytest.raises(TypeError) as exc_info:
            BaseLLMProvider()
        assert "abstract" in str(exc_info.value).lower() or "instantiate" in str(exc_info.value).lower()

    def test_is_abstract_class(self):
        """Test that BaseLLMProvider is an ABC."""
        assert issubclass(BaseLLMProvider, ABC)

    def test_subclass_without_chat_raises(self):
        """Test that subclass without chat() implementation raises TypeError."""
        class IncompleteProvider(BaseLLMProvider):
            async def embed(self, text: str):
                return []

            def get_provider_type(self) -> str:
                return 'incomplete'

        with pytest.raises(TypeError):
            IncompleteProvider()

    def test_subclass_without_embed_raises(self):
        """Test that subclass without embed() implementation raises TypeError."""
        class IncompleteProvider(BaseLLMProvider):
            async def chat(self, messages, temperature=0.7, max_tokens=None, stream=False, **kwargs):
                return {}

            def get_provider_type(self) -> str:
                return 'incomplete'

        with pytest.raises(TypeError):
            IncompleteProvider()

    def test_subclass_without_get_provider_type_raises(self):
        """Test that subclass without get_provider_type() implementation raises TypeError."""
        class IncompleteProvider(BaseLLMProvider):
            async def chat(self, messages, temperature=0.7, max_tokens=None, stream=False, **kwargs):
                return {}

            async def embed(self, text: str):
                return []

        with pytest.raises(TypeError):
            IncompleteProvider()


class TestBaseLLMProviderDefaultMethods:
    """Test default method implementations in BaseLLMProvider."""

    @pytest.fixture
    def complete_provider(self):
        """Create a minimal complete provider for testing default methods."""
        class MinimalProvider(BaseLLMProvider):
            async def chat(self, messages, temperature=0.7, max_tokens=None, stream=False, **kwargs):
                return {'content': 'test'}

            async def embed(self, text: str):
                return [0.1, 0.2, 0.3]

            def get_provider_type(self) -> str:
                return 'minimal'

        return MinimalProvider(
            api_base='https://api.example.com',
            api_key='test-key',
            model_name='test-model'
        )

    def test_get_model_name(self, complete_provider):
        """Test get_model_name() returns the model name."""
        assert complete_provider.get_model_name() == 'test-model'

    def test_format_messages_default_passthrough(self, complete_provider):
        """Test format_messages() returns messages unchanged by default."""
        messages = [
            {'role': 'system', 'content': 'You are helpful.'},
            {'role': 'user', 'content': 'Hello!'}
        ]
        formatted = complete_provider.format_messages(messages)
        assert formatted == messages
        assert formatted is messages  # Same object reference

    def test_format_messages_empty_list(self, complete_provider):
        """Test format_messages() handles empty list."""
        messages = []
        formatted = complete_provider.format_messages(messages)
        assert formatted == []

    def test_initialization_stores_config(self):
        """Test that extra kwargs are stored in config dict."""
        class MinimalProvider(BaseLLMProvider):
            async def chat(self, messages, **kwargs):
                return {}

            async def embed(self, text: str):
                return []

            def get_provider_type(self) -> str:
                return 'minimal'

        provider = MinimalProvider(
            api_base='https://api.example.com',
            api_key='test-key',
            model_name='test-model',
            timeout=60,
            custom_option='value'
        )
        assert provider.config == {'timeout': 60, 'custom_option': 'value'}

    def test_initialization_stores_base_attributes(self):
        """Test that base attributes are properly stored."""
        class MinimalProvider(BaseLLMProvider):
            async def chat(self, messages, **kwargs):
                return {}

            async def embed(self, text: str):
                return []

            def get_provider_type(self) -> str:
                return 'minimal'

        provider = MinimalProvider(
            api_base='https://api.example.com',
            api_key='secret-key',
            model_name='gpt-4'
        )
        assert provider.api_base == 'https://api.example.com'
        assert provider.api_key == 'secret-key'
        assert provider.model_name == 'gpt-4'

    def test_initialization_default_values(self):
        """Test that default values are empty strings."""
        class MinimalProvider(BaseLLMProvider):
            async def chat(self, messages, **kwargs):
                return {}

            async def embed(self, text: str):
                return []

            def get_provider_type(self) -> str:
                return 'minimal'

        provider = MinimalProvider()
        assert provider.api_base == ''
        assert provider.api_key == ''
        assert provider.model_name == ''
        assert provider.config == {}

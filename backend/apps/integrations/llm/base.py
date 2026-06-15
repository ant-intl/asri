"""
Base LLM Provider abstract class.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, AsyncGenerator, Optional


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    All LLM providers (OpenAI, Ollama, etc.) must inherit from this class
    and implement the required methods.

    Subclasses should declare ``config_keys`` to enable data-driven
    instantiation from tenant settings, e.g.::

        config_keys = {
            'api_base': 'OPENAI_API_BASE',
            'api_key': 'OPENAI_API_KEY',
            'model_name': 'OPENAI_MODEL',
        }
    """

    # Mapping: constructor param name -> settings key name.
    # Override in subclasses to enable config-driven creation.
    config_keys: Dict[str, str] = {}

    # Keys consumed internally by providers and NOT forwarded to the upstream API payload.
    # Subclasses may override to customize filtering.
    _INTERNAL_CONFIG_KEYS: frozenset = frozenset({
        'auto_tools',
        'timeout',
        'enable_cache_control',
        'agent_context',
    })
    
    def __init__(
        self,
        api_base: str = '',
        api_key: str = '',
        model_name: str = '',
        **kwargs
    ):
        self.api_base = api_base
        self.api_key = api_key
        self.model_name = model_name
        self.config = kwargs
        self.auto_tools: bool = bool(kwargs.get('auto_tools', False))

    @property
    def extra_body(self) -> dict:
        """Return custom config parameters that should be forwarded to the upstream API payload.

        All config items not listed in ``_INTERNAL_CONFIG_KEYS`` are treated as
        API-level parameters and will be merged into the request body by each
        provider's ``chat()`` / ``_stream_chat()`` method.

        Subclasses may override ``_INTERNAL_CONFIG_KEYS`` to customise filtering.
        """
        return {
            k: v for k, v in self.config.items()
            if k not in self._INTERNAL_CONFIG_KEYS
        }

    @abstractmethod
    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any] | AsyncGenerator[str, None]:
        """
        Send a chat request to the LLM.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response
            **kwargs: Additional provider-specific parameters
        
        Returns:
            If stream=False: Dict with 'content', 'usage', etc.
            If stream=True: AsyncGenerator yielding content chunks
        """
        pass
    
    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """
        Generate embeddings for the given text.
        
        Args:
            text: Text to embed
        
        Returns:
            List of floats representing the embedding vector
        """
        pass
    
    @abstractmethod
    def get_provider_type(self) -> str:
        """
        Return the provider type identifier.
        
        Returns:
            String identifier (e.g., 'openai', 'ollama', 'cockpit')
        """
        pass
    
    def get_model_name(self) -> str:
        """Return the model name."""
        return self.model_name
    
    def format_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """
        Format messages for the provider (can be overridden).
        
        Args:
            messages: List of message dicts
        
        Returns:
            Formatted messages
        """
        return messages

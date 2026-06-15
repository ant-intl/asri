"""
Ollama LLM Provider implementation.
"""
import json
import logging
from typing import List, Dict, Any, AsyncGenerator, Optional

import httpx

from .base import BaseLLMProvider
from .response_parser import OllamaStructureParser

logger = logging.getLogger(__name__)


class OllamaProvider(BaseLLMProvider):
    """
    Ollama local LLM provider implementation.

    Connects to a locally running Ollama server.
    """

    config_keys = {
        'api_base': 'OLLAMA_API_BASE',
        'model_name': 'OLLAMA_MODEL',
    }

    def __init__(
        self,
        api_base: str = 'http://localhost:11434',
        api_key: str = '',
        model_name: str = 'llama2',
        **kwargs
    ):
        super().__init__(api_base, api_key, model_name, **kwargs)
        self.timeout = kwargs.get('timeout', 60)
        self.structure_parser = OllamaStructureParser()
        self.content_parser = None  # Reserved for Layer 2

    def get_provider_type(self) -> str:
        return 'ollama'

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any] | AsyncGenerator[str, None]:
        """Send chat request to Ollama API."""

        if stream:
            return self._stream_chat(messages, temperature, max_tokens, **kwargs)

        payload = {
            'model': self.model_name,
            'messages': self.format_messages(messages),
            'stream': False,
            'options': {
                'temperature': temperature,
            }
        }

        if max_tokens:
            payload['options']['num_predict'] = max_tokens

        # Forward extra custom parameters from config to upstream API payload
        payload.update(self.extra_body)

        logger.debug(f"Ollama chat request payload: {json.dumps(payload, ensure_ascii=False)}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f'{self.api_base}/api/chat',
                json=payload
            )
            response.raise_for_status()
            data = response.json()

        logger.debug(f"Ollama chat response: {json.dumps(data, ensure_ascii=False)}")
        result = self.structure_parser.parse_response(data)
        result['model'] = result['model'] or self.model_name
        return result

    async def _stream_chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream chat response from Ollama API."""
        cancel_event = kwargs.get('cancel_event')

        payload = {
            'model': self.model_name,
            'messages': self.format_messages(messages),
            'stream': True,
            'options': {
                'temperature': temperature,
            }
        }

        if max_tokens:
            payload['options']['num_predict'] = max_tokens

        # Forward extra custom parameters from config to upstream API payload
        payload.update(self.extra_body)

        logger.debug(f"Ollama stream request payload: {json.dumps(payload, ensure_ascii=False)}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                'POST',
                f'{self.api_base}/api/chat',
                json=payload
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    # Check for cancel signal
                    if cancel_event and cancel_event.is_set():
                        logger.info("Ollama stream cancelled")
                        yield {'type': 'done', 'content': ''}
                        break

                    if line:
                        try:
                            data = json.loads(line)
                            if data.get('done'):
                                yield {'type': 'done', 'content': ''}
                                break
                            parsed = self.structure_parser.parse_stream_chunk(data)
                            if parsed:
                                yield parsed
                        except Exception as e:
                            logger.warning(f"Error parsing stream chunk: {e}")

    async def embed(self, text: str) -> List[float]:
        """Generate embeddings using Ollama API."""

        payload = {
            'model': self.model_name,
            'prompt': text,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f'{self.api_base}/api/embeddings',
                json=payload
            )
            response.raise_for_status()
            data = response.json()

        return data['embedding']

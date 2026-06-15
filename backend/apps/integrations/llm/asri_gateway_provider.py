"""
AsriGateway Provider implementation.

Multi-model gateway that routes requests to various LLM providers.
Extends OpenAI-compatible API format with additional agent_context parameter.
"""
import logging
import json
from typing import List, Dict, Any, AsyncGenerator, Optional

import httpx

from .base import BaseLLMProvider
from .response_parser import QwenStructureParser, OpenAIStructureParser

logger = logging.getLogger(__name__)


class AsriGatewayProvider(BaseLLMProvider):
    """
    AsriGateway multi-model provider implementation.

    Routes requests to various LLM providers via a unified gateway API.
    Uses OpenAI-compatible API format with additional agent_context parameter.
    Uses QwenStructureParser for QWEN models, OpenAIStructureParser for others.
    """

    config_keys = {
        'api_base': 'ASRI_GATEWAY_API_BASE',
        'api_key': 'ASRI_GATEWAY_API_KEY',
        'model_name': 'ASRI_GATEWAY_MODEL',
    }

    def __init__(
        self,
        api_base: str = '',
        api_key: str = '',
        model_name: str = '',
        **kwargs
    ):
        super().__init__(api_base, api_key, model_name, **kwargs)
        self.timeout = kwargs.get('timeout', 60)

        # Store agent_context for request payload
        self.agent_context = kwargs.get('agent_context', {})

        # Select parser based on model name
        if 'QWEN' in model_name.upper():
            self.structure_parser = QwenStructureParser()
        else:
            self.structure_parser = OpenAIStructureParser()

        self.content_parser = None  # Reserved for Layer 2

    def get_provider_type(self) -> str:
        return 'asri_gateway'

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str | Dict] = 'auto',
        **kwargs
    ) -> Dict[str, Any] | AsyncGenerator:
        """Send chat request to AsriGateway API."""

        if stream:
            return self._stream_chat(
                messages, temperature, max_tokens, tools, tool_choice, **kwargs
            )

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        # Get agent_context from kwargs (dynamic) or self.config (default)
        agent_context = kwargs.get('agent_context', self.agent_context)

        payload = {
            'model': self.model_name,
            'messages': self.format_messages(messages),
            'temperature': temperature,
            'stream': False,
            'agent_context': agent_context,
        }

        if max_tokens:
            payload['max_tokens'] = max_tokens

        # Support tool calls (Function Calling)
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = tool_choice

        # Forward extra custom parameters from config to upstream API
        payload.update(self.extra_body)

        logger.debug(
            f"AsriGateway chat request payload: {json.dumps(payload, ensure_ascii=False)}"
        )

        url = self._build_url()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()

        logger.debug(f"AsriGateway chat response: {json.dumps(data, ensure_ascii=False)}")
        result = self.structure_parser.parse_response(data)
        result['model'] = result['model'] or self.model_name
        return result

    async def _stream_chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict]] = None,
        tool_choice: Optional[str | Dict] = 'auto',
        **kwargs
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream chat response from AsriGateway API."""
        cancel_event = kwargs.get('cancel_event')

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        # Get agent_context from kwargs (dynamic) or self.config (default)
        agent_context = kwargs.get('agent_context', self.agent_context)

        payload = {
            'model': self.model_name,
            'messages': self.format_messages(messages),
            'temperature': temperature,
            'max_tokens': max_tokens or 1000,
            'stream': True,
            'agent_context': agent_context,
        }

        # Support tool calls
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = tool_choice

        # Forward extra custom parameters from config to upstream API
        payload.update(self.extra_body)

        logger.debug(
            f"AsriGateway stream request payload: {json.dumps(payload, ensure_ascii=False)}"
        )

        url = self._build_url()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                'POST',
                url,
                headers=headers,
                json=payload
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    # Check for cancel signal
                    if cancel_event and cancel_event.is_set():
                        logger.info("AsriGateway stream cancelled")
                        yield {'type': 'done', 'content': ''}
                        break

                    if not line:
                        continue

                    if line == "data: [DONE]":
                        yield {'type': 'done', 'content': ''}
                        continue

                    if line.startswith('data:'):
                        try:
                            data_str = line[5:].strip()
                            chunk_data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        parsed = self.structure_parser.parse_stream_chunk(chunk_data)
                        if parsed is None:
                            continue

                        yield parsed

    async def embed(self, text: str) -> List[float]:
        """AsriGateway does not support embeddings."""
        raise NotImplementedError("AsriGateway does not support embeddings")

    def _build_url(self) -> str:
        """Build API URL ensuring proper format with /v1 suffix."""
        base = self.api_base.rstrip('/')
        # Ensure ends with /v1
        if not base.endswith('/v1'):
            base = f"{base}/v1"
        return f"{base}/chat/completions"

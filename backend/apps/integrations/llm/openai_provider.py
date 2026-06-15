"""
OpenAI LLM Provider implementation.
"""
import json
import logging
from typing import List, Dict, Any, AsyncGenerator, Optional

import httpx

from .base import BaseLLMProvider
from .response_parser import OpenAIStructureParser

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI API provider implementation.

    Supports both OpenAI and OpenAI-compatible APIs.
    """

    config_keys = {
        'api_base': 'OPENAI_API_BASE',
        'api_key': 'OPENAI_API_KEY',
        'model_name': 'OPENAI_MODEL',
    }

    def __init__(
        self,
        api_base: str = 'https://api.openai.com/v1',
        api_key: str = '',
        model_name: str = 'gpt-4',
        **kwargs
    ):
        super().__init__(api_base, api_key, model_name, **kwargs)
        self.timeout = kwargs.get('timeout', 60)
        self.structure_parser = OpenAIStructureParser()
        self.content_parser = None  # Reserved for Layer 2

    def get_provider_type(self) -> str:
        return 'openai'

    def format_messages(self, messages: list[dict]) -> list[dict]:
        """为 system 消息添加 cache_control 标记（如果启用）。

        当 enable_cache_control=True 时，在 system 消息上添加
        ``cache_control: {"type": "ephemeral"}`` 标记，以启用
        OpenAI API 级别的提示缓存。

        Args:
            messages: 原始消息列表。

        Returns:
            格式化后的消息列表。
        """
        if not self.config.get('enable_cache_control'):
            return messages

        formatted = []
        for msg in messages:
            entry = dict(msg)
            if msg.get('role') == 'system':
                entry['cache_control'] = {"type": "ephemeral"}
            formatted.append(entry)
        return formatted

    async def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> Dict[str, Any] | AsyncGenerator[str, None]:
        """Send chat request to OpenAI API."""

        if stream:
            return self._stream_chat(messages, temperature, max_tokens, **kwargs)

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        payload = {
            'model': self.model_name,
            'messages': self.format_messages(messages),
            'temperature': temperature,
            'stream': False,
        }

        if max_tokens:
            payload['max_tokens'] = max_tokens

        tools = kwargs.get('tools')
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = kwargs.get('tool_choice', 'auto')

        # Forward extra custom parameters from config to upstream API
        payload.update(self.extra_body)

        logger.debug(
            "OpenAI chat request: model=%s, messages=%d, tools=%s",
            self.model_name,
            len(payload.get('messages', [])),
            bool(payload.get('tools')),
        )

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f'{self.api_base}/chat/completions',
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()

        logger.debug("OpenAI chat response received: model=%s", data.get('model'))
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
        """Stream chat response from OpenAI API."""
        cancel_event = kwargs.get('cancel_event')

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        payload = {
            'model': self.model_name,
            'messages': self.format_messages(messages),
            'temperature': temperature,
            'stream': True,
            'stream_options': {'include_usage': True},
        }

        if max_tokens:
            payload['max_tokens'] = max_tokens

        tools = kwargs.get('tools')
        if tools:
            payload['tools'] = tools
            payload['tool_choice'] = kwargs.get('tool_choice', 'auto')

        # Forward extra custom parameters from config to upstream API
        payload.update(self.extra_body)

        url = f'{self.api_base}/chat/completions'
        logger.info(
            "OpenAI stream request: url=%s, model=%s, messages=%d, timeout=%ds",
            url,
            self.model_name,
            len(payload.get('messages', [])),
            self.timeout,
        )

        logger.info(f"OpenAI stream request payload: {json.dumps(payload, ensure_ascii=False)}")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                'POST',
                f'{self.api_base}/chat/completions',
                headers=headers,
                json=payload
            ) as response:
                if response.status_code >= 400:
                    # Read error response body
                    error_body = await response.aread()
                    error_text = error_body.decode('utf-8')
                    logger.error(
                        f"LLM API error {response.status_code}: {error_text}"
                    )
                response.raise_for_status()

                async for line in response.aiter_lines():
                    # Check for cancel signal
                    if cancel_event and cancel_event.is_set():
                        logger.info("OpenAI stream cancelled")
                        yield {'type': 'done', 'content': ''}
                        break

                    # Support both "data: {...}" and "data:{...}" formats
                    if line.startswith('data:'):
                        # Extract JSON part (handle both "data: " and "data:" formats)
                        if line.startswith('data: '):
                            data_str = line[6:]  # Skip "data: "
                        else:
                            data_str = line[5:]  # Skip "data:"

                        if data_str == '[DONE]':
                            yield {'type': 'done', 'content': ''}
                            break

                        try:
                            data = json.loads(data_str)
                            parsed = self.structure_parser.parse_stream_chunk(data)
                            if parsed:
                                yield parsed
                        except Exception as e:
                            logger.warning(f"Error parsing stream chunk: {e}")

    async def embed(self, text: str) -> List[float]:
        """Generate embeddings using OpenAI API."""

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
        }

        payload = {
            'model': 'text-embedding-3-small',
            'input': text,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f'{self.api_base}/embeddings',
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()

        return data['data'][0]['embedding']

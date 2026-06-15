"""
LLM Response Parser abstraction layer.

Separates response parsing into two layers:
- Layer 1 (StructureParser): Extracts unified fields from raw API JSON.
  Determined by model/API format (e.g., GEMINI uses 'delta', QWEN uses 'message').
- Layer 2 (ContentParser): Parses structured content from text output.
  Determined by model behavior + system prompt (e.g., <think> tags, ReAct format).

Only Layer 1 is implemented; Layer 2 provides an interface for future extension.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


# =============================================================================
# Layer 1: Structure Parser — JSON format extraction
# =============================================================================

class BaseStructureParser(ABC):
    """Extract unified fields from raw LLM API JSON responses.

    Each subclass handles one specific API response format.
    Parsers are stateless and synchronous.
    """

    @abstractmethod
    def parse_response(self, data: dict) -> dict:
        """Parse a non-streaming API response into unified format.

        Args:
            data: Raw JSON response dict from the API.

        Returns:
            Unified response dict with keys:
                content, model, usage, finish_reason,
                tool_calls, reasoning_content, trace_id
        """

    @abstractmethod
    def parse_stream_chunk(self, data: dict) -> Optional[dict]:
        """Parse a single streaming chunk into unified format.

        Args:
            data: Parsed JSON dict from one SSE/stream line.

        Returns:
            A chunk dict like {'type': 'content', 'content': ..., 'trace_id': ...}
            or None if the chunk should be skipped.
        """

    @staticmethod
    def _extract_cached_tokens(usage: dict) -> int:
        """Extract cached_tokens from usage dict.

        Supports multiple formats:
        - OpenAI format: usage['prompt_tokens_details']['cached_tokens']
        - Gemini format: usage['promptTokensDetails']['cachedInputTokenCount']

        Args:
            usage: Usage dict from API response.

        Returns:
            Number of cached tokens (0 if not available).
        """
        if not usage:
            return 0
        # OpenAI format
        details = usage.get('prompt_tokens_details', {})
        if details:
            return details.get('cached_tokens', 0) or 0
        # Gemini native format
        details = usage.get('promptTokensDetails', {})
        if details:
            return details.get('cachedInputTokenCount', 0) or 0
        return 0

    @staticmethod
    def _default_response(
        content: str = '',
        model: str = '',
        usage: Optional[dict] = None,
        finish_reason: Optional[str] = None,
        tool_calls: Optional[list] = None,
        reasoning_content: str = '',
        trace_id: str = '',
        cached_tokens: int = 0,
    ) -> dict:
        """Build a response dict with all standard fields."""
        return {
            'content': content,
            'model': model,
            'usage': usage or {},
            'finish_reason': finish_reason,
            'tool_calls': tool_calls or [],
            'reasoning_content': reasoning_content,
            'trace_id': trace_id,
            'cached_tokens': cached_tokens,
        }


class GeminiStructureParser(BaseStructureParser):
    """Parser for GEMINI-style API responses.

    Response uses 'delta' field and string/bool 'finish_reason'.
    """

    def parse_response(self, data: dict) -> dict:
        content = ''
        tool_calls: list = []
        reasoning_content = ''

        choices = data.get('choices', [])
        if choices:
            # GEMINI may use 'delta' or 'message' for non-stream
            msg = choices[0].get('delta') or choices[0].get('message') or {}
            if msg:
                content = msg.get('content', '')
                reasoning_content = msg.get('reasoning_content', '')
                tool_calls = msg.get('tool_calls') or []

        finish_reason = None
        if choices:
            raw = choices[0].get('finish_reason')
            if raw is True:
                finish_reason = 'stop'
            elif isinstance(raw, str):
                finish_reason = raw

        usage = data.get('usage', {})
        return self._default_response(
            content=content,
            model=data.get('model', ''),
            usage=usage,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            trace_id=data.get('trace_id', ''),
            cached_tokens=self._extract_cached_tokens(usage),
        )

    def parse_stream_chunk(self, data: dict) -> Optional[dict]:
        trace_id = data.get('trace_id', '')
        choices = data.get('choices', [])

        # If chunk has usage but no choices (final chunk), emit usage
        if not choices and data.get('usage'):
            return {'type': 'usage', 'usage': data['usage'], 'trace_id': trace_id}

        if not choices:
            return None

        delta = choices[0].get('delta', {})
        if not delta:
            # Check for usage in the last chunk with empty delta
            if data.get('usage'):
                return {'type': 'usage', 'usage': data['usage'], 'trace_id': trace_id}
            return None

        reasoning_content = delta.get('reasoning_content', '')
        if reasoning_content:
            return {'type': 'reasoning_content', 'content': reasoning_content, 'trace_id': trace_id}

        content = delta.get('content', '')
        tool_calls = delta.get('tool_calls', [])

        if content:
            return {'type': 'content', 'content': content, 'trace_id': trace_id}
        if tool_calls:
            return {'type': 'tool_calls_delta', 'tool_calls': tool_calls, 'trace_id': trace_id}
        return None


class QwenStructureParser(BaseStructureParser):
    """Parser for QWEN-style API responses.

    Response uses 'message' field and bool 'finish'.
    """

    def parse_response(self, data: dict) -> dict:
        content = ''
        tool_calls: list = []
        reasoning_content = ''

        choices = data.get('choices', [])
        if choices:
            msg = choices[0].get('message', {})
            if msg:
                content = msg.get('content', '')
                reasoning_content = msg.get('reasoning_content', '')
                tool_calls = msg.get('tool_calls') or []

        finish_reason = None
        if choices:
            raw = choices[0].get('finish_reason') or choices[0].get('finish')
            if raw is True:
                finish_reason = 'stop'
            elif raw is False:
                # QWEN returns False when complete
                finish_reason = 'stop' if content else None
            elif isinstance(raw, str):
                finish_reason = raw

        usage = data.get('usage', {})
        return self._default_response(
            content=content,
            model=data.get('model', ''),
            usage=usage,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            reasoning_content=reasoning_content,
            trace_id=data.get('trace_id', ''),
            cached_tokens=self._extract_cached_tokens(usage),
        )

    def parse_stream_chunk(self, data: dict) -> Optional[dict]:
        trace_id = data.get('trace_id', '')
        choices = data.get('choices', [])

        # If chunk has usage but no choices (final chunk), emit usage
        if not choices and data.get('usage'):
            return {'type': 'usage', 'usage': data['usage'], 'trace_id': trace_id}

        if not choices:
            return None

        # QWEN stream may use 'delta' or 'message'
        delta = choices[0].get('delta') or choices[0].get('message') or {}
        if not delta:
            if data.get('usage'):
                return {'type': 'usage', 'usage': data['usage'], 'trace_id': trace_id}
            return None

        reasoning_content = delta.get('reasoning_content', '')
        if reasoning_content:
            return {'type': 'reasoning_content', 'content': reasoning_content, 'trace_id': trace_id}

        content = delta.get('content', '')
        tool_calls = delta.get('tool_calls', [])

        if content:
            return {'type': 'content', 'content': content, 'trace_id': trace_id}
        if tool_calls:
            return {'type': 'tool_calls_delta', 'tool_calls': tool_calls, 'trace_id': trace_id}
        return None


class OpenAIStructureParser(BaseStructureParser):
    """Parser for standard OpenAI API responses.

    Non-stream: choices[0]['message']['content']
    Stream: choices[0]['delta']['content']
    """

    def parse_response(self, data: dict) -> dict:
        choices = data.get('choices', [])
        content = ''
        finish_reason = None
        tool_calls: list = []

        if choices:
            msg = choices[0].get('message', {})
            content = msg.get('content', '')
            finish_reason = choices[0].get('finish_reason')
            tool_calls = msg.get('tool_calls') or []

        usage = data.get('usage', {})
        return self._default_response(
            content=content,
            model=data.get('model', ''),
            usage=usage,
            finish_reason=finish_reason,
            tool_calls=tool_calls,
            cached_tokens=self._extract_cached_tokens(usage),
        )

    def parse_stream_chunk(self, data: dict) -> Optional[dict]:
        # If chunk has usage but no delta content (final chunk), emit usage
        choices = data.get('choices', [])
        if not choices and data.get('usage'):
            return {'type': 'usage', 'usage': data['usage'], 'trace_id': ''}

        if not choices:
            return None

        delta = choices[0].get('delta', {})

        reasoning_content = delta.get('reasoning_content', '')
        if reasoning_content:
            return {'type': 'reasoning_content', 'content': reasoning_content, 'trace_id': ''}

        content = delta.get('content', '')
        tool_calls = delta.get('tool_calls', [])

        if content:
            return {'type': 'content', 'content': content, 'trace_id': ''}
        if tool_calls:
            return {'type': 'tool_calls_delta', 'tool_calls': tool_calls, 'trace_id': ''}

        # Check for usage in last chunk with empty delta
        if data.get('usage'):
            return {'type': 'usage', 'usage': data['usage'], 'trace_id': ''}
        return None


class OllamaStructureParser(BaseStructureParser):
    """Parser for Ollama API responses.

    Non-stream: message.content, done bool, prompt_eval_count/eval_count
    Stream: JSON lines with message.content
    """

    def parse_response(self, data: dict) -> dict:
        msg = data.get('message', {})
        content = msg.get('content', '')

        done = data.get('done', False)
        finish_reason = 'stop' if done else 'length'

        prompt_tokens = data.get('prompt_eval_count', 0)
        completion_tokens = data.get('eval_count', 0)
        usage = {
            'prompt_tokens': prompt_tokens,
            'completion_tokens': completion_tokens,
            'total_tokens': prompt_tokens + completion_tokens,
        }

        return self._default_response(
            content=content,
            model=data.get('model', ''),
            usage=usage,
            finish_reason=finish_reason,
            cached_tokens=0,
        )

    def parse_stream_chunk(self, data: dict) -> Optional[dict]:
        msg = data.get('message', {})
        content = msg.get('content', '')
        if content:
            return {'type': 'content', 'content': content, 'trace_id': ''}
        return None


# =============================================================================
# Layer 2: Content Parser — Text content extraction (interface only)
# =============================================================================

class BaseContentParser(ABC):
    """Parse structured content from LLM text output.

    Handles model-specific or prompt-specific text patterns:
    - <think>...</think> reasoning tag extraction
    - ReAct Thought/Action/Observation parsing
    - Custom XML/JSON output format parsing

    Determined by: model behavior + system prompt instructions.
    """

    @abstractmethod
    def parse_content(self, raw_content: str) -> dict:
        """Parse raw text content into structured result.

        Args:
            raw_content: The raw text from LLM response.

        Returns:
            Dict with parsed fields (implementation-specific).
        """

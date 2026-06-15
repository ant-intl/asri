"""
Lightweight VCR (Video Cassette Recorder) for HTTP request recording and playback.

This module provides a simple way to record real HTTP responses and replay them
in tests, ensuring mock data matches real API responses.

Usage:
    # Record mode: capture real HTTP responses
    LLM_TEST_MODE=record OPENAI_API_KEY=sk-xxx pytest ... -k "vcr"

    # Playback mode (default): use recorded responses
    pytest ... -k "vcr"

Cassette files are stored in apps/tests/integrations/llm/cassettes/
"""
import json
import os
from pathlib import Path
from typing import Any, Optional
from unittest.mock import patch, MagicMock, AsyncMock
from functools import wraps

import httpx


CASSETTES_DIR = Path(__file__).parent / 'cassettes'


def get_cassette_path(name: str) -> Path:
    """Get the full path for a cassette file."""
    return CASSETTES_DIR / f'{name}.json'


def load_cassette(name: str) -> Optional[dict]:
    """Load a cassette file if it exists."""
    path = get_cassette_path(name)
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


def save_cassette(name: str, data: dict) -> None:
    """Save response data to a cassette file."""
    CASSETTES_DIR.mkdir(parents=True, exist_ok=True)
    path = get_cassette_path(name)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Recorded cassette: {path}")


def is_record_mode() -> bool:
    """Check if we're in record mode."""
    return os.environ.get('LLM_TEST_MODE') == 'record'


class CassetteResponse:
    """Mock HTTP response from cassette data."""

    def __init__(self, data: dict):
        self._data = data
        self.status_code = data.get('status_code', 200)

    def json(self) -> dict:
        return self._data.get('body', {})

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                message=f'HTTP {self.status_code}',
                request=MagicMock(),
                response=self
            )


class CassetteStreamResponse:
    """Mock streaming HTTP response from cassette data."""

    def __init__(self, data: dict):
        self._data = data
        self._lines = data.get('stream_lines', [])
        self.status_code = data.get('status_code', 200)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                message=f'HTTP {self.status_code}',
                request=MagicMock(),
                response=self
            )

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class CassetteStreamContext:
    """Async context manager for stream responses."""

    def __init__(self, data: dict):
        self._data = data

    async def __aenter__(self):
        return CassetteStreamResponse(self._data)

    async def __aexit__(self, *args):
        pass


class RecordingClient:
    """HTTP client that records responses to cassettes."""

    def __init__(self, cassette_name: str, timeout: int = 30):
        self.cassette_name = cassette_name
        self.timeout = timeout
        self._recorded_data = {
            'requests': [],
            'responses': []
        }

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.timeout)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *args):
        await self._client.__aexit__(*args)
        # Save recorded data
        if self._recorded_data['responses']:
            save_cassette(self.cassette_name, {
                'body': self._recorded_data['responses'][-1],
                'status_code': 200
            })

    async def post(self, url: str, **kwargs) -> httpx.Response:
        self._recorded_data['requests'].append({
            'url': url,
            'method': 'POST',
            'kwargs': {k: v for k, v in kwargs.items() if k != 'headers'}
        })
        response = await self._client.post(url, **kwargs)
        response.raise_for_status()
        data = response.json()
        self._recorded_data['responses'].append(data)
        return response

    def stream(self, method: str, url: str, **kwargs):
        return RecordingStreamContext(
            self._client, method, url, self.cassette_name, **kwargs
        )


class RecordingStreamContext:
    """Context manager for recording stream responses."""

    def __init__(self, client: httpx.AsyncClient, method: str, url: str,
                 cassette_name: str, **kwargs):
        self._client = client
        self._method = method
        self._url = url
        self._cassette_name = cassette_name
        self._kwargs = kwargs
        self._lines = []

    async def __aenter__(self):
        self._stream = self._client.stream(self._method, self._url, **self._kwargs)
        self._response = await self._stream.__aenter__()
        return RecordingStreamResponse(self._response, self._lines)

    async def __aexit__(self, *args):
        await self._stream.__aexit__(*args)
        # Save recorded stream lines
        if self._lines:
            save_cassette(f'{self._cassette_name}_stream', {
                'stream_lines': self._lines,
                'status_code': 200
            })


class RecordingStreamResponse:
    """Wrapper that records stream lines."""

    def __init__(self, response: httpx.Response, lines_collector: list):
        self._response = response
        self._lines_collector = lines_collector

    def raise_for_status(self) -> None:
        self._response.raise_for_status()

    async def aiter_lines(self):
        async for line in self._response.aiter_lines():
            self._lines_collector.append(line)
            yield line


class PlaybackClient:
    """HTTP client that plays back responses from cassettes."""

    def __init__(self, cassette_name: str):
        self.cassette_name = cassette_name

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def post(self, url: str, **kwargs) -> CassetteResponse:
        data = load_cassette(self.cassette_name)
        if not data:
            raise FileNotFoundError(
                f"Cassette not found: {self.cassette_name}. "
                f"Run with LLM_TEST_MODE=record to record responses."
            )
        return CassetteResponse(data)

    def stream(self, method: str, url: str, **kwargs) -> CassetteStreamContext:
        data = load_cassette(f'{self.cassette_name}_stream')
        if not data:
            raise FileNotFoundError(
                f"Stream cassette not found: {self.cassette_name}_stream. "
                f"Run with LLM_TEST_MODE=record to record responses."
            )
        return CassetteStreamContext(data)


def use_cassette(cassette_name: str):
    """
    Decorator/context manager for using cassette recordings.

    In record mode: makes real HTTP requests and saves responses
    In playback mode: returns saved responses without HTTP requests

    Usage as decorator:
        @use_cassette('openai_chat')
        async def test_chat():
            ...

    Usage as context manager:
        async with use_cassette('openai_chat'):
            ...
    """
    def get_client():
        if is_record_mode():
            return RecordingClient(cassette_name)
        else:
            return PlaybackClient(cassette_name)

    class CassetteContext:
        def __init__(self):
            self._patcher = None

        async def __aenter__(self):
            self._patcher = patch('httpx.AsyncClient', lambda **kwargs: get_client())
            self._patcher.start()
            return self

        async def __aexit__(self, *args):
            if self._patcher:
                self._patcher.stop()

        def __call__(self, func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                async with self:
                    return await func(*args, **kwargs)
            return wrapper

    return CassetteContext()


# Convenience fixtures for pytest
def vcr_cassette(cassette_name: str):
    """
    Create a VCR cassette fixture for a test.

    Usage in conftest.py:
        @pytest.fixture
        def openai_vcr():
            return vcr_cassette('openai_chat')

    Usage in test:
        async def test_chat(openai_vcr):
            async with openai_vcr:
                result = await provider.chat(messages)
    """
    return use_cassette(cassette_name)

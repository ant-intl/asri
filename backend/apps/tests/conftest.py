"""
Pytest configuration for chatbot tests.

Provides:
- Django setup for all tests
- Real mode markers and fixtures for E2E tests
"""
import os

import django
import pytest
from unittest.mock import AsyncMock, patch

# Set up Django settings before importing any models
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.base')
# Set SERVER_ENV to empty so the middleware does not auto-assign
# the 'example' tenant during tests (base.py loads .env which may set SERVER_ENV=local).
# We must SET it (not pop) because load_dotenv(override=False) would reload it from .env.
os.environ['SERVER_ENV'] = ''


def pytest_configure():
    """Configure Django for pytest."""
    django.setup()


# -----------------------------------------------------------------------------
# Test Mode Control (shared with integrations/llm/conftest.py pattern)
# -----------------------------------------------------------------------------

def is_real_mode() -> bool:
    """Check if running in real mode."""
    return os.environ.get('LLM_TEST_MODE', 'mock') == 'real'


def real_mode_only(func_or_cls):
    """Mark a test as requiring real LLM API calls.

    Applies both ``pytest.mark.real_mode`` (for deselection via
    ``-m "not real_mode"`` in pytest.ini) and a ``skipif`` guard
    as a safety net when someone runs with ``-m real_mode`` but
    forgets to set ``LLM_TEST_MODE=real``.
    """
    func_or_cls = pytest.mark.real_mode(func_or_cls)
    func_or_cls = pytest.mark.skipif(
        not is_real_mode(),
        reason='Requires LLM_TEST_MODE=real and valid API credentials',
    )(func_or_cls)
    return func_or_cls


# -----------------------------------------------------------------------------
# E2E Test Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture
def e2e_session():
    """Create a fresh chat session for E2E tests.

    Requires Django DB (use with Django TestCase or pytest-django).
    """
    from apps.services.session_service import SessionService

    session_service = SessionService()

    async def _create():
        return await session_service.create_session(
            user_id='e2e_test_user',
            title='E2E Test Session',
        )

    import asyncio
    return asyncio.get_event_loop().run_until_complete(_create())


@pytest.fixture
def e2e_chat_service():
    """Create a ChatService with OpenAIProvider injected via LLMRegistry patch.

    Reads OPENAI_API_KEY, OPENAI_API_BASE, OPENAI_MODEL from env.
    Skips if credentials are missing.
    """
    from apps.integrations.llm.openai_provider import OpenAIProvider
    from apps.integrations.llm.registry import LLMRegistry
    from apps.services.chat_service import ChatService

    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        pytest.skip('OPENAI_API_KEY not set')

    api_base = os.environ.get('OPENAI_API_BASE', 'https://api.openai.com/v1')
    model_name = os.environ.get('OPENAI_MODEL', 'gpt-4')

    provider = OpenAIProvider(
        api_base=api_base,
        api_key=api_key,
        model_name=model_name,
        timeout=120,
    )

    with patch.object(LLMRegistry, 'get_provider_from_config', new_callable=AsyncMock, return_value=provider):
        yield ChatService()

    LLMRegistry._instances.clear()

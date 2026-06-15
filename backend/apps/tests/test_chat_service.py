"""
Tests for ChatService.
"""
import asyncio

import pytest
from asgiref.sync import sync_to_async
from unittest.mock import AsyncMock, MagicMock, patch
from django.test import TransactionTestCase

from apps.entities import ChatSession, ChatMessage
from apps.services.chat_service import ChatService, _streaming_sessions
from apps.tenant.context import set_current_tenant_id


# Sync helpers run in thread for use in async test methods
@sync_to_async
def _create_db_session(**kwargs):
    """Create a ChatSession from an async context."""
    return ChatSession.objects.create(**kwargs)


@sync_to_async
def _save_obj(obj):
    """Save a model instance from an async context."""
    obj.save()


@sync_to_async
def _get_user_messages(session_id):
    """Get user messages for a session from an async context."""
    return list(ChatMessage.objects.filter(
        session_id=session_id,
        role='user',
    ).order_by('gmt_create'))


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _mock_agent_run_response():
    """Standard mock result for agent.run()."""
    return {
        'answer': 'Mocked response',
        'trace': [{'type': 'think', 'content': 'thinking...'}],
        'model': 'test-model',
        'prompt_tokens': 10,
        'completion_tokens': 5,
        'total_tokens': 15,
        'system_prompt': 'test system prompt',
        'tools': [],
        'context_messages': [
            {'role': 'system', 'content': 'test'},
            {'role': 'user', 'content': 'hello'},
            {'role': 'assistant', 'content': 'Mocked response'},
        ],
    }


def _make_mock_agent():
    """Create a standalone mock ChatAgent."""
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=_mock_agent_run_response())
    mock_agent.stream = MagicMock(return_value=_mock_stream_chunks())
    mock_agent.get_context_messages = AsyncMock(return_value=[
        {'role': 'user', 'content': 'hello'},
        {'role': 'assistant', 'content': 'Mocked response'},
    ])
    return mock_agent


async def _mock_stream_chunks():
    """Mock async generator for agent.stream()."""
    yield {'type': 'think', 'content': 'thinking...'}
    yield {'type': 'answer', 'content': 'Hello, '}
    yield {'type': 'answer', 'content': 'how can I help?'}
    yield {'type': 'done', 'content': '', 'context_messages': [
        {'role': 'system', 'content': 'test'},
        {'role': 'user', 'content': 'hello'},
        {'role': 'assistant', 'content': 'Hello, how can I help?'},
    ]}


async def _collect_stream(generator):
    """Collect all items from an async generator."""
    items = []
    async for item in generator:
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Tests: ChatService.chat()
# ---------------------------------------------------------------------------

class TestChatServiceChat(TransactionTestCase):
    """Tests for ChatService.chat() method."""

    def setUp(self):
        self.svc = ChatService()
        self._tenant_token = set_current_tenant_id('example')
        self.session = ChatSession.objects.create(
            tenant_id='example',
            user_id='test_user',
            title='Test Session',
        )

    def tearDown(self):
        from apps.tenant.context import tenant_id_var
        tenant_id_var.reset(self._tenant_token)

    @pytest.mark.asyncio
    async def test_chat_basic(self):
        """chat() returns correct response format."""
        mock_agent = _make_mock_agent()
        with patch.object(self.svc, '_create_agent', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_agent

            result = await self.svc.chat(
                session=self.session,
                message='Hello',
                user_id='test_user',
            )

        assert result['content'] == 'Mocked response'
        assert result['message_id'] is not None
        assert result['usage']['total_tokens'] == 15
        assert len(result['trace']) == 1

    @pytest.mark.asyncio
    async def test_chat_user_context(self):
        """chat() passes user_context from session.metadata to agent."""
        session = await _create_db_session(
            tenant_id='example',
            user_id='test_user',
            title='Test',
            metadata={'user_context': {'userId': '2088123'}},
        )

        mock_agent = _make_mock_agent()
        with patch.object(self.svc, '_create_agent', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_agent

            await self.svc.chat(
                session=session,
                message='Hello',
                user_id='test_user',
            )

        call_kwargs = mock_agent.run.call_args.kwargs
        context = call_kwargs.get('context')
        assert context is not None
        assert context.user_context == {'userId': '2088123'}

    @pytest.mark.asyncio
    async def test_chat_empty_metadata(self):
        """chat() handles sessions with None metadata."""
        session = await _create_db_session(
            tenant_id='example',
            user_id='test_user',
            title='Test',
        )
        session.metadata = None
        await _save_obj(session)

        mock_agent = _make_mock_agent()
        with patch.object(self.svc, '_create_agent', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_agent

            await self.svc.chat(
                session=session,
                message='Hello',
                user_id='test_user',
            )

        context = mock_agent.run.call_args.kwargs.get('context')
        assert context.user_context == {}


# ---------------------------------------------------------------------------
# Tests: ChatService.batch_chat()
# ---------------------------------------------------------------------------

class TestChatServiceBatchChat(TransactionTestCase):
    """Tests for ChatService.batch_chat() method."""

    def setUp(self):
        self.svc = ChatService()
        self._tenant_token = set_current_tenant_id('example')
        self.session = ChatSession.objects.create(
            tenant_id='example',
            user_id='test_user',
            title='Test Session',
        )

    def tearDown(self):
        from apps.tenant.context import tenant_id_var
        tenant_id_var.reset(self._tenant_token)

    @pytest.mark.asyncio
    async def test_batch_chat_basic(self):
        """batch_chat() processes multiple messages."""
        mock_agent = _make_mock_agent()
        with patch.object(self.svc, '_create_agent', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_agent

            result = await self.svc.batch_chat(
                session=self.session,
                messages=['Question 1', 'Question 2'],
                user_id='test_user',
            )

        assert result['content'] == 'Mocked response'
        assert result['message_id'] is not None
        assert result['group_id'] is not None
        query = mock_agent.run.call_args.kwargs.get('query')
        assert 'Question 1' in query
        assert 'Question 2' in query

    @pytest.mark.asyncio
    async def test_batch_chat_user_context(self):
        """batch_chat() passes user_context from session.metadata to agent."""
        session = await _create_db_session(
            tenant_id='example',
            user_id='test_user',
            title='Test',
            metadata={'user_context': {'userId': 'batch_user'}},
        )

        mock_agent = _make_mock_agent()
        with patch.object(self.svc, '_create_agent', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_agent

            await self.svc.batch_chat(
                session=session,
                messages=['Test message'],
                user_id='test_user',
            )

        context = mock_agent.run.call_args.kwargs.get('context')
        assert context.user_context == {'userId': 'batch_user'}

    @pytest.mark.asyncio
    async def test_batch_chat_custom_group_id(self):
        """batch_chat() uses provided group_id."""
        custom_group = 'custom-group-123'

        mock_agent = _make_mock_agent()
        with patch.object(self.svc, '_create_agent', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_agent

            result = await self.svc.batch_chat(
                session=self.session,
                messages=['Test'],
                user_id='test_user',
                group_id=custom_group,
            )

        assert result['group_id'] == custom_group


# ---------------------------------------------------------------------------
# Tests: ChatService.stream_chat()
# ---------------------------------------------------------------------------

class TestChatServiceStreamChat(TransactionTestCase):
    """Tests for ChatService.stream_chat() method."""

    def setUp(self):
        self.svc = ChatService()
        self._tenant_token = set_current_tenant_id('example')
        self.session = ChatSession.objects.create(
            tenant_id='example',
            user_id='test_user',
            title='Test Session',
        )
        _streaming_sessions.clear()

    def tearDown(self):
        from apps.tenant.context import tenant_id_var
        tenant_id_var.reset(self._tenant_token)

    @pytest.mark.asyncio
    async def test_stream_chat_basic(self):
        """stream_chat() yields answer chunks and done event."""
        mock_agent = _make_mock_agent()
        with patch.object(self.svc, '_create_agent', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_agent

            chunks = await _collect_stream(
                self.svc.stream_chat(
                    session=self.session,
                    message='Hello',
                    user_id='test_user',
                )
            )

        answer_chunks = [c for c in chunks if c.get('type') == 'answer']
        done_chunks = [c for c in chunks if c.get('type') == 'done']
        think_chunks = [c for c in chunks if c.get('type') == 'think']
        assert len(answer_chunks) == 2
        assert len(done_chunks) == 1
        assert len(think_chunks) == 1
        assert done_chunks[0]['message_id'] is not None

    @pytest.mark.asyncio
    async def test_stream_chat_user_context(self):
        """stream_chat() passes user_context from session.metadata to agent."""
        session = await _create_db_session(
            tenant_id='example',
            user_id='test_user',
            title='Test',
            metadata={'user_context': {'userId': 'stream_user'}},
        )
        _streaming_sessions.clear()

        mock_agent = _make_mock_agent()
        with patch.object(self.svc, '_create_agent', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_agent

            await _collect_stream(
                self.svc.stream_chat(
                    session=session,
                    message='Hello',
                    user_id='test_user',
                )
            )

        call_kwargs = mock_agent.stream.call_args.kwargs
        context = call_kwargs.get('context')
        assert context is not None
        assert context.user_context == {'userId': 'stream_user'}

    @pytest.mark.asyncio
    async def test_stream_chat_skip_user_message(self):
        """stream_chat() skips saving user message with user_message_id."""
        mock_agent = _make_mock_agent()
        with patch.object(self.svc, '_create_agent', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_agent

            await _collect_stream(
                self.svc.stream_chat(
                    session=self.session,
                    message='Hello',
                    user_id='test_user',
                    user_message_id='pre-saved-msg-id',
                )
            )

        user_msgs = await _get_user_messages(self.session.session_id)
        assert len(user_msgs) == 0

    @pytest.mark.asyncio
    async def test_stream_chat_interrupt(self):
        """stream_chat() handles interrupt signal correctly."""
        interrupted_sid = str(self.session.session_id)

        async def _interrupting_stream():
            yield {'type': 'answer', 'content': 'partial '}
            _streaming_sessions[interrupted_sid].set()
            yield {'type': 'answer', 'content': 'content'}

        mock_agent = MagicMock()
        mock_agent.stream = MagicMock(return_value=_interrupting_stream())
        mock_agent.get_context_messages = AsyncMock(return_value=[
            {'role': 'user', 'content': 'Hello'},
        ])

        with patch.object(self.svc, '_create_agent', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_agent

            chunks = await _collect_stream(
                self.svc.stream_chat(
                    session=self.session,
                    message='Hello',
                    user_id='test_user',
                )
            )

        assert len([c for c in chunks if c.get('type') == 'answer']) == 1

    @pytest.mark.asyncio
    async def test_stream_chat_clears_registry(self):
        """stream_chat() removes session from _streaming_sessions on finish."""
        sid = str(self.session.session_id)

        mock_agent = _make_mock_agent()
        with patch.object(self.svc, '_create_agent', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_agent

            await _collect_stream(
                self.svc.stream_chat(
                    session=self.session,
                    message='Hello',
                    user_id='test_user',
                )
            )

        assert sid not in _streaming_sessions

    @pytest.mark.asyncio
    async def test_stream_chat_empty_metadata(self):
        """stream_chat() handles sessions with None metadata."""
        session = await _create_db_session(
            tenant_id='example',
            user_id='test_user',
            title='Test',
        )
        session.metadata = None
        await _save_obj(session)
        _streaming_sessions.clear()

        mock_agent = _make_mock_agent()
        with patch.object(self.svc, '_create_agent', new_callable=AsyncMock) as mock_create:
            mock_create.return_value = mock_agent

            await _collect_stream(
                self.svc.stream_chat(
                    session=session,
                    message='Hello',
                    user_id='test_user',
                )
            )

        context = mock_agent.stream.call_args.kwargs.get('context')
        assert context.user_context == {}


# ---------------------------------------------------------------------------
# Tests: ChatService.interrupt_session()
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestChatServiceInterrupt:
    """Tests for ChatService.interrupt_session() method."""

    def setup_method(self):
        _streaming_sessions.clear()
        self.svc = ChatService()

    @pytest.mark.asyncio
    async def test_interrupt_no_active_session(self):
        """interrupt_session() returns False when no active stream."""
        result = await self.svc.interrupt_session('nonexistent', 'interrupt message')
        assert result is False

    @pytest.mark.asyncio
    async def test_interrupt_active_session(self):
        """interrupt_session() returns True and sets the event."""
        event = asyncio.Event()
        _streaming_sessions['session-123'] = event

        result = await self.svc.interrupt_session('session-123', 'new message')
        assert result is True
        assert event.is_set()
        assert event.interrupt_message == 'new message'

    @pytest.mark.asyncio
    async def test_interrupt_only_matching(self):
        """interrupt_session() only interrupts the specified session."""
        event1 = asyncio.Event()
        event2 = asyncio.Event()
        _streaming_sessions['session-1'] = event1
        _streaming_sessions['session-2'] = event2

        result = await self.svc.interrupt_session('session-1', 'interrupt')
        assert result is True
        assert event1.is_set()
        assert not event2.is_set()

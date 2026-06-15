"""
Tests for session service.
"""
import pytest
from django.test import TestCase

from apps.entities import ChatSession, ChatMessage
from apps.services.session_service import SessionService


class TestSessionService(TestCase):
    """Tests for SessionService."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = SessionService()
    
    @pytest.mark.asyncio
    async def test_create_session(self):
        """Test creating a session through service."""
        session = await self.service.create_session(
            user_id='test_user',
            title='Test Session',
        )
        
        assert session.session_id is not None
        assert session.user_id == 'test_user'
        assert session.title == 'Test Session'
        assert session.agent_type == 'react'  # default value
    
    @pytest.mark.asyncio
    async def test_get_session(self):
        """Test getting a session by ID."""
        created = await self.service.create_session(
            user_id='test_user',
            title='Test'
        )
        
        fetched = await self.service.get_session(str(created.session_id))
        
        assert fetched is not None
        assert str(fetched.session_id) == str(created.session_id)
    
    @pytest.mark.asyncio
    async def test_get_session_not_found(self):
        """Test getting a non-existent session."""
        session = await self.service.get_session('non-existent-id')
        
        assert session is None
    
    @pytest.mark.asyncio
    async def test_list_sessions(self):
        """Test listing sessions for a user."""
        user_id = 'list_test_user'
        
        for i in range(3):
            await self.service.create_session(
                user_id=user_id,
                title=f'Session {i}'
            )
        
        sessions, total = await self.service.list_sessions(
            user_id=user_id,
            page=1,
            page_size=10
        )
        
        assert total == 3
        assert len(sessions) == 3
    
    @pytest.mark.asyncio
    async def test_list_sessions_pagination(self):
        """Test session listing pagination."""
        user_id = 'pagination_user'
        
        for i in range(5):
            await self.service.create_session(
                user_id=user_id,
                title=f'Session {i}'
            )
        
        sessions, total = await self.service.list_sessions(
            user_id=user_id,
            page=1,
            page_size=2
        )
        
        assert total == 5
        assert len(sessions) == 2
    
    @pytest.mark.asyncio
    async def test_update_session(self):
        """Test updating a session."""
        session = await self.service.create_session(
            user_id='test_user',
            title='Original'
        )
        
        updated = await self.service.update_session(
            session_id=session.session_id,
            title='Updated Title'
        )
        
        assert updated is not None
        assert updated.title == 'Updated Title'
    
    @pytest.mark.asyncio
    async def test_delete_session(self):
        """Test soft deleting a session."""
        session = await self.service.create_session(
            user_id='test_user',
            title='To Delete'
        )
        
        result = await self.service.delete_session(session.session_id)
        
        assert result is True
        
        # Session should still exist but with deleted status
        deleted = await self.service.get_session(session.session_id)
        assert deleted.status == 'deleted'
    
    @pytest.mark.asyncio
    async def test_add_message(self):
        """Test adding a message to a session."""
        session = await self.service.create_session(
            user_id='test_user',
            title='Message Test'
        )
        
        message = await self.service.add_message(
            session_id=session.session_id,
            role='user',
            content='Hello!'
        )
        
        assert message.message_id is not None
        assert message.role == 'user'
        assert message.content == 'Hello!'
    
    @pytest.mark.asyncio
    async def test_add_message_updates_title(self):
        """Test that first user message updates empty session title."""
        session = await self.service.create_session(
            user_id='test_user',
            title=''
        )
        
        await self.service.add_message(
            session_id=session.session_id,
            role='user',
            content='What is the weather today?'
        )
        
        updated = await self.service.get_session(session.session_id)
        assert updated.title != ''
        assert 'weather' in updated.title.lower()
    
    @pytest.mark.asyncio
    async def test_get_messages(self):
        """Test getting messages for a session."""
        session = await self.service.create_session(
            user_id='test_user',
            title='Test'
        )
        
        await self.service.add_message(
            session_id=session.session_id,
            role='user',
            content='Message 1'
        )
        await self.service.add_message(
            session_id=session.session_id,
            role='assistant',
            content='Message 2'
        )
        
        messages, total = await self.service.get_messages(
            session_id=session.session_id
        )
        
        assert total == 2
        assert len(messages) == 2
    
    @pytest.mark.asyncio
    async def test_get_conversation_history(self):
        """Test getting conversation history for LLM context."""
        session = await self.service.create_session(
            user_id='test_user',
            title='Test'
        )
        
        await self.service.add_message(
            session_id=session.session_id,
            role='user',
            content='Hello',
            message_type='text'
        )
        await self.service.add_message(
            session_id=session.session_id,
            role='assistant',
            content='Hi there!',
            message_type='text'
        )
        # Thought messages should not be included
        await self.service.add_message(
            session_id=session.session_id,
            role='assistant',
            content='Thinking...',
            message_type='thought'
        )
        
        history = await self.service.get_conversation_history(
            session_id=session.session_id
        )
        
        assert len(history) == 2
        assert history[0]['role'] == 'user'
        assert history[1]['role'] == 'assistant'
    
    @pytest.mark.asyncio
    async def test_delete_message(self):
        """Test deleting a message."""
        session = await self.service.create_session(
            user_id='test_user',
            title='Test'
        )
        
        message = await self.service.add_message(
            session_id=session.session_id,
            role='user',
            content='To delete'
        )
        
        result = await self.service.delete_message(message.message_id)
        
        assert result is True
        
        # Verify message is deleted
        deleted = await self.service.get_message(message.message_id)
        assert deleted is None

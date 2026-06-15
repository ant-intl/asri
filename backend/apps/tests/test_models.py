"""
Tests for chatbot models.
"""
import pytest
from django.test import TestCase

from apps.entities import ChatSession, ChatMessage


class TestChatSession(TestCase):
    """Tests for ChatSession model."""
    
    def test_create_session(self):
        """Test creating a chat session."""
        session = ChatSession.objects.create(
            user_id='test_user_001',
            title='Test Session'
        )
        
        assert session.id is not None
        assert session.session_id is not None
        assert session.user_id == 'test_user_001'
        assert session.title == 'Test Session'
        assert session.status == ChatSession.Status.ACTIVE
        assert session.agent_type == ChatSession.AgentType.REACT
    
    def test_session_default_values(self):
        """Test session default values."""
        session = ChatSession.objects.create(user_id='test_user')
        
        assert session.title == ''
        assert session.status == 'active'
        assert session.agent_type == 'react'
        assert session.metadata == {}
    
    def test_session_str_representation(self):
        """Test session string representation."""
        session = ChatSession.objects.create(
            user_id='test_user',
            title='My Chat'
        )
        
        assert 'My Chat' in str(session)
    
    def test_session_str_untitled(self):
        """Test session string representation when untitled."""
        session = ChatSession.objects.create(user_id='test_user')
        
        assert 'Untitled' in str(session)
    
    def test_session_uuid_generation(self):
        """Test that session_id is auto-generated."""
        session1 = ChatSession.objects.create(user_id='user1')
        session2 = ChatSession.objects.create(user_id='user2')
        
        assert session1.session_id != session2.session_id
        assert len(str(session1.session_id)) == 36  # UUID format


class TestChatMessage(TestCase):
    """Tests for ChatMessage model."""
    
    def setUp(self):
        """Set up test session."""
        self.session = ChatSession.objects.create(
            user_id='test_user',
            title='Test Session'
        )
    
    def test_create_message(self):
        """Test creating a chat message."""
        message = ChatMessage.objects.create(
            session_id=str(self.session.session_id),
            role=ChatMessage.Role.USER,
            content='Hello, how are you?'
        )
        
        assert message.id is not None
        assert message.message_id is not None
        assert message.role == 'user'
        assert message.content == 'Hello, how are you?'
        assert message.message_type == ChatMessage.MessageType.TEXT
    
    def test_message_types(self):
        """Test different message types."""
        thought = ChatMessage.objects.create(
            session_id=str(self.session.session_id),
            role=ChatMessage.Role.ASSISTANT,
            content='Thinking...',
            message_type=ChatMessage.MessageType.THOUGHT
        )
        
        action = ChatMessage.objects.create(
            session_id=str(self.session.session_id),
            role=ChatMessage.Role.ASSISTANT,
            content='RAG',
            message_type=ChatMessage.MessageType.ACTION
        )
        
        observation = ChatMessage.objects.create(
            session_id=str(self.session.session_id),
            role=ChatMessage.Role.TOOL,
            content='Search results...',
            message_type=ChatMessage.MessageType.OBSERVATION
        )
        
        assert thought.message_type == 'thought'
        assert action.message_type == 'action'
        assert observation.message_type == 'observation'
    
    def test_message_str_representation(self):
        """Test message string representation."""
        message = ChatMessage.objects.create(
            session_id=str(self.session.session_id),
            role=ChatMessage.Role.USER,
            content='Short message'
        )
        
        assert '[user]' in str(message)
        assert 'Short message' in str(message)
    
    def test_message_str_truncation(self):
        """Test message string truncation for long content."""
        long_content = 'A' * 100
        message = ChatMessage.objects.create(
            session_id=str(self.session.session_id),
            role=ChatMessage.Role.USER,
            content=long_content
        )
        
        str_repr = str(message)
        assert '...' in str_repr
        assert len(str_repr) < len(long_content)
    
    def test_message_delete_with_session(self):
        """Test that messages can be deleted by session_id."""
        message = ChatMessage.objects.create(
            session_id=str(self.session.session_id),
            role=ChatMessage.Role.USER,
            content='Test message'
        )
        message_id = message.id
        
        ChatMessage.objects.filter(session_id=str(self.session.session_id)).delete()
        
        assert not ChatMessage.objects.filter(id=message_id).exists()
    
    def test_message_ordering(self):
        """Test that messages are ordered by creation time."""
        msg1 = ChatMessage.objects.create(
            session_id=str(self.session.session_id),
            role=ChatMessage.Role.USER,
            content='First'
        )
        msg2 = ChatMessage.objects.create(
            session_id=str(self.session.session_id),
            role=ChatMessage.Role.ASSISTANT,
            content='Second'
        )
        
        messages = list(ChatMessage.objects.filter(
            session_id=str(self.session.session_id)
        ))
        
        assert messages[0].id == msg1.id
        assert messages[1].id == msg2.id

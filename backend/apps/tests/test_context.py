"""
Tests for agent context.
"""
import pytest

from apps.agent.agent.context import AgentContext


class TestAgentContext:
    """Tests for AgentContext."""
    
    def test_default_values(self):
        """Test default context values."""
        ctx = AgentContext()
        
        assert ctx.session_id == ''
        assert ctx.user_id == ''
        assert ctx.messages == []
        assert ctx.current_query == ''
        assert ctx.available_tools == []
        assert ctx.available_skills == []
        assert ctx.rag_enabled is False
        assert ctx.iteration_count == 0
        assert ctx.max_iterations == 10
        assert ctx.trace == []
        assert ctx.prompt_tokens == 0
        assert ctx.completion_tokens == 0
        assert ctx.metadata == {}
    
    def test_custom_initialization(self):
        """Test context with custom values."""
        ctx = AgentContext(
            session_id='session-123',
            user_id='user-456',
            current_query='What is AI?',
            available_tools=['search', 'calculate'],
            rag_enabled=True,
            max_iterations=5
        )
        
        assert ctx.session_id == 'session-123'
        assert ctx.user_id == 'user-456'
        assert ctx.current_query == 'What is AI?'
        assert ctx.available_tools == ['search', 'calculate']
        assert ctx.rag_enabled is True
        assert ctx.max_iterations == 5
    
    def test_add_trace(self):
        """Test adding trace entries."""
        ctx = AgentContext()
        
        ctx.add_trace('thought', 'Analyzing the question')
        ctx.add_trace('action', 'RAG', {'input': 'AI definition'})
        
        assert len(ctx.trace) == 2
        assert ctx.trace[0]['type'] == 'thought'
        assert ctx.trace[0]['content'] == 'Analyzing the question'
        assert ctx.trace[0]['iteration'] == 0
        assert ctx.trace[1]['type'] == 'action'
        assert ctx.trace[1]['metadata'] == {'input': 'AI definition'}
    
    def test_add_trace_with_iteration(self):
        """Test trace entries track iteration count."""
        ctx = AgentContext()
        
        ctx.add_trace('thought', 'First thought')
        ctx.increment_iteration()
        ctx.add_trace('thought', 'Second thought')
        ctx.increment_iteration()
        ctx.add_trace('thought', 'Third thought')
        
        assert ctx.trace[0]['iteration'] == 0
        assert ctx.trace[1]['iteration'] == 1
        assert ctx.trace[2]['iteration'] == 2
    
    def test_increment_iteration(self):
        """Test iteration increment."""
        ctx = AgentContext(max_iterations=3)
        
        assert ctx.iteration_count == 0
        
        result = ctx.increment_iteration()
        assert ctx.iteration_count == 1
        assert result is True
        
        result = ctx.increment_iteration()
        assert ctx.iteration_count == 2
        assert result is True
        
        result = ctx.increment_iteration()
        assert ctx.iteration_count == 3
        assert result is False  # Reached limit
    
    def test_increment_iteration_limit(self):
        """Test iteration limit behavior."""
        ctx = AgentContext(max_iterations=1)
        
        result = ctx.increment_iteration()
        assert result is False
        assert ctx.iteration_count == 1
    
    def test_get_total_tokens(self):
        """Test total token calculation."""
        ctx = AgentContext()
        ctx.prompt_tokens = 100
        ctx.completion_tokens = 50
        
        assert ctx.get_total_tokens() == 150
    
    def test_get_total_tokens_zero(self):
        """Test total tokens when zero."""
        ctx = AgentContext()
        
        assert ctx.get_total_tokens() == 0
    
    def test_messages_list(self):
        """Test managing messages list."""
        ctx = AgentContext()
        
        ctx.messages.append({'role': 'user', 'content': 'Hello'})
        ctx.messages.append({'role': 'assistant', 'content': 'Hi!'})
        
        assert len(ctx.messages) == 2
        assert ctx.messages[0]['role'] == 'user'
        assert ctx.messages[1]['role'] == 'assistant'
    
    def test_metadata_dict(self):
        """Test metadata storage."""
        ctx = AgentContext()
        
        ctx.metadata['model'] = 'gpt-4'
        ctx.metadata['temperature'] = 0.7
        
        assert ctx.metadata['model'] == 'gpt-4'
        assert ctx.metadata['temperature'] == 0.7
    
    def test_independent_instances(self):
        """Test that multiple contexts are independent."""
        ctx1 = AgentContext()
        ctx2 = AgentContext()
        
        ctx1.messages.append({'role': 'user', 'content': 'Ctx1'})
        ctx1.available_tools.append('tool1')
        
        assert ctx2.messages == []
        assert ctx2.available_tools == []

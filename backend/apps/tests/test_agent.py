"""
Tests for Agent module.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.agent.agent.context import AgentContext
from apps.agent.agent.chat_agent import ChatAgent


def make_mock_template(system_template: str = "Test system prompt", mode: str = 'generic',
                        user_template: str = '', extractor_config: dict = None):
    """Create a mock PromptTemplate object for testing."""
    template = MagicMock()
    template.system_template = system_template
    template.user_template_mode = mode
    template.user_template = user_template
    template.extractor_config = extractor_config or {}
    template.is_active = True
    return template


class TestAgentContext:
    """Test cases for AgentContext."""
    
    def test_context_creation(self):
        """Test context can be created with default values."""
        context = AgentContext(
            session_id='test-session',
            user_id='test-user',
        )
        
        assert context.session_id == 'test-session'
        assert context.user_id == 'test-user'
        assert context.messages == []
        assert context.iteration_count == 0
    
    def test_context_with_messages(self):
        """Test context can be created with messages."""
        messages = [
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Hi there!'},
        ]
        context = AgentContext(
            session_id='test-session',
            user_id='test-user',
            messages=messages,
        )
        
        assert len(context.messages) == 2
    
    def test_add_trace(self):
        """Test adding trace entries."""
        context = AgentContext(
            session_id='test-session',
            user_id='test-user',
        )
        
        context.add_trace('thought', 'I need to search for information')
        
        assert len(context.trace) == 1
        assert context.trace[0]['type'] == 'thought'


class TestChatAgent:
    """Test cases for ChatAgent."""

    @pytest.fixture
    def mock_llm_provider(self):
        """Create a mock LLM provider that returns streaming chunks."""
        provider = MagicMock()
        provider.get_model_name = MagicMock(return_value='test-model')

        async def mock_stream(*args, **kwargs):
            yield {'type': 'content', 'content': 'Hello, how can I help you?'}
            yield {'type': 'done', 'content': ''}

        provider.chat = AsyncMock(return_value=mock_stream())
        return provider

    @pytest.fixture
    def agent_context(self):
        """Create a test agent context."""
        return AgentContext(
            session_id='test-session',
            user_id='test-user',
            messages=[],
        )
    
    @pytest.mark.asyncio
    async def test_agent_initialization(self, mock_llm_provider):
        """Test agent can be initialized with system_prompt."""
        agent = ChatAgent(llm_provider=mock_llm_provider, system_prompt='Test')
        assert agent is not None
    
    @pytest.mark.asyncio
    async def test_agent_initialization_with_prompt(self, mock_llm_provider):
        """Test agent can be initialized with a DynamicPrompt instance."""
        from apps.agent.prompts import DynamicPrompt
        mock_template = make_mock_template("Test")
        prompt = DynamicPrompt('test', db_template=mock_template)
        agent = ChatAgent(llm_provider=mock_llm_provider, prompt=prompt)
        assert agent is not None
    
    @pytest.mark.asyncio
    async def test_agent_raises_without_prompt_or_system_prompt(self, mock_llm_provider):
        """Test agent raises ValueError when neither prompt nor system_prompt is given."""
        with pytest.raises(ValueError, match='Either system_prompt or prompt must be provided'):
            ChatAgent(llm_provider=mock_llm_provider)
    
    @pytest.mark.asyncio
    async def test_agent_simple_response(self, mock_llm_provider, agent_context):
        """Test agent returns simple response."""
        agent = ChatAgent(llm_provider=mock_llm_provider, system_prompt='Test')
        
        result = await agent.run(
            query='Hello',
            context=agent_context,
        )

        assert 'answer' in result
        mock_llm_provider.chat.assert_called()

    @pytest.mark.asyncio
    async def test_agent_max_iterations(self, mock_llm_provider, agent_context):
        """Test agent respects max iterations."""
        agent = ChatAgent(
            llm_provider=mock_llm_provider,
            system_prompt='Test',
            max_iterations=3,
        )
        assert agent.max_iterations == 3

    @pytest.mark.asyncio
    async def test_run_returns_correct_format(self, mock_llm_provider, agent_context):
        """run() returns dict with answer, trace, token counts, model."""
        agent = ChatAgent(llm_provider=mock_llm_provider, system_prompt='Test')
        result = await agent.run(query='hello', context=agent_context)

        assert 'answer' in result
        assert 'trace' in result
        assert 'prompt_tokens' in result
        assert 'completion_tokens' in result
        assert 'total_tokens' in result
        assert result['model'] == 'test-model'


class TestChatAgentPromptBehavior:
    """Test ChatAgent prompt behavior with DynamicPrompt."""

    @pytest.fixture
    def mock_llm_provider(self):
        """Create a mock LLM provider."""
        provider = MagicMock()
        provider.get_model_name = MagicMock(return_value='test-model')

        async def mock_stream(*args, **kwargs):
            yield {'type': 'content', 'content': 'Test answer'}
            yield {'type': 'done', 'content': ''}

        provider.chat = AsyncMock(return_value=mock_stream())
        return provider

    def test_agent_with_prompt_object(self, mock_llm_provider):
        """Agent should accept a DynamicPrompt instance and use its prompt_name."""
        from apps.agent.prompts import DynamicPrompt
        mock_template = make_mock_template("Test")
        prompt = DynamicPrompt('my_custom_prompt', db_template=mock_template)
        agent = ChatAgent(llm_provider=mock_llm_provider, prompt=prompt)
        assert agent._prompt is not None
        assert agent._prompt.prompt_name == 'my_custom_prompt'

    def test_build_messages_system_prompt(self, mock_llm_provider):
        """System message should use system_template from DB template."""
        from apps.agent.prompts import DynamicPrompt
        expected = "Custom system prompt for testing"
        mock_template = make_mock_template(expected)
        prompt = DynamicPrompt('test', db_template=mock_template)
        agent = ChatAgent(llm_provider=mock_llm_provider, prompt=prompt)
        messages = agent._build_messages(query='Hello')
        assert messages[0]['role'] == 'system'
        assert messages[0]['content'] == expected

    def test_build_messages_user_prompt(self, mock_llm_provider):
        """User message should contain the query text."""
        from apps.agent.prompts import DynamicPrompt
        mock_template = make_mock_template("Test")
        prompt = DynamicPrompt('test', db_template=mock_template)
        agent = ChatAgent(llm_provider=mock_llm_provider, prompt=prompt)
        messages = agent._build_messages(query='What is IBAN?')
        user_msg = messages[-1]
        assert user_msg['role'] == 'user'
        assert 'What is IBAN?' in user_msg['content']

    def test_build_messages_includes_history(self, mock_llm_provider):
        """History messages should appear between system and user messages."""
        from apps.agent.prompts import DynamicPrompt
        mock_template = make_mock_template("Test")
        prompt = DynamicPrompt('test', db_template=mock_template)
        agent = ChatAgent(llm_provider=mock_llm_provider, prompt=prompt)
        history = [
            {'role': 'user', 'content': 'prev question'},
            {'role': 'assistant', 'content': 'prev answer'},
        ]
        messages = agent._build_messages(query='follow up', history=history)
        assert len(messages) == 4  # system + 2 history + user
        assert messages[1]['content'] == 'prev question'
        assert messages[2]['content'] == 'prev answer'

    def test_build_messages_custom_system_prompt_bypasses_prompt(self, mock_llm_provider):
        """When system_prompt is set, _build_messages bypasses the prompt class entirely."""
        agent = ChatAgent(llm_provider=mock_llm_provider, system_prompt='My custom prompt')
        messages = agent._build_messages(query='Hello')
        assert messages[0]['role'] == 'system'
        assert messages[0]['content'] == 'My custom prompt'

    @patch('apps.integrations.skill.registry.SkillRegistry.list_skills_with_descriptions')
    def test_build_messages_skills_injection(self, mock_list, mock_llm_provider):
        """System prompt should render with skills via Jinja2 when prompt has a template."""
        from apps.agent.prompts import DynamicPrompt
        test_template = "Skills: {% for s in skills %}{{ s.name }}, {% endfor %}"
        mock_template = make_mock_template(test_template)
        prompt = DynamicPrompt('test', db_template=mock_template)
        mock_list.return_value = [
            {"name": "account-mgr", "description": "Manages accounts"},
        ]
        agent = ChatAgent(llm_provider=mock_llm_provider, prompt=prompt)
        # DynamicPrompt.requires_skills() inherits base default (True)
        messages = agent._build_messages(query='Help me')
        sys_msg = messages[0]['content']
        assert 'account-mgr' in sys_msg

    @patch('apps.integrations.skill.registry.SkillRegistry.list_skills_with_descriptions')
    def test_build_messages_skills_user_prompt(self, mock_list, mock_llm_provider):
        """User prompt should contain the query text with a prompt that requires skills."""
        from apps.agent.prompts import DynamicPrompt
        mock_template = make_mock_template("Test")
        prompt = DynamicPrompt('test', db_template=mock_template)
        mock_list.return_value = []
        agent = ChatAgent(llm_provider=mock_llm_provider, prompt=prompt)
        messages = agent._build_messages(query='How to pay?')
        user_msg = messages[-1]
        assert user_msg['role'] == 'user'
        assert 'How to pay?' in user_msg['content']

    def test_load_skills_calls_registry(self, mock_llm_provider):
        """_load_skills() should call registry (all prompts use requires_skills=True now)."""
        from apps.agent.prompts import DynamicPrompt
        mock_template = make_mock_template("Test")
        prompt = DynamicPrompt('test', db_template=mock_template)
        agent = ChatAgent(llm_provider=mock_llm_provider, prompt=prompt)
        # DynamicPrompt.requires_skills() inherits base default (True)
        assert agent._prompt.requires_skills() is True

    @patch('apps.integrations.skill.registry.SkillRegistry.list_skills_with_descriptions')
    def test_load_skills_returns_skills(self, mock_list, mock_llm_provider):
        """_load_skills() should return skills from registry."""
        from apps.agent.prompts import DynamicPrompt
        mock_list.return_value = [
            {"name": "skill-a", "description": "desc-a"},
        ]
        mock_template = make_mock_template("Test")
        prompt = DynamicPrompt('test', db_template=mock_template)
        agent = ChatAgent(llm_provider=mock_llm_provider, prompt=prompt)
        skills = agent._load_skills()
        assert len(skills) == 1
        assert skills[0]['name'] == 'skill-a'
        mock_list.assert_called_once()

"""
Tests for Integration modules.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.integrations.llm.base import BaseLLMProvider
from apps.integrations.rag.base import BaseRAGProvider
from apps.integrations.tool.base import BaseTool
from apps.integrations.skill.base import BaseSkill
from apps.integrations.memory.base import BaseMemory


class TestLLMProvider:
    """Test cases for LLM Provider integration."""
    
    def test_base_provider_is_abstract(self):
        """Test BaseLLMProvider cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseLLMProvider()
    
    @pytest.mark.asyncio
    async def test_openai_provider_initialization(self):
        """Test OpenAI provider can be initialized."""
        from apps.integrations.llm.openai_provider import OpenAIProvider

        provider = OpenAIProvider(
            api_key='test-key',
            api_base='https://api.openai.com/v1',
            model_name='gpt-4',
        )

        assert provider is not None
        assert provider.get_model_name() == 'gpt-4'
    
    @pytest.mark.asyncio
    async def test_ollama_provider_initialization(self):
        """Test Ollama provider can be initialized."""
        from apps.integrations.llm.ollama_provider import OllamaProvider

        provider = OllamaProvider(
            api_base='http://localhost:11434',
            model_name='llama2',
        )

        assert provider is not None
        assert provider.get_model_name() == 'llama2'


class TestRAGProvider:
    """Test cases for RAG Provider integration."""
    
    def test_base_rag_provider_is_abstract(self):
        """Test BaseRAGProvider cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseRAGProvider()


class TestToolIntegration:
    """Test cases for Tool integration."""
    
    def test_base_tool_is_abstract(self):
        """Test BaseTool cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseTool()
    
    def test_custom_tool_implementation(self):
        """Test custom tool can be implemented."""

        class TestTool(BaseTool):
            name = 'test_tool'

            @property
            def description(self) -> str:
                return 'A test tool'

            async def execute(self, input: str, context=None) -> str:
                return f'Executed with input: {input}'

        tool = TestTool()
        assert tool.name == 'test_tool'


class TestSkillIntegration:
    """Test cases for Skill integration."""
    
    def test_base_skill_is_abstract(self):
        """Test BaseSkill cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseSkill()
    
    def test_custom_skill_implementation(self):
        """Test custom skill can be implemented."""
        
        class TestSkill(BaseSkill):
            name = 'test_skill'
            description = 'A test skill'
            
            async def execute(self, input: str, context=None) -> str:
                return f'Skill executed with input: {input}'
        
        skill = TestSkill()
        assert skill.name == 'test_skill'


class TestMemoryIntegration:
    """Test cases for Memory integration."""
    
    def test_base_memory_is_abstract(self):
        """Test BaseMemory cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseMemory()
    
    @pytest.mark.asyncio
    async def test_conversation_memory(self):
        """Test ConversationMemory implementation."""
        from apps.integrations.memory.conversation import ConversationMemory

        memory = ConversationMemory(max_size=10)
        
        await memory.add({'role': 'user', 'content': 'Hello'})
        await memory.add({'role': 'assistant', 'content': 'Hi there!'})
        
        messages = await memory.get()
        assert len(messages) == 2
    
    @pytest.mark.asyncio
    async def test_memory_clear(self):
        """Test memory can be cleared."""
        from apps.integrations.memory.conversation import ConversationMemory
        
        memory = ConversationMemory()
        await memory.add({'role': 'user', 'content': 'Hello'})
        await memory.clear()
        
        messages = await memory.get()
        assert len(messages) == 0

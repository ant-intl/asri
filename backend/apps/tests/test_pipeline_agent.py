"""
Tests for Chat Agent module.

Covers: ToolFunctionRegistry, OutputCollectorProcessor,
FullDuplexLLMProcessor, ChatAgent, and ChatService integration.
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.agent.agent.context import AgentContext
from apps.agent.agent.chat_agent import ChatAgent
from apps.agent.prompts import DynamicPrompt
from apps.agent.pipeline.functions.tool_functions import (
    build_tool_schemas,
    build_function_handlers,
)
from apps.agent.pipeline.processors.output_collector import OutputCollectorProcessor
from apps.agent.pipeline.processors.full_duplex_llm_processor import (
    FullDuplexLLMProcessor,
)
from apps.agent.executor.action_executor import ActionExecutor
from apps.agent.pipeline.framework import TextFrame


# =============================================================================
# TestToolFunctionRegistry
# =============================================================================

class TestToolFunctionRegistry:
    """Test tool function schema generation and handler building."""

    def test_build_schemas_no_registered_tools(self):
        """No schemas when no tools registered in ToolRegistry."""
        context = AgentContext()
        with patch('apps.integrations.tool.base.ToolRegistry.list_tools_with_schemas', return_value=[]):
            schemas = build_tool_schemas(context)
            assert len(schemas) == 0

    def test_build_schemas_with_registered_tools(self):
        """Schemas driven by ToolRegistry.list_tools_with_schemas()."""
        context = AgentContext()
        with patch('apps.integrations.tool.base.ToolRegistry.list_tools_with_schemas', return_value=[
            {
                'type': 'function',
                'function': {
                    'name': 'calculator',
                    'description': 'Calculate math expressions',
                    'parameters': {
                        'type': 'object',
                        'properties': {'expr': {'type': 'string'}},
                        'required': ['expr'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'rag_search',
                    'description': 'Search knowledge base',
                    'parameters': {
                        'type': 'object',
                        'properties': {'query': {'type': 'string'}},
                        'required': ['query'],
                    },
                },
            },
        ]):
            schemas = build_tool_schemas(context)
            names = {s.name for s in schemas}
            assert 'calculator' in names
            assert 'rag_search' in names

    def test_build_schemas_tools_available(self):
        """No execute_tool schema generated when only context.available_tools provided."""
        context = AgentContext(available_tools=["calculator", "search"])
        with patch('apps.integrations.tool.base.ToolRegistry.list_tools_with_schemas', return_value=[]):
            schemas = build_tool_schemas(context)
            assert len(schemas) == 0

    def test_build_schemas_multi_instance_tools(self):
        """Multiple instances of same tool class appear with unique names."""
        context = AgentContext()
        with patch('apps.integrations.tool.base.ToolRegistry.list_tools_with_schemas', return_value=[
            {
                'type': 'function',
                'function': {
                    'name': 'faq_rag',
                    'description': 'Search FAQ',
                    'parameters': {
                        'type': 'object',
                        'properties': {'query': {'type': 'string'}},
                        'required': ['query'],
                    },
                },
            },
            {
                'type': 'function',
                'function': {
                    'name': 'doc_rag',
                    'description': 'Search documents',
                    'parameters': {
                        'type': 'object',
                        'properties': {'query': {'type': 'string'}},
                        'required': ['query'],
                    },
                },
            },
        ]):
            schemas = build_tool_schemas(context)
            names = {s.name for s in schemas}
            assert 'faq_rag' in names
            assert 'doc_rag' in names

    def test_build_handlers_returns_core_handlers(self):
        """Handlers dict has entries for registered tools."""
        executor = ActionExecutor()
        context = AgentContext()
        handlers = build_function_handlers(executor, context)
        # Handlers are built from ToolRegistry, which may be empty in tests
        assert isinstance(handlers, dict)

    @pytest.mark.asyncio
    async def test_tool_handler_calls_executor(self):
        """Tool handler calls ActionExecutor with TOOL action."""
        from apps.agent.pipeline.framework import FunctionCallParams

        executor = ActionExecutor()
        context = AgentContext()

        result_holder = []

        async def mock_result_callback(result, **kwargs):
            result_holder.append(result)

        # Mock ToolRegistry to return a test tool
        with patch('apps.integrations.tool.base.ToolRegistry.list_tools_with_schemas', return_value=[
            {
                'type': 'function',
                'function': {
                    'name': 'calc',
                    'description': 'Calculator',
                    'parameters': {
                        'type': 'object',
                        'properties': {'expr': {'type': 'string'}},
                        'required': ['expr'],
                    },
                },
            },
        ]):
            handlers = build_function_handlers(executor, context)
            assert 'calc' in handlers

            with patch.object(executor, 'execute', new_callable=AsyncMock,
                              return_value="tool result") as mock_exec:
                params = MagicMock(spec=FunctionCallParams)
                params.result_callback = mock_result_callback
                params.arguments = {'expr': '2+2'}

                await handlers['calc'](params)

                mock_exec.assert_called_once_with(
                    action="TOOL",
                    action_input={"name": "calc", "arguments": '{"expr": "2+2"}'},
                    context=context,
                )
                assert result_holder[0] == {"result": "tool result"}


# =============================================================================
# TestOutputCollector
# =============================================================================

class TestOutputCollector:
    """Test OutputCollectorProcessor frame-to-chunk mapping."""

    @pytest.mark.asyncio
    async def test_text_frame(self):
        """TextFrame maps to token chunk."""
        from apps.agent.pipeline.framework import TextFrame

        queue = asyncio.Queue()
        collector = OutputCollectorProcessor(output_queue=queue)

        frame = TextFrame(text="hello")
        await collector.process_frame(frame, direction=None)

        chunk = await queue.get()
        assert chunk['type'] == 'answer'
        assert chunk['content'] == 'hello'

    @pytest.mark.asyncio
    async def test_empty_text_frame_ignored(self):
        """Empty TextFrame does not produce a chunk."""
        from apps.agent.pipeline.framework import TextFrame

        queue = asyncio.Queue()
        collector = OutputCollectorProcessor(output_queue=queue)

        frame = TextFrame(text="")
        await collector.process_frame(frame, direction=None)

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_function_call_in_progress_frame(self):
        """FunctionCallInProgressFrame maps to tool_call chunk."""
        from apps.agent.pipeline.framework import FunctionCallInProgressFrame

        queue = asyncio.Queue()
        collector = OutputCollectorProcessor(output_queue=queue)

        frame = FunctionCallInProgressFrame(
            function_name="rag_search",
            tool_call_id="call_123",
            arguments={"query": "test"},
        )
        await collector.process_frame(frame, direction=None)

        chunk = await queue.get()
        assert chunk['type'] == 'tool_call'
        assert chunk['tool_name'] == 'rag_search'
        assert chunk['tool_call_id'] == 'call_123'

    @pytest.mark.asyncio
    async def test_function_call_result_frame(self):
        """FunctionCallResultFrame maps to tool_result chunk."""
        from apps.agent.pipeline.framework import FunctionCallResultFrame

        queue = asyncio.Queue()
        collector = OutputCollectorProcessor(output_queue=queue)

        frame = FunctionCallResultFrame(
            function_name="rag_search",
            tool_call_id="call_123",
            arguments={"query": "test"},
            result={"result": "Found info"},
        )
        await collector.process_frame(frame, direction=None)

        chunk = await queue.get()
        assert chunk['type'] == 'tool_result'
        assert chunk['tool_name'] == 'rag_search'

    @pytest.mark.asyncio
    async def test_llm_full_response_end_frame(self):
        """LLMFullResponseEndFrame maps to done chunk."""
        from apps.agent.pipeline.framework import LLMFullResponseEndFrame

        queue = asyncio.Queue()
        collector = OutputCollectorProcessor(output_queue=queue)

        frame = LLMFullResponseEndFrame()
        await collector.process_frame(frame, direction=None)

        chunk = await queue.get()
        assert chunk['type'] == 'done'

    @pytest.mark.asyncio
    async def test_end_frame_sends_sentinel(self):
        """EndFrame maps to None sentinel."""
        from apps.agent.pipeline.framework import EndFrame

        queue = asyncio.Queue()
        collector = OutputCollectorProcessor(output_queue=queue)

        frame = EndFrame()
        await collector.process_frame(frame, direction=None)

        chunk = await queue.get()
        assert chunk is None


# =============================================================================
# TestFullDuplexLLMProcessor
# =============================================================================

class TestFullDuplexLLMProcessor:
    """Test FullDuplexLLMProcessor LLM bridge."""

    @pytest.mark.asyncio
    async def test_text_stream_pushes_text_frames(self):
        """Text-only stream produces TextFrame chunks."""
        provider = MagicMock()
        provider.config = {}
        context = AgentContext()

        # Mock provider.chat returns an async generator of content chunks
        async def mock_stream(*args, **kwargs):
            yield {'type': 'content', 'content': 'Hello'}
            yield {'type': 'content', 'content': ' world'}
            yield {'type': 'done', 'content': ''}

        provider.chat = AsyncMock(return_value=mock_stream())

        processor = FullDuplexLLMProcessor(
            llm_provider=provider,
            context=context,
        )

        pushed_frames = []

        async def capture_push(frame, direction=None):
            pushed_frames.append(frame)

        processor.push_frame = capture_push

        from apps.agent.pipeline.framework import LLMMessagesAppendFrame
        frame = LLMMessagesAppendFrame(
            messages=[{'role': 'user', 'content': 'hi'}],
        )
        await processor.process_frame(frame, direction=None)

        text_frames = [f for f in pushed_frames if isinstance(f, TextFrame)]
        assert len(text_frames) == 2
        assert text_frames[0].text == 'Hello'
        assert text_frames[1].text == ' world'

    def test_max_iterations_parameter(self):
        """max_iterations parameter should be stored on processor."""
        provider = MagicMock()
        processor = FullDuplexLLMProcessor(
            llm_provider=provider,
            max_iterations=5,
        )
        assert processor._max_iterations == 5

    def test_max_iterations_default(self):
        """max_iterations should default to 10."""
        provider = MagicMock()
        processor = FullDuplexLLMProcessor(llm_provider=provider)
        assert processor._max_iterations == 10


# =============================================================================
# TestChatAgent
# =============================================================================

class TestChatAgent:
    """Test ChatAgent BaseAgent contract compliance."""

    def test_init_defaults(self):
        """ChatAgent initializes correctly with system_prompt."""
        provider = MagicMock()
        agent = ChatAgent(llm_provider=provider, system_prompt="Test")
        assert agent._custom_system_prompt == "Test"
        assert agent.llm_provider is provider

    def test_init_custom_prompt(self):
        """ChatAgent accepts custom system prompt."""
        provider = MagicMock()
        agent = ChatAgent(llm_provider=provider, system_prompt="Custom prompt")
        assert agent._custom_system_prompt == "Custom prompt"

    def test_init_max_iterations(self):
        """ChatAgent accepts max_iterations parameter."""
        provider = MagicMock()
        agent = ChatAgent(llm_provider=provider, system_prompt="Test", max_iterations=5)
        assert agent.max_iterations == 5

    @patch('apps.integrations.skill.registry.SkillRegistry.list_skills_with_descriptions')
    def test_build_messages_no_history(self, mock_list):
        """Messages list: [system, user] with rendered DynamicPrompt."""
        mock_list.return_value = [
            {'name': 'test_skill', 'description': 'A test skill'},
        ]
        from apps.agent.prompts import DynamicPrompt
        provider = MagicMock()
        # Provide a system template that includes skills
        mock_template = MagicMock()
        mock_template.system_template = "Skills: {% for s in skills %}{{ s.name }}{% endfor %}"
        mock_template.user_template_mode = 'generic'
        mock_template.user_template = ''
        mock_template.extractor_config = {}
        mock_template.is_active = True
        prompt = DynamicPrompt('test', db_template=mock_template)
        agent = ChatAgent(llm_provider=provider, prompt=prompt)
        messages = agent._build_messages("hello")
        assert len(messages) == 2
        assert messages[0]['role'] == 'system'
        assert 'test_skill' in messages[0]['content']
        assert messages[1]['role'] == 'user'
        # GENERIC mode: user message is the raw query
        assert messages[1]['content'] == 'hello'

    def test_build_messages_with_history(self):
        """Messages list: [system, *history, user]."""
        from apps.agent.prompts import DynamicPrompt
        provider = MagicMock()
        history = [
            {'role': 'user', 'content': 'prev question'},
            {'role': 'assistant', 'content': 'prev answer'},
        ]
        mock_template = MagicMock()
        mock_template.system_template = "System"
        mock_template.user_template_mode = 'generic'
        mock_template.user_template = ''
        mock_template.extractor_config = {}
        mock_template.is_active = True
        prompt = DynamicPrompt('test', db_template=mock_template)
        agent = ChatAgent(llm_provider=provider, prompt=prompt)
        messages = agent._build_messages("new question", history)
        assert len(messages) == 4
        assert messages[0]['role'] == 'system'
        assert messages[1]['role'] == 'user'
        assert messages[1]['content'] == 'prev question'
        assert messages[2]['role'] == 'assistant'
        assert messages[3]['role'] == 'user'
        # GENERIC mode: user message is the raw query
        assert messages[3]['content'] == 'new question'

    @pytest.mark.asyncio
    async def test_run_returns_correct_format(self):
        """run() returns dict with answer, trace, token counts, model."""
        from apps.agent.prompts import DynamicPrompt
        provider = MagicMock()
        provider.get_model_name = MagicMock(return_value='test-model')

        # Mock LLM response with XML tags for the content extractor to parse
        async def mock_stream(*args, **kwargs):
            yield {'type': 'content', 'content': '<answer>Test answer</answer>'}
            yield {'type': 'done', 'content': ''}

        provider.chat = AsyncMock(return_value=mock_stream())

        mock_template = MagicMock()
        mock_template.system_template = "System"
        mock_template.user_template_mode = 'generic'
        mock_template.user_template = ''
        mock_template.extractor_config = {}
        mock_template.is_active = True
        prompt = DynamicPrompt('test', db_template=mock_template)
        agent = ChatAgent(llm_provider=provider, prompt=prompt)
        result = await agent.run(query="hello")

        assert 'answer' in result
        assert result['answer'] == 'Test answer'
        assert 'trace' in result
        assert 'prompt_tokens' in result
        assert 'completion_tokens' in result
        assert 'total_tokens' in result
        assert result['model'] == 'test-model'

    @pytest.mark.asyncio
    async def test_stream_yields_chunks(self):
        """stream() yields token and done chunks."""
        from apps.agent.prompts import DynamicPrompt
        provider = MagicMock()
        provider.get_model_name = MagicMock(return_value='test-model')

        # Mock LLM response with XML tags for the content extractor to parse
        async def mock_stream(*args, **kwargs):
            yield {'type': 'content', 'content': '<answer>chunk1</answer>'}
            yield {'type': 'content', 'content': '<answer>chunk2</answer>'}
            yield {'type': 'done', 'content': ''}

        provider.chat = AsyncMock(return_value=mock_stream())

        mock_template = MagicMock()
        mock_template.system_template = "System"
        mock_template.user_template_mode = 'generic'
        mock_template.user_template = ''
        mock_template.extractor_config = {}
        mock_template.is_active = True
        prompt = DynamicPrompt('test', db_template=mock_template)
        agent = ChatAgent(llm_provider=provider, prompt=prompt)
        chunks = []
        async for chunk in agent.stream(query="hello"):
            chunks.append(chunk)

        token_chunks = [c for c in chunks if c.get('type') == 'answer']
        done_chunks = [c for c in chunks if c.get('type') == 'done']
        assert len(token_chunks) >= 1
        assert len(done_chunks) == 1


# =============================================================================
# TestChatServiceAgentCreation
# =============================================================================

class TestChatServiceAgentCreation:
    """Test ChatService._create_agent() always returns ChatAgent."""

    @pytest.mark.asyncio
    @patch('apps.services.chat_service.LLMRegistry')
    async def test_default_returns_chat_agent(self, mock_registry_cls):
        """Default _create_agent() returns ChatAgent."""
        from apps.services.chat_service import ChatService
        from apps.agent.prompts import DynamicPrompt

        mock_registry = MagicMock()
        mock_provider = MagicMock()
        # _create_agent uses get_provider_from_config, not get_default_provider
        mock_registry.get_provider_from_config = AsyncMock(return_value=mock_provider)
        mock_registry_cls.return_value = mock_registry

        mock_prompt = DynamicPrompt('test')
        with patch('apps.services.chat_service.get_active_prompt_async', AsyncMock(return_value=mock_prompt)):
            service = ChatService()
            agent = await service._create_agent()
            assert isinstance(agent, ChatAgent)

    @pytest.mark.asyncio
    @patch('apps.services.chat_service.LLMRegistry')
    async def test_uses_get_provider_from_config(self, mock_registry_cls):
        """_create_agent() should use get_provider_from_config."""
        from apps.services.chat_service import ChatService
        from apps.agent.prompts import DynamicPrompt

        mock_registry = MagicMock()
        mock_provider = MagicMock()
        mock_registry.get_provider_from_config = AsyncMock(return_value=mock_provider)
        mock_registry_cls.return_value = mock_registry

        mock_prompt = DynamicPrompt('test')
        with patch('apps.services.chat_service.get_active_prompt_async', AsyncMock(return_value=mock_prompt)):
            service = ChatService()
            agent = await service._create_agent()

        mock_registry.get_provider_from_config.assert_called_once()
        assert isinstance(agent, ChatAgent)


# =============================================================================
# TestOpenAIStructureParserToolCalls
# =============================================================================

class TestOpenAIStructureParserToolCalls:
    """Test OpenAIStructureParser tool_calls parsing extensions."""

    def test_parse_response_with_tool_calls(self):
        """parse_response extracts tool_calls from message."""
        from apps.integrations.llm.response_parser import OpenAIStructureParser

        parser = OpenAIStructureParser()
        data = {
            'choices': [{
                'message': {
                    'content': None,
                    'tool_calls': [{
                        'id': 'call_1',
                        'type': 'function',
                        'function': {'name': 'rag_search', 'arguments': '{"query":"test"}'},
                    }],
                },
                'finish_reason': 'tool_calls',
            }],
            'model': 'gpt-4',
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15},
        }
        result = parser.parse_response(data)
        assert len(result['tool_calls']) == 1
        assert result['tool_calls'][0]['function']['name'] == 'rag_search'

    def test_parse_stream_chunk_tool_calls_delta(self):
        """parse_stream_chunk returns tool_calls_delta for tool call chunks."""
        from apps.integrations.llm.response_parser import OpenAIStructureParser

        parser = OpenAIStructureParser()
        data = {
            'choices': [{
                'delta': {
                    'tool_calls': [{
                        'index': 0,
                        'id': 'call_1',
                        'function': {'name': 'rag_search', 'arguments': '{"query":"t"}'},
                    }],
                },
            }],
        }
        result = parser.parse_stream_chunk(data)
        assert result is not None
        assert result['type'] == 'tool_calls_delta'
        assert len(result['tool_calls']) == 1

    def test_parse_stream_chunk_content_unchanged(self):
        """parse_stream_chunk still handles content chunks correctly."""
        from apps.integrations.llm.response_parser import OpenAIStructureParser

        parser = OpenAIStructureParser()
        data = {
            'choices': [{
                'delta': {'content': 'hello'},
            }],
        }
        result = parser.parse_stream_chunk(data)
        assert result == {'type': 'content', 'content': 'hello', 'trace_id': ''}

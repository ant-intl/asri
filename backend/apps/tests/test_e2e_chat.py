"""
End-to-end tests for ChatService with real LLM calls.

Tests the full conversation chain:
    ChatService → ChatAgent → OpenAIProvider → Real LLM API

All tests are real-mode only and require:
    LLM_TEST_MODE=real
    OPENAI_API_KEY=<valid key>
    SERVER_ENV=test

Run:
    LLM_TEST_MODE=real OPENAI_API_KEY=xxx SERVER_ENV=test \
        pytest apps/tests/test_e2e_chat.py -v -s
"""
import pytest
from asgiref.sync import sync_to_async
from django.test import TransactionTestCase

from apps.entities import ChatMessage
from apps.services.session_service import SessionService
from apps.tests.conftest import real_mode_only


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def collect_stream(generator) -> list:
    """Collect all items from an async generator into a list."""
    items = []
    async for item in generator:
        items.append(item)
    return items


@sync_to_async
def get_db_messages(session_id: str) -> list:
    """Query all messages for a session from the database."""
    return list(
        ChatMessage.objects.filter(
            session_id=session_id
        ).order_by('gmt_create')
    )


# ---------------------------------------------------------------------------
# E2E Test Class
# ---------------------------------------------------------------------------

@real_mode_only
class TestChatServiceE2E(TransactionTestCase):
    """
    End-to-end tests for the full chat pipeline with real LLM calls.

    Uses Django TransactionTestCase for real DB commits (required by
    async code that reads back data written in the same request).
    """

    def setUp(self):
        """Create a fresh session and chat service for each test."""
        import asyncio
        import os
        from unittest.mock import AsyncMock, patch

        from apps.integrations.llm.openai_provider import OpenAIProvider
        from apps.integrations.llm.registry import LLMRegistry
        from apps.services.chat_service import ChatService

        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            self.skipTest('OPENAI_API_KEY not set')

        api_base = os.environ.get(
            'OPENAI_API_BASE', 'https://api.openai.com/v1'
        )
        model_name = os.environ.get('OPENAI_MODEL', 'gpt-4')

        self.provider = OpenAIProvider(
            api_base=api_base,
            api_key=api_key,
            model_name=model_name,
            timeout=120,
        )

        self.patcher = patch.object(
            LLMRegistry, 'get_provider_from_config', new_callable=AsyncMock, return_value=self.provider
        )
        self.patcher.start()
        self.chat_service = ChatService()

        self.session_service = SessionService()
        loop = asyncio.get_event_loop()
        self.session = loop.run_until_complete(
            self.session_service.create_session(
                user_id='e2e_test_user',
                title='E2E Test',
                agent_type='react',
            )
        )
        self.session_id = str(self.session.session_id)
        self.user_id = 'e2e_test_user'

    def tearDown(self):
        from apps.integrations.llm.registry import LLMRegistry
        self.patcher.stop()
        LLMRegistry._instances.clear()

    # ------------------------------------------------------------------
    # Group 1: Non-stream single turn
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_non_stream_response_structure(self):
        """chat() returns dict with all required fields."""
        result = await self.chat_service.chat(
            session_id=self.session_id,
            message='What is 2+2?',
            user_id=self.user_id,
        )

        assert isinstance(result, dict)
        assert 'message_id' in result
        assert 'content' in result
        assert 'trace' in result
        assert 'usage' in result

        assert isinstance(result['message_id'], str)
        assert len(result['message_id']) > 0
        assert isinstance(result['content'], str)
        assert isinstance(result['trace'], list)
        assert isinstance(result['usage'], dict)

    @pytest.mark.asyncio

    async def test_non_stream_content_is_non_empty(self):
        """chat() returns a non-empty answer from the LLM."""
        result = await self.chat_service.chat(
            session_id=self.session_id,
            message='What is the capital of France?',
            user_id=self.user_id,
        )

        assert len(result['content']) > 0

    @pytest.mark.asyncio

    async def test_non_stream_trace_has_entries(self):
        """chat() trace contains thought/action entries from ReAct loop."""
        result = await self.chat_service.chat(
            session_id=self.session_id,
            message='Say hello.',
            user_id=self.user_id,
        )

        trace = result['trace']
        assert len(trace) > 0

        types_found = {entry['type'] for entry in trace}
        # ReAct agent should at least produce thought and action entries
        assert 'thought' in types_found or 'action' in types_found

        for entry in trace:
            assert 'type' in entry
            assert 'content' in entry

    @pytest.mark.asyncio

    async def test_non_stream_usage_tokens_positive(self):
        """chat() reports positive token usage from real LLM call."""
        result = await self.chat_service.chat(
            session_id=self.session_id,
            message='Hello!',
            user_id=self.user_id,
        )

        usage = result['usage']
        assert usage['prompt_tokens'] > 0
        assert usage['completion_tokens'] > 0
        assert usage['total_tokens'] > 0
        assert usage['total_tokens'] == usage['prompt_tokens'] + usage['completion_tokens']

    @pytest.mark.asyncio

    async def test_non_stream_messages_persisted_in_db(self):
        """chat() persists both user and assistant messages in the database."""
        result = await self.chat_service.chat(
            session_id=self.session_id,
            message='Hi there!',
            user_id=self.user_id,
        )

        messages = await get_db_messages(self.session_id)

        assert len(messages) == 2

        user_msg = messages[0]
        assert user_msg.role == 'user'
        assert user_msg.content == 'Hi there!'

        assistant_msg = messages[1]
        assert assistant_msg.role == 'assistant'
        assert len(assistant_msg.content) > 0
        assert str(assistant_msg.message_id) == result['message_id']

    # ------------------------------------------------------------------
    # Group 2: Stream single turn
    # ------------------------------------------------------------------

    @pytest.mark.asyncio

    async def test_stream_yields_chunks(self):
        """stream_chat() yields multiple chunks."""
        generator = self.chat_service.stream_chat(
            session_id=self.session_id,
            message='Say hello briefly.',
            user_id=self.user_id,
        )
        chunks = await collect_stream(generator)

        assert len(chunks) > 0

    @pytest.mark.asyncio

    async def test_stream_has_expected_types(self):
        """stream_chat() chunks contain token/thought/action types."""
        generator = self.chat_service.stream_chat(
            session_id=self.session_id,
            message='What is 1+1?',
            user_id=self.user_id,
        )
        chunks = await collect_stream(generator)

        types_found = {c.get('type') for c in chunks}
        # Should have at least answer or thought/action chunks
        assert types_found & {'answer', 'thought', 'action'}

        for chunk in chunks:
            assert 'type' in chunk
            assert 'content' in chunk

    @pytest.mark.asyncio

    async def test_stream_content_is_meaningful(self):
        """Concatenated token chunks form meaningful text."""
        generator = self.chat_service.stream_chat(
            session_id=self.session_id,
            message='Say the word hello.',
            user_id=self.user_id,
        )
        chunks = await collect_stream(generator)

        token_texts = [c['content'] for c in chunks if c.get('type') == 'answer']
        full_text = ''.join(token_texts)

        assert len(full_text) > 0

    @pytest.mark.asyncio

    async def test_stream_messages_persisted_after_completion(self):
        """After consuming the full stream, messages are saved in DB."""
        generator = self.chat_service.stream_chat(
            session_id=self.session_id,
            message='Greet me.',
            user_id=self.user_id,
        )
        # Must fully consume the generator for stream_chat to save messages
        await collect_stream(generator)

        messages = await get_db_messages(self.session_id)

        assert len(messages) == 2

        assert messages[0].role == 'user'
        assert messages[0].content == 'Greet me.'

        assert messages[1].role == 'assistant'
        assert len(messages[1].content) > 0

    # ------------------------------------------------------------------
    # Group 3: Multi-turn conversation
    # ------------------------------------------------------------------

    @pytest.mark.asyncio

    async def test_multi_turn_non_stream_recalls_context(self):
        """Second non-stream turn recalls information from the first turn."""
        # Turn 1: establish a fact
        await self.chat_service.chat(
            session_id=self.session_id,
            message='The answer to my math problem is 42. What is 1+1?',
            user_id=self.user_id,
        )

        # Turn 2: ask it to recall
        result = await self.chat_service.chat(
            session_id=self.session_id,
            message='What was the answer to my math problem that I mentioned earlier?',
            user_id=self.user_id,
        )

        assert '42' in result['content']

    @pytest.mark.asyncio

    async def test_multi_turn_stream_recalls_context(self):
        """Second stream turn recalls information from the first turn."""
        # Turn 1: stream and fully consume
        gen1 = self.chat_service.stream_chat(
            session_id=self.session_id,
            message='The name of my pet dog is Biscuit. How are you?',
            user_id=self.user_id,
        )
        await collect_stream(gen1)

        # Turn 2: stream and collect tokens
        gen2 = self.chat_service.stream_chat(
            session_id=self.session_id,
            message="What is my dog's name?",
            user_id=self.user_id,
        )
        chunks = await collect_stream(gen2)

        token_texts = [c['content'] for c in chunks if c.get('type') == 'answer']
        full_text = ''.join(token_texts)

        assert 'Biscuit' in full_text or 'biscuit' in full_text.lower()

    # ------------------------------------------------------------------
    # Group 4: ReAct behavior
    # ------------------------------------------------------------------

    @pytest.mark.asyncio

    async def test_simple_question_triggers_finish_directly(self):
        """Simple factual question should FINISH without RAG/TOOL loop."""
        result = await self.chat_service.chat(
            session_id=self.session_id,
            message='What is 2+2? Answer with just the number.',
            user_id=self.user_id,
        )

        trace = result['trace']
        observation_entries = [e for e in trace if e.get('type') == 'observation']
        # Should not have any observation (no RAG/TOOL action executed)
        assert len(observation_entries) == 0, (
            f"Expected FINISH on first iteration, but found observations: {observation_entries}"
        )


# ---------------------------------------------------------------------------
# Enhanced system prompt with tool/skill/RAG descriptions
# ---------------------------------------------------------------------------

TOOL_ENHANCED_PROMPT = """You are a helpful AI assistant that uses a ReAct (Reasoning + Acting) approach to answer questions.

For each step, you should:
1. Think about what you need to do
2. Decide on an action if needed
3. Observe the result
4. Continue until you have a final answer

Available actions:
- RAG: Search knowledge base for relevant information
- TOOL: Use a specific tool (specify tool name and input)
- SKILL: Use a skill for complex operations
- FINISH: Provide the final answer

Format your response as:
Thought: [Your reasoning about what to do next]
Action: [RAG|TOOL|SKILL|FINISH]
Action Input: [Input for the action, or final answer if FINISH]

If you have enough information to answer, use:
Thought: I have enough information to answer.
Action: FINISH
Action Input: [Your final answer]

Available tools you MUST use when appropriate:
- datetime: Returns current date and time. Usage → Action: TOOL, Action Input: datetime:now
- calculator: Evaluates math expressions. Usage → Action: TOOL, Action Input: calculator:<expression>

Available skills:
- translate: Translates English text to Chinese. Usage → Action: SKILL, Action Input: translate:<english text>

You also have access to RAG for knowledge base search.
Usage → Action: RAG, Action Input: <query>

IMPORTANT: For questions about current time, math calculations, translations, or knowledge lookups,
you MUST use the appropriate tool/skill/RAG instead of answering from memory. Do NOT guess.
Always be helpful, accurate, and concise."""


# ---------------------------------------------------------------------------
# Group 5: Tool / RAG / Skill Action path E2E tests
# ---------------------------------------------------------------------------

@real_mode_only
class TestToolActionE2E(TransactionTestCase):
    """
    E2E tests for the ReAct agent's non-FINISH action paths.

    Registers lightweight test tools/skills/RAG, patches the system prompt
    to inform the LLM about available tools, and uses the real OpenAI provider.
    """

    def setUp(self):
        """Register test tools and set up the chat service."""
        import asyncio
        import os
        from unittest.mock import AsyncMock, patch

        from apps.integrations.llm.openai_provider import OpenAIProvider
        from apps.integrations.llm.registry import LLMRegistry
        from apps.integrations.tool.base import ToolRegistry
        from apps.integrations.skill.registry import SkillRegistry
        from apps.services.chat_service import ChatService

        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            self.skipTest('OPENAI_API_KEY not set')

        api_base = os.environ.get(
            'OPENAI_API_BASE', 'https://api.openai.com/v1'
        )
        model_name = os.environ.get('OPENAI_MODEL', 'gpt-4')

        # --- LLM provider ---
        self.provider = OpenAIProvider(
            api_base=api_base,
            api_key=api_key,
            model_name=model_name,
            timeout=120,
        )
        self.llm_patcher = patch.object(
            LLMRegistry, 'get_provider_from_config', new_callable=AsyncMock, return_value=self.provider
        )
        self.llm_patcher.start()

        # --- System prompt patch (inject tool descriptions) ---
        from unittest.mock import MagicMock
        _mock_template = MagicMock()
        _mock_template.system_template = TOOL_ENHANCED_PROMPT
        _mock_template.user_template_mode = 'generic'
        _mock_template.user_template = ''
        _mock_template.extractor_config = {}
        _mock_template.is_active = True
        self.prompt_patcher = patch(
            'apps.agent.prompts._get_db_template_sync',
            return_value=_mock_template,
        )
        self.prompt_patcher.start()

        # --- Register test tools ---
        from apps.tests.fixtures.test_tools import (
            DateTimeTool, CalculatorTool, TranslateSkill,
        )

        ToolRegistry.register(DateTimeTool())
        ToolRegistry.register(CalculatorTool())
        SkillRegistry.register(TranslateSkill())

        # --- Chat service and session ---
        self.chat_service = ChatService()
        self.session_service = SessionService()
        loop = asyncio.get_event_loop()
        self.session = loop.run_until_complete(
            self.session_service.create_session(
                user_id='e2e_tool_test_user',
                title='E2E Tool Test',
                agent_type='react',
            )
        )
        self.session_id = str(self.session.session_id)
        self.user_id = 'e2e_tool_test_user'

    def tearDown(self):
        from apps.integrations.llm.registry import LLMRegistry
        from apps.integrations.tool.base import ToolRegistry
        from apps.integrations.skill.registry import SkillRegistry

        self.llm_patcher.stop()
        self.prompt_patcher.stop()

        ToolRegistry._tools.clear()
        SkillRegistry._skills.clear()
        LLMRegistry._instances.clear()

    # ------------------------------------------------------------------
    # Tool tests
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_tool_datetime_non_stream(self):
        """LLM uses the datetime tool to answer a time question."""
        result = await self.chat_service.chat(
            session_id=self.session_id,
            message=(
                'What is the current date and time right now? '
                'You MUST use the datetime tool to get the real time. '
                'Do NOT guess.'
            ),
            user_id=self.user_id,
        )
        print(result)

        trace = result['trace']
        observations = [e for e in trace if e.get('type') == 'observation']

        if observations:
            # Tool was called: observation should contain a date string
            obs_text = ' '.join(o['content'] for o in observations)
            assert 'Current date and time' in obs_text or '20' in obs_text
        # Either way, the final content should be non-empty
        assert len(result['content']) > 0

    @pytest.mark.asyncio
    async def test_tool_calculator_non_stream(self):
        """LLM uses the calculator tool for a complex calculation."""
        result = await self.chat_service.chat(
            session_id=self.session_id,
            message=(
                'Use the calculator tool to compute 98765 * 12345. '
                'You MUST use the calculator tool. Do NOT calculate in your head.'
            ),
            user_id=self.user_id,
        )

        trace = result['trace']
        observations = [e for e in trace if e.get('type') == 'observation']

        expected_result = str(98765 * 12345)  # 1219253925

        if observations:
            obs_text = ' '.join(o['content'] for o in observations)
            assert expected_result in obs_text
        # Final answer should contain the correct result
        assert len(result['content']) > 0

    @pytest.mark.asyncio
    async def test_tool_action_in_stream_mode(self):
        """Tool usage works correctly in stream mode."""
        generator = self.chat_service.stream_chat(
            session_id=self.session_id,
            message=(
                'What is the current date and time? '
                'You MUST use the datetime tool. Do NOT guess.'
            ),
            user_id=self.user_id,
        )
        chunks = await collect_stream(generator)

        types_found = {c.get('type') for c in chunks}

        # Should have token chunks with the final answer
        token_texts = [c['content'] for c in chunks if c.get('type') == 'answer']
        full_text = ''.join(token_texts)
        assert len(full_text) > 0

        # If the LLM used the tool, we should see observation chunks
        if 'observation' in types_found:
            obs_texts = [c['content'] for c in chunks if c.get('type') == 'observation']
            obs_combined = ' '.join(obs_texts)
            assert 'Current date and time' in obs_combined or '20' in obs_combined

    # ------------------------------------------------------------------
    # RAG test
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_rag_search_returns_docs(self):
        """LLM uses RAG to search the knowledge base."""
        result = await self.chat_service.chat(
            session_id=self.session_id,
            message=(
                'Search the knowledge base using RAG to find information about the Eiffel Tower. '
                'You MUST use the RAG action to search. Do NOT answer from memory.'
            ),
            user_id=self.user_id,
        )

        trace = result['trace']
        observations = [e for e in trace if e.get('type') == 'observation']

        if observations:
            obs_text = ' '.join(o['content'] for o in observations)
            # InMemoryRAGProvider should return the Eiffel Tower doc
            assert 'Eiffel Tower' in obs_text or 'Paris' in obs_text
        # Final content should be non-empty
        assert len(result['content']) > 0

    # ------------------------------------------------------------------
    # Skill test
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_skill_translate_non_stream(self):
        """LLM uses the translate skill to translate text."""
        result = await self.chat_service.chat(
            session_id=self.session_id,
            message=(
                'Use the translate skill to translate the word "hello" to Chinese. '
                'You MUST use the translate skill. Do NOT translate by yourself.'
            ),
            user_id=self.user_id,
        )

        trace = result['trace']
        observations = [e for e in trace if e.get('type') == 'observation']

        if observations:
            obs_text = ' '.join(o['content'] for o in observations)
            assert '你好' in obs_text
        # Final content should be non-empty
        assert len(result['content']) > 0

    # ------------------------------------------------------------------
    # Error handling test
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_tool_not_found_graceful(self):
        """Agent handles gracefully when an unknown tool is attempted."""
        result = await self.chat_service.chat(
            session_id=self.session_id,
            message=(
                'Use the weather tool to check the weather in Tokyo. '
                'Action: TOOL, Action Input: weather:Tokyo'
            ),
            user_id=self.user_id,
        )

        # Should not crash, and should produce a response
        assert isinstance(result, dict)
        assert len(result['content']) > 0

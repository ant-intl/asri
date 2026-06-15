"""
Tests for prompt system.

Tests prompt creation, parsing, formatting, and observation handling
using create_prompt() via mocked DB templates.
"""
import sys
import types

import pytest
from unittest.mock import MagicMock, patch

from apps.agent.prompts import create_prompt, DynamicPrompt


def make_mock_template(
    system_template: str = "Test system prompt",
    mode: str = 'generic',
    user_template: str = '',
    extractor_config: dict = None,
):
    """Create a mock PromptTemplate object for testing."""
    template = MagicMock()
    template.system_template = system_template
    template.user_template_mode = mode
    template.user_template = user_template
    template.extractor_config = extractor_config or {}
    template.is_active = True
    return template


# ---------------------------------------------------------------------------
# Extractor configs used across multiple tests
# ---------------------------------------------------------------------------

REACT_EXTRACTOR_CONFIG = {
    'extractor': {
        'type': 'react',
    },
    'mapper': {
        'tool_keys': ['TOOL', 'RAG', 'tool'],
        'finish_keys': ['FINISH'],
        'think_keys': ['Thought'],
        'input_keys': ['Action Input'],
        'action_keys': ['Action'],
    },
}

SKILL_DECISION_EXTRACTOR_CONFIG = {
    'extractor': {
        'type': 'json',
        'action_key': 'action',
        'cot_key': 'cot',
        'content_key': 'content',
    },
    'mapper': {
        'tool_action': 'TOOL',
        'text_qa_action': 'TEXT_QA',
        'default_action': 'FINISH',
    },
}

INTERLEAVED_EXTRACTOR_CONFIG = {
    'extractor': {
        'type': 'xml_tags',
        'default_type': 'think',
    },
    'mapper': {
        'tool_keys': ['tool_call'],
        'think_keys': ['think'],
        'answer_keys': ['answer'],
    },
}


class TestPromptCreation:
    """Test prompt creation via create_prompt() with mocked DB."""

    def test_react_mode_returns_dynamic_prompt(self):
        """create_prompt('react') should return DynamicPrompt when DB has config."""
        mock_template = make_mock_template()
        with patch('apps.agent.prompts._get_db_template_sync', return_value=mock_template):
            prompt = create_prompt('react')
            assert isinstance(prompt, DynamicPrompt)
            assert prompt.prompt_name == 'react'

    def test_skill_decision_mode_returns_dynamic_prompt(self):
        """create_prompt('skill_decision') should return DynamicPrompt when DB has config."""
        mock_template = make_mock_template()
        with patch('apps.agent.prompts._get_db_template_sync', return_value=mock_template):
            prompt = create_prompt('skill_decision')
            assert isinstance(prompt, DynamicPrompt)
            assert prompt.prompt_name == 'skill_decision'

    def test_invalid_mode_raises_value_error(self):
        """Invalid prompt_mode should raise ValueError when DB has no config."""
        with patch('apps.agent.prompts._get_db_template_sync', return_value=None):
            with pytest.raises(ValueError, match='Unknown prompt mode'):
                create_prompt('invalid_nonexistent_mode')

    def test_any_mode_works_with_db_config(self):
        """Any arbitrary mode name works as long as a DB template exists."""
        mock_template = make_mock_template()
        with patch('apps.agent.prompts._get_db_template_sync', return_value=mock_template):
            prompt = create_prompt('my_custom_mode')
            assert isinstance(prompt, DynamicPrompt)
            assert prompt.prompt_name == 'my_custom_mode'


class TestDynamicPromptRendering:
    """Test DynamicPrompt.render() with various system templates."""

    def test_render_returns_system_template(self):
        """render() should return the system_template from DB."""
        mock_template = make_mock_template("My system prompt")
        prompt = DynamicPrompt('react', db_template=mock_template)
        result = prompt.render()
        assert result == "My system prompt"

    def test_render_with_jinja2_template(self):
        """render() should process Jinja2 expressions in system_template."""
        template_text = "Skills: {% for s in skills %}{{ s.name }}, {% endfor %}"
        mock_template = make_mock_template(template_text)
        prompt = DynamicPrompt('react', db_template=mock_template)
        skills = [{"name": "tool-a"}, {"name": "tool-b"}]
        result = prompt.render(skills=skills)
        assert "tool-a" in result
        assert "tool-b" in result

    def test_render_raises_if_no_template(self):
        """render() should raise RuntimeError if DB has no system_template."""
        mock_template = make_mock_template("")
        prompt = DynamicPrompt('react', db_template=mock_template)
        with pytest.raises(RuntimeError):
            prompt.render()

    def test_render_raises_if_no_db_template(self):
        """render() should raise RuntimeError if no DB template at all."""
        prompt = DynamicPrompt('react', db_template=None)
        with pytest.raises(RuntimeError):
            prompt.render()


class TestDynamicPromptFormatUserPrompt:
    """Test DynamicPrompt.format_user_prompt()."""

    def test_returns_query_when_no_user_template(self):
        """If DB has no user_template, format_user_prompt() should return query as-is."""
        mock_template = make_mock_template(user_template='')
        prompt = DynamicPrompt('react', db_template=mock_template)
        result = prompt.format_user_prompt(query='What is IBAN?')
        assert result == 'What is IBAN?'

    def test_renders_user_template_with_query(self):
        """If DB has user_template, it should be rendered with query."""
        user_tmpl = "<query>{{ query }}</query>"
        mock_template = make_mock_template(user_template=user_tmpl)
        prompt = DynamicPrompt('react', db_template=mock_template)
        result = prompt.format_user_prompt(query='What is IBAN?')
        assert '<query>What is IBAN?</query>' == result

    def test_user_template_with_skills(self):
        """User template can embed skills list."""
        user_tmpl = "{{ query }}{% for s in skills %} [{{ s.name }}]{% endfor %}"
        mock_template = make_mock_template(user_template=user_tmpl)
        prompt = DynamicPrompt('react', db_template=mock_template)
        skills = [{"name": "my-skill"}]
        result = prompt.format_user_prompt(query='Help', skills=skills)
        assert 'Help' in result
        assert '[my-skill]' in result


class TestDynamicPromptParseResponse:
    """Test DynamicPrompt.parse_response() delegates to OutputParserFactory."""

    def _make_prompt(self, extractor_config: dict) -> DynamicPrompt:
        mock_template = make_mock_template(extractor_config=extractor_config)
        return DynamicPrompt('test', db_template=mock_template)

    def _inject_fake_output_parser(self, action: str = '', action_input=None, thought: str = ''):
        """Inject a fake output_parser module so parse_response() can run.

        Returns the mock factory for assertion.
        """
        mock_extractor = MagicMock()
        mock_mapper = MagicMock()
        mock_extractor.extract.return_value = {}
        mock_mapper.map.return_value = {
            'tool_call': action,
            'tool_input': action_input or {},
            'think': thought,
        }
        mock_factory = MagicMock()
        mock_factory.create.return_value = (mock_extractor, mock_mapper)

        fake_mod = types.ModuleType('apps.agent.pipeline.output_parser')
        fake_mod.OutputParserFactory = mock_factory
        sys.modules['apps.agent.pipeline.output_parser'] = fake_mod
        return mock_factory

    def teardown_method(self, method):
        sys.modules.pop('apps.agent.pipeline.output_parser', None)

    def test_parse_delegates_to_output_parser_factory(self):
        """parse_response() passes extractor/mapper configs to OutputParserFactory."""
        prompt = self._make_prompt(INTERLEAVED_EXTRACTOR_CONFIG)
        response = '<answer>hello</answer>'

        mock_factory = self._inject_fake_output_parser()
        result = prompt.parse_response(response)

        mock_factory.create.assert_called_once_with(
            INTERLEAVED_EXTRACTOR_CONFIG['extractor'],
            INTERLEAVED_EXTRACTOR_CONFIG['mapper'],
        )
        assert result['raw'] == response

    def test_parse_tool_action_from_factory(self):
        """TOOL action from factory maps to result['action'] == 'TOOL'."""
        prompt = self._make_prompt(INTERLEAVED_EXTRACTOR_CONFIG)
        response = '<tool_call>{"name": "my-skill"}</tool_call>'

        self._inject_fake_output_parser(
            action='TOOL',
            action_input={'name': 'my-skill'},
            thought='需要调用技能',
        )
        result = prompt.parse_response(response)

        assert result['action'] == 'TOOL'
        assert result['thought'] == '需要调用技能'
        assert result['raw'] == response

    def test_parse_preserves_raw_response(self):
        """raw field always contains the original response string."""
        prompt = self._make_prompt(INTERLEAVED_EXTRACTOR_CONFIG)
        response = '<answer>hello</answer>'

        self._inject_fake_output_parser()
        result = prompt.parse_response(response)

        assert result['raw'] == response


class TestDynamicPromptObservation:
    """Test format_observation() — base class default behavior."""

    def test_default_observation_format(self):
        """Default format_observation should produce 'Observation: ...' user message."""
        mock_template = make_mock_template()
        prompt = DynamicPrompt('react', db_template=mock_template)
        msg = prompt.format_observation('search result')
        assert msg == {'role': 'user', 'content': 'Observation: search result'}

    def test_observation_with_empty_string(self):
        """Empty observation string should still produce correct format."""
        mock_template = make_mock_template()
        prompt = DynamicPrompt('react', db_template=mock_template)
        msg = prompt.format_observation('')
        assert msg == {'role': 'user', 'content': 'Observation: '}


class TestDynamicPromptRequiresSkills:
    """Test requires_skills() default behavior."""

    def test_requires_skills_returns_true_by_default(self):
        """DynamicPrompt inherits base default: requires_skills() is True."""
        mock_template = make_mock_template()
        prompt = DynamicPrompt('any_mode', db_template=mock_template)
        assert prompt.requires_skills() is True


class TestBaseHistoryConversion:
    """Test default history_to_prompt_format() and normalize_context_messages()."""

    def test_history_to_prompt_format_returns_copy(self):
        """Default history_to_prompt_format returns history unchanged."""
        mock_template = make_mock_template()
        prompt = DynamicPrompt('react', db_template=mock_template)
        history = [{'role': 'user', 'content': 'hi'}]
        result = prompt.history_to_prompt_format(history)
        assert result == history
        # Should be a copy, not the same list
        assert result is not history

    def test_history_to_prompt_format_empty(self):
        """Empty history returns empty list."""
        mock_template = make_mock_template()
        prompt = DynamicPrompt('react', db_template=mock_template)
        assert prompt.history_to_prompt_format([]) == []

    def test_normalize_context_messages_strips_system(self):
        """normalize_context_messages filters out system messages."""
        mock_template = make_mock_template()
        prompt = DynamicPrompt('react', db_template=mock_template)
        msgs = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'hi'},
            {'role': 'assistant', 'content': 'hello'},
        ]
        result = prompt.normalize_context_messages(msgs)
        assert len(result) == 2
        assert result[0]['role'] == 'user'
        assert result[1]['role'] == 'assistant'


class TestBuildMessagesGenericMode:
    """Test build_messages() in GENERIC and CUSTOM modes."""

    def test_build_messages_structure(self):
        """Generic mode: [system, *history, user]."""
        mock_template = make_mock_template("My system")
        prompt = DynamicPrompt('react', db_template=mock_template)
        history = [
            {'role': 'user', 'content': 'prev question'},
            {'role': 'assistant', 'content': 'prev answer'},
        ]
        messages = prompt.build_messages(query='follow up', history=history)
        assert len(messages) == 4  # system + 2 history + user
        assert messages[0] == {'role': 'system', 'content': 'My system'}
        assert messages[1] == {'role': 'user', 'content': 'prev question'}
        assert messages[2] == {'role': 'assistant', 'content': 'prev answer'}
        assert messages[3] == {'role': 'user', 'content': 'follow up'}

    def test_build_messages_no_history(self):
        """Without history: [system, user]."""
        mock_template = make_mock_template("System")
        prompt = DynamicPrompt('react', db_template=mock_template)
        messages = prompt.build_messages(query='Hello')
        assert len(messages) == 2
        assert messages[0]['role'] == 'system'
        assert messages[1] == {'role': 'user', 'content': 'Hello'}

    def test_build_messages_user_content_with_template(self):
        """In CUSTOM mode, user message is rendered via user_template from DB."""
        user_tmpl = "<query>{{ query }}</query>"
        # Must use 'custom' mode for user_template to take effect in build_messages
        mock_template = make_mock_template(mode='custom', user_template=user_tmpl)
        prompt = DynamicPrompt('react', db_template=mock_template)
        messages = prompt.build_messages(query='What is IBAN?')
        assert messages[-1]['content'] == '<query>What is IBAN?</query>'


class TestToolSchema:
    """Test BaseTool/BaseSkill.to_tool_schema() output format."""

    def test_tool_schema_with_parameters(self):
        """Tool with parameters_schema should include parameters in output."""
        from apps.integrations.tool.base import BaseTool

        class MockTool(BaseTool):
            name = 'test'
            description = 'A test tool'
            parameters_schema = {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "search query"},
                },
                "required": ["query"],
            }

            async def execute(self, input_text, context):
                return ''

        schema = MockTool().to_tool_schema()
        assert schema['type'] == 'function'
        assert schema['function']['name'] == 'test'
        assert schema['function']['description'] == 'A test tool'
        assert 'parameters' in schema['function']
        assert schema['function']['parameters']['required'] == ['query']

    def test_tool_schema_without_parameters(self):
        """Tool without parameters_schema should omit parameters key."""
        from apps.integrations.tool.base import BaseTool

        class SimpleTool(BaseTool):
            name = 'simple'
            description = 'No params'

            async def execute(self, input_text, context):
                return ''

        schema = SimpleTool().to_tool_schema()
        assert schema['function']['name'] == 'simple'
        assert 'parameters' not in schema['function']


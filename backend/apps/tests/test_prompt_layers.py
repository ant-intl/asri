"""
Tests for PromptTemplate.layers JSON field and layer-based prompt rendering.
"""
import json
import uuid

from django.test import TestCase

from apps.chatbot.models.prompt_template import PromptTemplate
from apps.agent.prompts.base import BaseSystemPrompt


# =============================================================================
# Model Tests (JSON field)
# =============================================================================

class TestPromptLayerModel(TestCase):
    """Tests for layers as a JSON field on PromptTemplate."""

    def setUp(self):
        self.template = PromptTemplate.objects.create(
            name='test_prompt',
            system_template='Base system template',
            is_active=True,
        )

    def test_layers_default_to_empty_list(self):
        """Test that a new template has an empty layers list."""
        assert self.template.layers == []

    def test_create_layer_via_json(self):
        """Test creating a layer by appending to the JSON field."""
        self.template.layers = [
            {
                'id': str(uuid.uuid4()),
                'name': 'test_layer',
                'description': 'A test layer',
                'target': 'system',
                'strategy': 'always',
                'template': 'You are a helpful assistant.',
                'order': 0,
                'is_active': True,
            }
        ]
        self.template.save()

        # Re-fetch from DB
        refreshed = PromptTemplate.objects.get(pk=self.template.pk)
        assert len(refreshed.layers) == 1
        assert refreshed.layers[0]['name'] == 'test_layer'
        assert refreshed.layers[0]['target'] == 'system'
        assert refreshed.layers[0]['strategy'] == 'always'

    def test_layer_ordering_in_json(self):
        """Test layers are ordered by target and order in Python code."""
        self.template.layers = [
            {
                'id': str(uuid.uuid4()), 'name': 'layer_b',
                'target': 'user', 'order': 2, 'template': 'b', 'is_active': True,
                'strategy': 'always',
            },
            {
                'id': str(uuid.uuid4()), 'name': 'layer_a',
                'target': 'user', 'order': 1, 'template': 'a', 'is_active': True,
                'strategy': 'always',
            },
            {
                'id': str(uuid.uuid4()), 'name': 'layer_c',
                'target': 'system', 'order': 0, 'template': 'c', 'is_active': True,
                'strategy': 'always',
            },
        ]
        self.template.save()

        active = [
            l for l in self.template.layers
            if l.get('is_active', True)
        ]
        active.sort(key=lambda l: (l.get('target', ''), l.get('order', 0)))

        assert active[0]['name'] == 'layer_c'   # system first
        assert active[1]['name'] == 'layer_a'   # user, order=1
        assert active[2]['name'] == 'layer_b'   # user, order=2

    def test_inactive_layer_excluded(self):
        """Test inactive layers are filtered out by default."""
        self.template.layers = [
            {
                'id': str(uuid.uuid4()), 'name': 'active_layer',
                'target': 'system', 'template': 'active', 'is_active': True,
                'strategy': 'always', 'order': 0,
            },
            {
                'id': str(uuid.uuid4()), 'name': 'inactive_layer',
                'target': 'system', 'template': 'inactive', 'is_active': False,
                'strategy': 'always', 'order': 1,
            },
        ]
        self.template.save()

        active = [
            l for l in self.template.layers
            if l.get('is_active', True)
        ]
        assert len(active) == 1
        assert active[0]['name'] == 'active_layer'

    def test_layers_persisted_in_db(self):
        """Test layers are stored and retrievable from the JSON field."""
        self.template.layers = [
            {
                'id': str(uuid.uuid4()), 'name': 'persist_test',
                'target': 'system', 'template': 'x', 'is_active': True,
                'strategy': 'always', 'order': 0,
            },
        ]
        self.template.save()

        pk = self.template.pk
        refreshed = PromptTemplate.objects.get(pk=pk)
        assert len(refreshed.layers) == 1
        assert refreshed.layers[0]['name'] == 'persist_test'


# =============================================================================
# Serialization Tests
# =============================================================================

class TestPromptLayerSerialization(TestCase):
    """Tests for serialize_template with layers."""

    def setUp(self):
        self.template = PromptTemplate.objects.create(
            name='ser_test', system_template='sys', is_active=True,
        )
        self.template.layers = [
            {
                'id': str(uuid.uuid4()), 'name': 'ser_layer',
                'target': 'system', 'strategy': 'always',
                'template': 'You are {{ name }}', 'order': 0, 'is_active': True,
            },
        ]
        self.template.save()

    def test_serialize_template_includes_layers(self):
        """Test serialize_template includes layers array."""
        from apps.api.prompt_template import serialize_template
        data = serialize_template(self.template)
        assert 'layers' in data
        assert len(data['layers']) == 1
        assert data['layers'][0]['name'] == 'ser_layer'

    def test_serialize_template_returns_system_template_directly(self):
        """Test system_template comes from the field, not derived."""
        from apps.api.prompt_template import serialize_template
        data = serialize_template(self.template)
        # system_template is the field value ('sys' from setUp), not derived
        assert data['system_template'] == 'sys'

    def test_serialize_template_system_template_fallback(self):
        """Test fallback to original system_template when no layers."""
        template2 = PromptTemplate.objects.create(
            name='ser_test2', system_template='Legacy template',
        )
        from apps.api.prompt_template import serialize_template
        data = serialize_template(template2)
        assert data['system_template'] == 'Legacy template'
        assert data['layers'] == []


# =============================================================================
# Layer Rendering Tests
# =============================================================================

class _TestPrompt(BaseSystemPrompt):
    """Concrete prompt subclass for testing."""

    @property
    def prompt_name(self) -> str:
        return 'test_layers'

    def _get_hardcoded_template(self) -> str:
        return ''

    def parse_response(self, response: str) -> dict:
        return {'thought': '', 'action': '', 'action_input': {}, 'raw': response}

    def format_user_prompt(self, query: str, **kwargs) -> str:
        return query


class TestLayerRendering(TestCase):
    """Tests for layer-based message building in BaseSystemPrompt."""

    def _add_layers(self, template: PromptTemplate, layers: list[dict]):
        template.layers = layers
        template.save()

    def setUp(self):
        self.template = PromptTemplate.objects.create(
            name='test_layers',
            system_template='{{ query }}',
            is_active=True,
        )
        self.prompt = _TestPrompt()

    def test_no_layers_falls_back_to_legacy(self):
        """Test that without layers, the legacy path is used."""
        messages = self.prompt.build_messages(query='hello')
        assert len(messages) == 2  # system + user
        assert messages[0]['role'] == 'system'
        assert messages[1]['role'] == 'user'
        assert messages[1]['content'] == 'hello'

    def test_system_always_layer(self):
        """Test system ALWAYS layer is always included."""
        self._add_layers(self.template, [
            {
                'id': str(uuid.uuid4()), 'name': 'sys_always',
                'target': 'system', 'strategy': 'always',
                'template': 'Core rules: be helpful.', 'order': 0, 'is_active': True,
            },
        ])
        messages = self.prompt.build_messages(query='hello')
        assert 'Core rules: be helpful.' in messages[0]['content']

    def test_system_first_turn_layer(self):
        """Test system FIRST_TURN layer only appears when tool_ans is empty."""
        self._add_layers(self.template, [
            {
                'id': str(uuid.uuid4()), 'name': 'sys_first',
                'target': 'system', 'strategy': 'first_turn',
                'template': 'First turn only.', 'order': 0, 'is_active': True,
            },
        ])
        # First turn: tool_ans is None
        messages = self.prompt.build_messages(query='hello', tool_ans=None)
        assert 'First turn only.' in messages[0]['content']

        # Subsequent turn: tool_ans is set
        messages2 = self.prompt.build_messages(query='hello', tool_ans=['result'])
        assert 'First turn only.' not in messages2[0]['content']

    def test_user_always_layer(self):
        """Test user ALWAYS layer is prepended to query."""
        self._add_layers(self.template, [
            {
                'id': str(uuid.uuid4()), 'name': 'user_always',
                'target': 'user', 'strategy': 'always',
                'template': 'User info: id=123', 'order': 0, 'is_active': True,
            },
        ])
        messages = self.prompt.build_messages(query='hello')
        assert len(messages) == 2  # system + user
        user_content = messages[1]['content']
        assert 'User info: id=123' in user_content
        assert 'hello' in user_content
        # Layer content should come before query
        assert user_content.index('User info: id=123') < user_content.index('hello')

    def test_user_first_turn_layer(self):
        """Test user FIRST_TURN layer only appears when history is empty."""
        self._add_layers(self.template, [
            {
                'id': str(uuid.uuid4()), 'name': 'user_first',
                'target': 'user', 'strategy': 'first_turn',
                'template': 'First conversation turn.', 'order': 0, 'is_active': True,
            },
        ])
        # First turn: empty history
        messages = self.prompt.build_messages(query='hello', history=[])
        user_content = messages[1]['content']
        assert 'First conversation turn.' in user_content

        # Subsequent turn: has history — layer injects into first historical user msg
        history = [{'role': 'user', 'content': 'previous question'},
                   {'role': 'assistant', 'content': 'previous answer'}]
        messages2 = self.prompt.build_messages(query='hello again', history=history)
        # Layer is in the first historical user message (messages[1])
        assert 'First conversation turn.' in messages2[1]['content']
        # Layer is NOT in the current user message (messages[-1])
        assert 'First conversation turn.' not in messages2[-1]['content']
        # Current user message is clean (no layer prefix)
        assert messages2[-1]['content'] == 'hello again'

    def test_user_layers_skipped_when_tool_ans(self):
        """Test user message (and thus user layers) are skipped when tool_ans is set."""
        self._add_layers(self.template, [
            {
                'id': str(uuid.uuid4()), 'name': 'user_always',
                'target': 'user', 'strategy': 'always',
                'template': 'User info', 'order': 0, 'is_active': True,
            },
        ])
        messages = self.prompt.build_messages(query='hello', tool_ans=['result'])
        assert len(messages) == 1  # only system message, no user message

    def test_multiple_layers_ordering(self):
        """Test multiple layers are rendered in order."""
        self._add_layers(self.template, [
            {
                'id': str(uuid.uuid4()), 'name': 'sys_a',
                'target': 'system', 'strategy': 'always',
                'template': 'Layer A', 'order': 1, 'is_active': True,
            },
            {
                'id': str(uuid.uuid4()), 'name': 'sys_b',
                'target': 'system', 'strategy': 'always',
                'template': 'Layer B', 'order': 0, 'is_active': True,
            },
        ])
        messages = self.prompt.build_messages(query='hello')
        content = messages[0]['content']
        # Layer B (order=0) should come before Layer A (order=1)
        assert content.index('Layer B') < content.index('Layer A')

    def test_layer_jinja2_rendering(self):
        """Test that layer templates support Jinja2 variables."""
        self._add_layers(self.template, [
            {
                'id': str(uuid.uuid4()), 'name': 'jinja_test',
                'target': 'system', 'strategy': 'always',
                'template': 'Hello {{ name }}!', 'order': 0, 'is_active': True,
            },
        ])
        messages = self.prompt.build_messages(query='hi', name='World')
        assert 'Hello World!' in messages[0]['content']

    def test_template_without_layers_still_works(self):
        """Test that templates without layers work exactly as before."""
        class _NoLayersPrompt(_TestPrompt):
            @property
            def prompt_name(self) -> str:
                return 'test_no_layers'

        PromptTemplate.objects.create(
            name='test_no_layers',
            system_template='You are {{ name }}.',
            is_active=True,
        )
        prompt = _NoLayersPrompt()
        messages = prompt.build_messages(query='hello', name='Bot')
        assert messages[0]['role'] == 'system'
        assert 'You are Bot.' in messages[0]['content']
        assert messages[1]['role'] == 'user'
        assert messages[1]['content'] == 'hello'


# =============================================================================
# API Backward Compatibility Tests
# =============================================================================

class TestPromptTemplateAPIBackwardCompat(TestCase):
    """Tests for backward compatibility: system_template ↔ layers."""

    def setUp(self):
        self.template = PromptTemplate.objects.create(
            name='bw_test', system_template='Original sys', is_active=True,
        )

    def test_create_with_system_template_preserves_it(self):
        """Test POST with system_template stores it directly (no auto-layer)."""
        response = self.client.post(
            '/chatbot/api/admin/prompt-templates/',
            data=json.dumps({
                'name': 'bw_new',
                'system_template': 'Hello {{ name }}',
            }),
            content_type='application/json',
        )
        assert response.status_code == 201
        data = json.loads(response.content)
        # system_template is stored directly
        assert data['system_template'] == 'Hello {{ name }}'
        # No auto-created _system_default layer
        assert data['layers'] == []

    def test_update_with_system_template_preserves_layers(self):
        """Test PUT with system_template does not alter layers."""
        response = self.client.put(
            f'/chatbot/api/admin/prompt-templates/{self.template.id}/',
            data=json.dumps({
                'system_template': 'Updated sys',
            }),
            content_type='application/json',
        )
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['system_template'] == 'Updated sys'
        # Layers stay as-is (no auto-creation)
        assert data['layers'] == []

    def test_update_with_layers_preserves_them(self):
        """Test PUT with explicit layers stores them alongside system_template."""
        layers = [
            {
                'id': str(uuid.uuid4()), 'name': 'custom_layer',
                'target': 'system', 'strategy': 'always',
                'template': 'Custom', 'order': 0, 'is_active': True,
            },
        ]
        response = self.client.put(
            f'/chatbot/api/admin/prompt-templates/{self.template.id}/',
            data=json.dumps({
                'system_template': 'System base',
                'layers': layers,
            }),
            content_type='application/json',
        )
        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['system_template'] == 'System base'
        assert len(data['layers']) == 1
        assert data['layers'][0]['name'] == 'custom_layer'
        assert data['layers'][0]['template'] == 'Custom'

    def test_serialize_returns_system_template_directly(self):
        """Test GET returns system_template from the field, not derived."""
        self.template.layers = [
            {
                'id': str(uuid.uuid4()), 'name': 'layer_a',
                'target': 'system', 'strategy': 'always',
                'template': 'Part A', 'order': 0, 'is_active': True,
            },
        ]
        self.template.save()

        response = self.client.get(
            f'/chatbot/api/admin/prompt-templates/{self.template.id}/'
        )
        assert response.status_code == 200
        data = json.loads(response.content)
        # system_template comes from the field directly
        assert data['system_template'] == 'Original sys'
        # layers are extra layers (no _system_default)
        assert len(data['layers']) == 1
        assert data['layers'][0]['name'] == 'layer_a'

    def test_system_default_filtered_in_serialization(self):
        """Test _system_default artifacts are filtered from serialized layers."""
        self.template.layers = [
            {
                'id': str(uuid.uuid4()), 'name': '_system_default',
                'target': 'system', 'strategy': 'always',
                'template': 'Some old content', 'order': 0, 'is_active': True,
            },
        ]
        self.template.save()

        response = self.client.get(
            f'/chatbot/api/admin/prompt-templates/{self.template.id}/'
        )
        assert response.status_code == 200
        data = json.loads(response.content)
        # _system_default filtered out
        assert data['layers'] == []
        # system_template still has original field value
        assert data['system_template'] == 'Original sys'

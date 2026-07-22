"""
Tests for VoiceAgentConfig model and API.

Covers:
- Model CRUD operations
- voice_settings JSON field storage/retrieval
- Active config uniqueness per tenant
- API endpoints (list, create, update, delete)
- DjangoConfigReader voice_settings integration
"""
import json
import sys
from pathlib import Path

import pytest
from django.test import TestCase

from apps.entities import VoiceAgentConfig
from apps.tenant.context import set_current_tenant_id, tenant_id_var

# Add voice/ to path so ``import asri_voice.xxx`` works in tests
_voice_pkg = str(Path(__file__).resolve().parents[3] / 'voice')
if _voice_pkg not in sys.path:
    sys.path.insert(0, _voice_pkg)


class TestVoiceAgentConfigModel(TestCase):
    """Tests for VoiceAgentConfig model."""

    def test_create_config(self):
        """Test creating a voice agent config."""
        config = VoiceAgentConfig.objects.create(
            name='test_config',
            voice_settings={
                'stt': {'backend': 'vadasr'},
                'tts': {'backend': 'omnivoice', 'base_url': 'http://localhost:18003'},
                'vad': {'thresh': 0.5, 'min_silence_ms': 500},
                'enable_barge_in': True,
            },
        )
        assert config.id is not None
        assert config.name == 'test_config'
        assert config.is_active is True
        assert config.voice_settings['stt']['backend'] == 'vadasr'
        assert config.voice_settings['tts']['base_url'] == 'http://localhost:18003'
        assert config.voice_settings['enable_barge_in'] is True

    def test_default_values(self):
        """Test default values for new config."""
        config = VoiceAgentConfig.objects.create(name='defaults')
        assert config.tenant_id == 'default'
        assert config.is_active is True
        assert config.voice_settings == {}

    def test_str_representation(self):
        """Test string representation."""
        config = VoiceAgentConfig.objects.create(
            name='my_config',
            tenant_id='tenant_a',
        )
        assert str(config) == 'VoiceAgentConfig(tenant_a/my_config)'

    def test_active_config_uniqueness(self):
        """Test that only one active config per tenant is allowed."""
        config1 = VoiceAgentConfig.objects.create(
            name='config1', tenant_id='default', is_active=True,
        )
        # Creating a second active config should deactivate the first
        config2 = VoiceAgentConfig.objects.create(
            name='config2', tenant_id='default', is_active=True,
        )
        config1.refresh_from_db()
        assert config1.is_active is False
        assert config2.is_active is True

    def test_multiple_tenants_independent(self):
        """Test that different tenants can have independent active configs."""
        config_a = VoiceAgentConfig.objects.create(
            name='config_a', tenant_id='tenant_a', is_active=True,
        )
        config_b = VoiceAgentConfig.objects.create(
            name='config_b', tenant_id='tenant_b', is_active=True,
        )
        # Both should remain active since they're in different tenants
        config_a.refresh_from_db()
        config_b.refresh_from_db()
        assert config_a.is_active is True
        assert config_b.is_active is True

    def test_voice_settings_json_roundtrip(self):
        """Test JSON serialization/deserialization of voice_settings."""
        settings = {
            'stt': {'backend': 'vadasr', 'vadasr_url': 'https://example.com/asr'},
            'tts': {'backend': 'omnivoice', 'base_url': 'http://localhost:18003', 'num_step': 32},
            'vad': {'thresh': 0.5, 'min_silence_ms': 500, 'min_speech_ms': 200},
            'enable_barge_in': True,
            'enable_heartbeat_interaction': False,
            'heartbeat': {'mode': 'streaming_asr', 'max_concurrent': 8},
        }
        config = VoiceAgentConfig.objects.create(
            name='json_test', voice_settings=settings,
        )
        config.refresh_from_db()
        assert config.voice_settings == settings
        assert config.voice_settings['vad']['thresh'] == 0.5
        assert config.voice_settings['heartbeat']['max_concurrent'] == 8

    def test_unique_constraint(self):
        """Test that tenant_id + name combination is unique."""
        VoiceAgentConfig.objects.create(
            name='dup_name', tenant_id='default',
        )
        with pytest.raises(Exception):
            VoiceAgentConfig.objects.create(
                name='dup_name', tenant_id='default',
            )


class TestVoiceAgentConfigAPI(TestCase):
    """Tests for VoiceAgentConfig API endpoints."""

    def setUp(self):
        self._tenant_token = set_current_tenant_id('default')
        self.config = VoiceAgentConfig.objects.create(
            name='api_test_config',
            tenant_id='default',
            voice_settings={
                'stt': {'backend': 'vadasr'},
                'tts': {'backend': 'omnivoice'},
                'enable_barge_in': True,
            },
        )

    def tearDown(self):
        tenant_id_var.reset(self._tenant_token)

    def test_list_configs(self):
        """Test GET /chatbot/api/admin/voice-agent-config/"""
        response = self.client.get('/chatbot/api/admin/voice-agent-config/')
        assert response.status_code == 200
        data = response.json()
        assert 'configs' in data
        assert len(data['configs']) >= 1
        assert data['configs'][0]['name'] == 'api_test_config'

    def test_get_config_detail(self):
        """Test GET .../voice-agent-config/<pk>/"""
        response = self.client.get(f'/chatbot/api/admin/voice-agent-config/{self.config.id}/')
        assert response.status_code == 200
        data = response.json()
        assert data['id'] == self.config.id
        assert data['name'] == 'api_test_config'
        assert data['voice_settings']['enable_barge_in'] is True

    def test_create_config(self):
        """Test POST .../voice-agent-config/"""
        response = self.client.post('/chatbot/api/admin/voice-agent-config/',
            data=json.dumps({
                'name': 'created_via_api',
                'voice_settings': {
                    'stt': {'backend': 'qwen3_asr'},
                    'tts': {'backend': 'omnivoice'},
                    'vad': {'thresh': 0.6},
                    'enable_barge_in': False,
                },
            }),
            content_type='application/json',
        )
        assert response.status_code == 201
        data = response.json()
        assert data['name'] == 'created_via_api'
        assert data['voice_settings']['vad']['thresh'] == 0.6

    def test_update_config(self):
        """Test PUT .../voice-agent-config/<pk>/"""
        response = self.client.put(f'/chatbot/api/admin/voice-agent-config/{self.config.id}/',
            data=json.dumps({
                'name': 'updated_name',
                'voice_settings': {
                    'stt': {'backend': 'qwen3_asr'},
                    'enable_barge_in': False,
                },
            }),
            content_type='application/json',
        )
        assert response.status_code == 200
        data = response.json()
        assert data['name'] == 'updated_name'
        assert data['voice_settings']['enable_barge_in'] is False
        assert data['voice_settings']['stt']['backend'] == 'qwen3_asr'

    def test_delete_config(self):
        """Test DELETE (deactivate) .../voice-agent-config/<pk>/"""
        response = self.client.delete(f'/chatbot/api/admin/voice-agent-config/{self.config.id}/')
        assert response.status_code == 200
        assert response.json()['success'] is True
        self.config.refresh_from_db()
        assert self.config.is_active is False

    def test_get_nonexistent_config(self):
        """Test GET with invalid pk returns 404."""
        response = self.client.get('/chatbot/api/admin/voice-agent-config/99999/')
        assert response.status_code == 404


class TestDjangoConfigReaderVoiceSettings(TestCase):
    """Tests for DjangoConfigReader voice_settings integration."""

    def setUp(self):
        self._tenant_token = set_current_tenant_id('default')
        # Pre-create a config for the read_all test
        self.test_config = VoiceAgentConfig.objects.create(
            name='reader_test',
            tenant_id='default',
            is_active=True,
            voice_settings={
                'stt': {'backend': 'vadasr'},
                'tts': {'backend': 'omnivoice', 'base_url': 'http://localhost:18003'},
                'vad': {'thresh': 0.6, 'min_silence_ms': 700},
                'enable_barge_in': False,
            },
        )

    def tearDown(self):
        tenant_id_var.reset(self._tenant_token)

    async def test_voice_settings_returned_in_read_all(self):
        """Test that read_all() includes voice_settings from VoiceAgentConfig."""
        from asri_voice.voice_django.django_config_reader import DjangoConfigReader

        reader = DjangoConfigReader(tenant_id='default')
        result = await reader.read_all()

        assert 'voice_settings' in result
        assert result['voice_settings']['vad']['thresh'] == 0.6
        assert result['voice_settings']['vad']['min_silence_ms'] == 700
        assert result['voice_settings']['enable_barge_in'] is False
        assert result['voice_settings']['tts']['base_url'] == 'http://localhost:18003'

    async def test_empty_voice_settings_when_no_config(self):
        """Test that read_all() returns empty voice_settings when no config exists."""
        from asri_voice.voice_django.django_config_reader import DjangoConfigReader

        reader = DjangoConfigReader(tenant_id='nonexistent_tenant')
        result = await reader.read_all()

        assert result['voice_settings'] == {}

    def test_apply_voice_settings_filters_old_format_keys(self):
        """Old-format STT keys with prefix (e.g. vadasr_url) should be filtered out."""
        from asri_voice.voice_django.django_config_reader import apply_django_config_to_handler_kwargs

        django_config = {
            'voice_settings': {
                'stt': {
                    'backend': 'vadasr',
                    'vadasr_url': 'https://old-format.example.com',  # old format
                    'vadasr_timeout': 99.0,  # old format
                    'url': 'https://new-format.example.com',  # new format
                    'timeout': 10.0,  # new format
                },
                'tts': {
                    'backend': 'omnivoice',
                    'omnivoice_tts_base_url': 'http://old:18003',  # old format
                    'base_url': 'http://new:18003',  # new format
                },
            },
        }
        handler_kwargs_map = {
            'vadasr': {'url': 'http://yaml-default.com', 'timeout': 5.0},
            'omnivoice_tts': {'base_url': 'http://yaml-default:18003'},
        }

        apply_django_config_to_handler_kwargs(django_config, handler_kwargs_map)

        # New-format keys should be applied
        assert handler_kwargs_map['vadasr']['url'] == 'https://new-format.example.com'
        assert handler_kwargs_map['vadasr']['timeout'] == 10.0
        # Old-format keys should NOT be in the kwargs
        assert 'vadasr_url' not in handler_kwargs_map['vadasr']
        assert 'vadasr_timeout' not in handler_kwargs_map['vadasr']

        # TTS: new-format applied, old-format filtered
        assert handler_kwargs_map['omnivoice_tts']['base_url'] == 'http://new:18003'
        assert 'omnivoice_tts_base_url' not in handler_kwargs_map['omnivoice_tts']

    def test_apply_voice_settings_to_handler_kwargs(self):
        """Test that voice_settings are mapped to handler kwargs."""
        from asri_voice.voice_django.django_config_reader import apply_django_config_to_handler_kwargs

        django_config = {
            'system_prompt': 'You are a voice assistant.',
            'voice_settings': {
                'vad': {'thresh': 0.6, 'min_silence_ms': 700},
                'tts': {'backend': 'omnivoice', 'base_url': 'http://localhost:9999'},
                'enable_barge_in': False,
                'enable_heartbeat_interaction': True,
            },
        }
        handler_kwargs_map = {
            'omnivoice_tts': {'base_url': 'http://old:18003'},
            'open_api': {'model_name': 'test'},
        }

        class MockVadKwargs:
            thresh = 0.3
            min_silence_ms = 300
            min_speech_ms = 200
            speech_pad_ms = 300
            sample_rate = 16000

        class MockModuleKwargs:
            enable_barge_in = True
            enable_heartbeat_interaction = False
            system_prompt_file = 'configs/prompt.txt'

        module_kwargs = MockModuleKwargs()
        vad_handler_kwargs = MockVadKwargs()
        apply_django_config_to_handler_kwargs(
            django_config, handler_kwargs_map, module_kwargs,
            vad_handler_kwargs=vad_handler_kwargs,
        )

        # VAD settings should be applied to vad_handler_kwargs
        assert vad_handler_kwargs.thresh == 0.6
        assert vad_handler_kwargs.min_silence_ms == 700

        # TTS settings should be overridden
        assert handler_kwargs_map['omnivoice_tts']['base_url'] == 'http://localhost:9999'

        # System prompt should be set and file path cleared
        assert handler_kwargs_map['open_api']['init_chat_prompt'] == 'You are a voice assistant.'
        assert module_kwargs.system_prompt_file is None

        # Behavior toggles should be overridden
        assert module_kwargs.enable_barge_in is False
        assert module_kwargs.enable_heartbeat_interaction is True
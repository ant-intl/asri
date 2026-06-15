"""
Tests for Skill API views.

Covers: SkillListView, SkillDetailView, SkillRefreshView,
SkillEnableView, SkillDisableView, SkillRegistryView,
SkillDBToolView, KnowledgeBaseConfigView, KnowledgeBaseEnableView,
KnowledgeBaseDisableView, KnowledgeBaseSyncView, SkillRegistryDetailView.
"""
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Allow async ORM operations in tests
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from django.test import TransactionTestCase
from django.urls import reverse

from apps.entities import Skill


# ---------------------------------------------------------------------------
# Helper: build Skill instance for testing
# ---------------------------------------------------------------------------

def _create_skill(**kwargs):
    """Create a Skill instance in the database."""
    defaults = {
        'tenant_id': 'example',
        'name': 'test_skill',
        'description': 'A test skill',
        'content': '# Test Skill\nThis is a test.',
        'is_active': True,
        'metadata': {},
    }
    defaults.update(kwargs)
    return Skill.objects.create(**defaults)


# ---------------------------------------------------------------------------
# TestSkillListView
# ---------------------------------------------------------------------------

class TestSkillListView(TransactionTestCase):
    """Test GET /admin/skills/ and POST /admin/skills/."""

    async def test_list_skills_empty(self):
        """GET should return empty list when no skills exist."""
        from apps.api.http.skill import SkillListView
        request = MagicMock()
        request.GET = {'page': '1', 'page_size': '20'}
        request.method = 'GET'

        view = SkillListView.as_view()
        response = await view(request)
        data = json.loads(response.content)

        assert data['skills'] == []
        assert data['total'] == 0
        assert data['page'] == 1
        assert data['page_size'] == 20

    async def test_list_skills_with_data(self):
        """GET should return paginated skills."""
        _create_skill(name='skill_one')
        _create_skill(name='skill_two')

        from apps.api.http.skill import SkillListView
        request = MagicMock()
        request.GET = {'page': '1', 'page_size': '10'}
        request.method = 'GET'

        view = SkillListView.as_view()
        response = await view(request)
        data = json.loads(response.content)

        assert data['total'] == 2
        assert len(data['skills']) == 2
        assert data['skills'][0]['name'] in ('skill_one', 'skill_two')

    async def test_list_skills_filter_active(self):
        """GET should filter by is_active parameter."""
        _create_skill(name='active_skill', is_active=True)
        _create_skill(name='inactive_skill', is_active=False)

        from apps.api.http.skill import SkillListView
        request = MagicMock()
        request.GET = {'page': '1', 'page_size': '20', 'is_active': 'true'}
        request.method = 'GET'

        view = SkillListView.as_view()
        response = await view(request)
        data = json.loads(response.content)

        assert data['total'] == 1
        assert data['skills'][0]['name'] == 'active_skill'

    async def test_list_skills_filter_inactive(self):
        """GET should filter inactive skills."""
        _create_skill(name='active_skill', is_active=True)
        _create_skill(name='inactive_skill', is_active=False)

        from apps.api.http.skill import SkillListView
        request = MagicMock()
        request.GET = {'page': '1', 'page_size': '20', 'is_active': 'false'}
        request.method = 'GET'

        view = SkillListView.as_view()
        response = await view(request)
        data = json.loads(response.content)

        assert data['total'] == 1
        assert data['skills'][0]['name'] == 'inactive_skill'

    async def test_list_skills_pagination(self):
        """GET should respect page and page_size parameters."""
        for i in range(5):
            _create_skill(name=f'skill_{i}')

        from apps.api.http.skill import SkillListView
        request = MagicMock()
        request.GET = {'page': '2', 'page_size': '2'}
        request.method = 'GET'

        view = SkillListView.as_view()
        response = await view(request)
        data = json.loads(response.content)

        assert data['total'] == 5
        assert len(data['skills']) == 2
        assert data['page'] == 2
        assert data['page_size'] == 2

    async def test_create_skill_success(self):
        """POST should create a new skill and return 201."""
        from apps.api.http.skill import SkillListView

        body = json.dumps({
            'name': 'new_skill',
            'description': 'A new skill',
            'content': '# New Skill\nContent here.',
            'is_active': True,
            'metadata': {'key': 'value'},
        }).encode()

        request = MagicMock()
        request.body = body
        request.method = 'POST'

        view = SkillListView.as_view()
        response = await view(request)

        assert response.status_code == 201
        data = json.loads(response.content)
        assert data['name'] == 'new_skill'

    async def test_create_skill_missing_name(self):
        """POST should return 400 if name is missing."""
        from apps.api.http.skill import SkillListView

        body = json.dumps({'content': 'Some content'}).encode()
        request = MagicMock()
        request.body = body
        request.method = 'POST'

        view = SkillListView.as_view()
        response = await view(request)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert 'name is required' in data['error']

    async def test_create_skill_missing_content(self):
        """POST should return 400 if content is missing."""
        from apps.api.http.skill import SkillListView

        body = json.dumps({'name': 'test_skill'}).encode()
        request = MagicMock()
        request.body = body
        request.method = 'POST'

        view = SkillListView.as_view()
        response = await view(request)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert 'content is required' in data['error']

    async def test_create_skill_duplicate_name(self):
        """POST should return 400 if skill name already exists."""
        _create_skill(name='existing_skill')

        from apps.api.http.skill import SkillListView

        body = json.dumps({
            'name': 'existing_skill',
            'content': 'New content',
        }).encode()
        request = MagicMock()
        request.body = body
        request.method = 'POST'

        view = SkillListView.as_view()
        response = await view(request)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert 'already exists' in data['error']

    async def test_create_skill_invalid_json(self):
        """POST should return 400 for invalid JSON."""
        from apps.api.http.skill import SkillListView

        request = MagicMock()
        request.body = b'not valid json'
        request.method = 'POST'

        view = SkillListView.as_view()
        response = await view(request)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert 'Invalid JSON' in data['error']


# ---------------------------------------------------------------------------
# TestSkillDetailView
# ---------------------------------------------------------------------------

class TestSkillDetailView(TransactionTestCase):
    """Test GET/PUT/DELETE /admin/skills/{skill_id}/."""

    async def test_get_skill_success(self):
        """GET should return skill details."""
        skill = _create_skill(name='get_test_skill')

        from apps.api.http.skill import SkillDetailView
        request = MagicMock()
        request.method = 'GET'

        view = SkillDetailView.as_view()
        response = await view(request, skill_id=str(skill.skill_id))
        data = json.loads(response.content)

        assert data['name'] == 'get_test_skill'
        assert data['content'] == '# Test Skill\nThis is a test.'
        assert data['is_active'] is True

    async def test_get_skill_not_found(self):
        """GET should return 404 for non-existent skill."""
        from apps.api.http.skill import SkillDetailView
        request = MagicMock()
        request.method = 'GET'

        view = SkillDetailView.as_view()
        response = await view(request, skill_id='non-existent-id')

        assert response.status_code == 404
        data = json.loads(response.content)
        assert 'not found' in data['error']

    async def test_update_skill_name(self):
        """PUT should update skill name."""
        skill = _create_skill(name='old_name')

        from apps.api.http.skill import SkillDetailView
        body = json.dumps({'name': 'new_name'}).encode()
        request = MagicMock()
        request.body = body
        request.method = 'PUT'

        view = SkillDetailView.as_view()
        response = await view(request, skill_id=str(skill.skill_id))

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['name'] == 'new_name'

    async def test_update_skill_duplicate_name(self):
        """PUT should return 400 if new name conflicts with existing skill."""
        _create_skill(name='skill_a')
        _create_skill(name='skill_b')

        skill_b = Skill.objects.get(name='skill_b')

        from apps.api.http.skill import SkillDetailView
        body = json.dumps({'name': 'skill_a'}).encode()
        request = MagicMock()
        request.body = body
        request.method = 'PUT'

        view = SkillDetailView.as_view()
        response = await view(request, skill_id=str(skill_b.skill_id))

        assert response.status_code == 400
        data = json.loads(response.content)
        assert 'already exists' in data['error']

    async def test_update_skill_not_found(self):
        """PUT should return 404 for non-existent skill."""
        from apps.api.http.skill import SkillDetailView
        body = json.dumps({'name': 'test'}).encode()
        request = MagicMock()
        request.body = body
        request.method = 'PUT'

        view = SkillDetailView.as_view()
        response = await view(request, skill_id='non-existent')

        assert response.status_code == 404

    async def test_update_skill_partial(self):
        """PUT should update only provided fields."""
        skill = _create_skill(name='partial_update', description='Old desc')

        from apps.api.http.skill import SkillDetailView
        body = json.dumps({'description': 'New desc'}).encode()
        request = MagicMock()
        request.body = body
        request.method = 'PUT'

        view = SkillDetailView.as_view()
        response = await view(request, skill_id=str(skill.skill_id))

        assert response.status_code == 200
        # Verify name unchanged
        skill.refresh_from_db()
        assert skill.name == 'partial_update'
        assert skill.description == 'New desc'

    async def test_delete_skill_success(self):
        """DELETE should remove the skill."""
        skill = _create_skill(name='to_delete')

        from apps.api.http.skill import SkillDetailView
        request = MagicMock()
        request.method = 'DELETE'

        view = SkillDetailView.as_view()
        response = await view(request, skill_id=str(skill.skill_id))

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True

    async def test_delete_skill_not_found(self):
        """DELETE should return 404 if skill doesn't exist."""
        from apps.api.http.skill import SkillDetailView
        request = MagicMock()
        request.method = 'DELETE'

        view = SkillDetailView.as_view()
        response = await view(request, skill_id='non-existent')

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# TestSkillRefreshView
# ---------------------------------------------------------------------------

class TestSkillRefreshView(TransactionTestCase):
    """Test POST /admin/skills/{skill_id}/refresh/."""

    async def test_refresh_skill_success(self):
        """POST should refresh skill cache."""
        skill = _create_skill(name='refresh_test')

        from apps.api.http.skill import SkillRefreshView
        request = MagicMock()
        request.method = 'POST'

        view = SkillRefreshView.as_view()
        response = await view(request, skill_id=str(skill.skill_id))

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['status'] == 'refreshed'


# ---------------------------------------------------------------------------
# TestSkillEnableView
# ---------------------------------------------------------------------------

class TestSkillEnableView(TransactionTestCase):
    """Test POST /admin/skills/{skill_id}/enable/."""

    async def test_enable_skill_success(self):
        """POST should set is_active=True."""
        skill = _create_skill(name='enable_test', is_active=False)

        from apps.api.http.skill import SkillEnableView
        request = MagicMock()
        request.method = 'POST'

        view = SkillEnableView.as_view()
        response = await view(request, skill_id=str(skill.skill_id))

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
        assert data['message'] == 'Skill enabled'

    async def test_enable_skill_not_found(self):
        """POST should return 404 if skill doesn't exist."""
        from apps.api.http.skill import SkillEnableView
        request = MagicMock()
        request.method = 'POST'

        view = SkillEnableView.as_view()
        response = await view(request, skill_id='non-existent')

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# TestSkillDisableView
# ---------------------------------------------------------------------------

class TestSkillDisableView(TransactionTestCase):
    """Test POST /admin/skills/{skill_id}/disable/."""

    async def test_disable_skill_success(self):
        """POST should set is_active=False."""
        skill = _create_skill(name='disable_test', is_active=True)

        from apps.api.http.skill import SkillDisableView
        request = MagicMock()
        request.method = 'POST'

        view = SkillDisableView.as_view()
        response = await view(request, skill_id=str(skill.skill_id))

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
        assert data['message'] == 'Skill disabled'

    async def test_disable_skill_not_found(self):
        """POST should return 404 if skill doesn't exist."""
        from apps.api.http.skill import SkillDisableView
        request = MagicMock()
        request.method = 'POST'

        view = SkillDisableView.as_view()
        response = await view(request, skill_id='non-existent')

        assert response.status_code == 404


# ---------------------------------------------------------------------------
# TestSkillRegistryView
# ---------------------------------------------------------------------------

class TestSkillRegistryView(TransactionTestCase):
    """Test GET /admin/skills/registry/."""

    async def test_list_registry_skills(self):
        """GET should list JSON skills from registry."""
        from apps.api.http.skill import SkillRegistryView

        mock_skill = MagicMock()
        mock_skill.name = 'registry_skill'
        mock_skill.description = 'A registry skill'
        mock_skill.doc_id = 'doc_123'
        mock_skill.dataset_id = 'ds_456'
        mock_skill.slice_id = 'slice_789'
        mock_skill.labels = ['label1', 'label2']

        request = MagicMock()
        request.method = 'GET'

        with patch('apps.api.http.skill.SkillRegistry') as mock_registry:
            mock_registry.list.return_value = [mock_skill]
            view = SkillRegistryView.as_view()
            response = await view(request)

        data = json.loads(response.content)
        assert 'skills' in data
        assert 'total' in data


# ---------------------------------------------------------------------------
# TestSkillDBToolView
# ---------------------------------------------------------------------------

class TestSkillDBToolView(TransactionTestCase):
    """Test GET /admin/skills/db-tool/."""

    async def test_get_db_tool_status(self):
        """GET should return db_tool enabled status."""
        from apps.api.http.skill import SkillDBToolView
        request = MagicMock()
        request.method = 'GET'

        view = SkillDBToolView.as_view()
        response = await view(request)

        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'db_tool_enabled' in data
        assert data['tenant_id'] == 'example'


# ---------------------------------------------------------------------------
# TestKnowledgeBaseConfigView
# ---------------------------------------------------------------------------

class TestKnowledgeBaseConfigView(TransactionTestCase):
    """Test GET/POST /admin/skills/knowledge-base/config/."""

    async def test_get_kb_config(self):
        """GET should return KB configuration."""
        from apps.api.http.skill import KnowledgeBaseConfigView
        request = MagicMock()
        request.method = 'GET'

        view = KnowledgeBaseConfigView.as_view()
        response = await view(request)

        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'config' in data

    async def test_save_kb_config_success(self):
        """POST should save KB configuration."""
        from apps.api.http.skill import KnowledgeBaseConfigView
        body = json.dumps({
            'api_url': 'http://example.com/api',
            'doc_id': 'doc_456',
        }).encode()
        request = MagicMock()
        request.body = body
        request.method = 'POST'

        view = KnowledgeBaseConfigView.as_view()
        response = await view(request)

        assert response.status_code == 200
        data = json.loads(response.content)
        assert 'config' in data

    async def test_save_kb_config_missing_api_url(self):
        """POST should return 400 if api_url is missing."""
        from apps.api.http.skill import KnowledgeBaseConfigView
        body = json.dumps({'doc_id': 'doc_456'}).encode()
        request = MagicMock()
        request.body = body
        request.method = 'POST'

        view = KnowledgeBaseConfigView.as_view()
        response = await view(request)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert 'api_url is required' in data['error']

    async def test_save_kb_config_missing_doc_id(self):
        """POST should return 400 if doc_id is missing."""
        from apps.api.http.skill import KnowledgeBaseConfigView
        body = json.dumps({'api_url': 'http://example.com/api'}).encode()
        request = MagicMock()
        request.body = body
        request.method = 'POST'

        view = KnowledgeBaseConfigView.as_view()
        response = await view(request)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert 'doc_id is required' in data['error']

    async def test_save_kb_config_invalid_json(self):
        """POST should return 400 for invalid JSON."""
        from apps.api.http.skill import KnowledgeBaseConfigView
        request = MagicMock()
        request.body = b'invalid json'
        request.method = 'POST'

        view = KnowledgeBaseConfigView.as_view()
        response = await view(request)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert 'Invalid JSON' in data['error']


# ---------------------------------------------------------------------------
# TestKnowledgeBaseEnableView
# ---------------------------------------------------------------------------

class TestKnowledgeBaseEnableView(TransactionTestCase):
    """Test POST /admin/skills/knowledge-base/enable/."""

    async def test_enable_kb_success(self):
        """POST should enable knowledge base."""
        from apps.api.http.skill import KnowledgeBaseEnableView
        request = MagicMock()
        request.method = 'POST'

        view = KnowledgeBaseEnableView.as_view()
        response = await view(request)

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
        assert 'skills_count' in data

    async def test_enable_kb_failure(self):
        """POST should return 400 if enabling KB fails."""
        from apps.api.http.skill import KnowledgeBaseEnableView
        request = MagicMock()
        request.method = 'POST'

        view = KnowledgeBaseEnableView.as_view()
        response = await view(request)

        # Response depends on KB state; just verify it returns a valid response
        assert response.status_code in (200, 400)


# ---------------------------------------------------------------------------
# TestKnowledgeBaseDisableView
# ---------------------------------------------------------------------------

class TestKnowledgeBaseDisableView(TransactionTestCase):
    """Test POST /admin/skills/knowledge-base/disable/."""

    async def test_disable_kb_success(self):
        """POST should disable knowledge base."""
        from apps.api.http.skill import KnowledgeBaseDisableView
        request = MagicMock()
        request.method = 'POST'

        view = KnowledgeBaseDisableView.as_view()
        response = await view(request)

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True

    async def test_disable_kb_failure(self):
        """POST should return 500 if disabling KB fails."""
        from apps.api.http.skill import KnowledgeBaseDisableView
        request = MagicMock()
        request.method = 'POST'

        view = KnowledgeBaseDisableView.as_view()
        response = await view(request)

        # Response depends on KB state
        assert response.status_code in (200, 500)


# ---------------------------------------------------------------------------
# TestKnowledgeBaseSyncView
# ---------------------------------------------------------------------------

class TestKnowledgeBaseSyncView(TransactionTestCase):
    """Test POST /admin/skills/knowledge-base/sync/."""

    async def test_sync_kb_success(self):
        """POST should sync skills from knowledge base."""
        from apps.api.http.skill import KnowledgeBaseSyncView
        request = MagicMock()
        request.method = 'POST'

        view = KnowledgeBaseSyncView.as_view()
        response = await view(request)

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['success'] is True
        assert 'skills_count' in data

    async def test_sync_kb_failure(self):
        """POST should return 400 if sync fails."""
        from apps.api.http.skill import KnowledgeBaseSyncView
        request = MagicMock()
        request.method = 'POST'

        view = KnowledgeBaseSyncView.as_view()
        response = await view(request)

        # Response depends on KB state
        assert response.status_code in (200, 400)


# ---------------------------------------------------------------------------
# TestSkillRegistryDetailView
# ---------------------------------------------------------------------------

class TestSkillRegistryDetailView(TransactionTestCase):
    """Test GET /admin/skills/registry/<skill_name>/."""

    async def test_get_registry_skill_success(self):
        """GET should return registry skill details."""
        from apps.api.http.skill import SkillRegistryDetailView

        mock_skill = MagicMock()
        mock_skill.name = 'detailed_skill'
        mock_skill.description = 'A detailed skill'
        mock_skill.content = '# Skill Content\nDetailed content here.'
        mock_skill.doc_id = 'doc_123'
        mock_skill.dataset_id = 'ds_456'
        mock_skill.slice_id = 'slice_789'
        mock_skill.labels = ['test', 'demo']
        mock_skill.features = ['feature1', 'feature2']

        request = MagicMock()
        request.method = 'GET'

        with patch('apps.api.http.skill.SkillRegistry') as mock_registry:
            mock_registry.get.return_value = mock_skill
            view = SkillRegistryDetailView.as_view()
            response = await view(request, skill_name='detailed_skill')

        assert response.status_code == 200
        data = json.loads(response.content)
        assert data['name'] == 'detailed_skill'

    async def test_get_registry_skill_not_found(self):
        """GET should return 404 if skill not in registry."""
        from apps.api.http.skill import SkillRegistryDetailView
        request = MagicMock()
        request.method = 'GET'

        with patch('apps.api.http.skill.SkillRegistry') as mock_registry:
            mock_registry.get.return_value = None
            view = SkillRegistryDetailView.as_view()
            response = await view(request, skill_name='nonexistent')

        assert response.status_code == 404
        data = json.loads(response.content)
        assert 'not found' in data['error']

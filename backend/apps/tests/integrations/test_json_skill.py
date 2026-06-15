"""
Tests for JSONSkill, SkillLoader._parse_skill, and load_skills_for_tenant.
"""
import pytest
from unittest.mock import patch

from apps.integrations.skill.json_skill import JSONSkill, SkillLoader
from apps.integrations.skill.base import SkillRegistry


class TestJSONSkill:
    """Test cases for JSONSkill."""

    def test_json_skill_attributes(self):
        """JSONSkill should store name, description, and content."""
        skill = JSONSkill(
            name='test-skill',
            description='A test skill',
            content='# Skill Content\nStep 1: Do this',
        )
        assert skill.name == 'test-skill'
        assert skill.description == 'A test skill'
        assert skill.content.startswith('# Skill Content')

    @pytest.mark.asyncio
    async def test_json_skill_execute_returns_content(self):
        """execute() should return the full content."""
        content = '# My Skill\n\nname:my-skill\ndescription:does something\n\nDetailed instructions here.'
        skill = JSONSkill(name='my-skill', description='does something', content=content)

        result = await skill.execute('any input', context=None)
        assert result == content

    def test_json_skill_metadata_fields(self):
        """JSONSkill should store optional metadata fields."""
        skill = JSONSkill(
            name='test',
            description='desc',
            content='content',
            doc_id='doc-123',
            dataset_id='ds-456',
            slice_id='sl-789',
            labels=[{'key': 'MCP', 'value': 'tool1'}],
            features=['feature1'],
        )
        assert skill.doc_id == 'doc-123'
        assert skill.dataset_id == 'ds-456'
        assert skill.slice_id == 'sl-789'
        assert len(skill.labels) == 1
        assert len(skill.features) == 1


class TestSkillLoaderParseSkill:
    """Test cases for SkillLoader._parse_skill()."""

    def test_parse_valid_skill(self):
        """_parse_skill should return JSONSkill for valid items."""
        item = {
            'validStatus': 'VALID',
            'content': '\nname:account-manager\ndescription:Manages user accounts\n\nDetailed steps...',
            'title': 'Account Manager',
            'docId': 'doc1',
            'datasetId': 'ds1',
            'sliceId': 'sl1',
            'labels': [{'key': 'type', 'value': 'management'}],
            'features': ['account'],
        }
        skill = SkillLoader._parse_skill(item)
        assert skill is not None
        assert skill.name == 'account-manager'
        assert skill.description == 'Manages user accounts'
        assert skill.doc_id == 'doc1'

    def test_parse_invalid_status(self):
        """_parse_skill should return None for invalid status."""
        item = {
            'validStatus': 'INVALID',
            'content': '\nname:disabled\ndescription:Should not load\n',
            'title': 'Disabled',
        }
        assert SkillLoader._parse_skill(item) is None

    def test_parse_empty_content(self):
        """_parse_skill should return None for empty content."""
        item = {
            'validStatus': 'VALID',
            'content': '',
            'title': 'Empty',
        }
        assert SkillLoader._parse_skill(item) is None

    def test_parse_fallback_to_title(self):
        """_parse_skill should fallback to title when name: not in content."""
        item = {
            'validStatus': 'VALID',
            'content': 'No name field here, just plain text.',
            'title': 'Fallback Skill Title',
        }
        skill = SkillLoader._parse_skill(item)
        assert skill is not None
        assert skill.name == 'Fallback Skill Title'

    def test_parse_no_name_no_title(self):
        """_parse_skill should return None when neither name nor title available."""
        item = {
            'validStatus': 'VALID',
            'content': 'No name field here.',
            'title': '',
        }
        assert SkillLoader._parse_skill(item) is None

    def test_parse_extracts_description(self):
        """_parse_skill should extract description from content."""
        item = {
            'validStatus': 'VALID',
            'content': '## Skill\nname:my-skill\ndescription:A special one\n\nBody text.',
            'title': 'Fallback',
        }
        skill = SkillLoader._parse_skill(item)
        assert skill is not None
        assert skill.description == 'A special one'


class TestSkillRegistryExtended:
    """Test list_skills_with_descriptions() extension."""

    def setup_method(self):
        SkillRegistry._skills = {}

    def teardown_method(self):
        SkillRegistry._skills = {}

    def test_list_skills_with_descriptions(self):
        """Should return [{name, description}] for all registered skills."""
        from apps.integrations.skill.registry import SkillRegistry as ExtendedRegistry

        skill1 = JSONSkill(name='skill-a', description='Does A', content='...')
        skill2 = JSONSkill(name='skill-b', description='Does B', content='...')
        ExtendedRegistry.register(skill1)
        ExtendedRegistry.register(skill2)

        result = ExtendedRegistry.list_skills_with_descriptions()
        assert len(result) == 2
        names = {s['name'] for s in result}
        assert 'skill-a' in names
        assert 'skill-b' in names

    def test_list_skills_with_descriptions_empty(self):
        """Should return empty list when no skills registered."""
        from apps.integrations.skill.registry import SkillRegistry as ExtendedRegistry
        result = ExtendedRegistry.list_skills_with_descriptions()
        assert result == []


class TestSkillRegistryTenantScoped:
    """Test tenant-scoped skill registration and isolation."""

    def setup_method(self):
        SkillRegistry._skills = {}

    def teardown_method(self):
        SkillRegistry._skills = {}

    def test_register_with_tenant_id(self):
        """Skills registered with tenant_id are stored in tenant bucket."""
        skill = JSONSkill(name='tenant-skill', description='desc', content='...')
        SkillRegistry.register(skill, tenant_id='worldfirst')

        assert 'worldfirst' in SkillRegistry._skills
        assert 'tenant-skill' in SkillRegistry._skills['worldfirst']

    @patch('apps.tenant.context.get_current_tenant_id', return_value='worldfirst')
    def test_get_skill_tenant_scoped(self, mock_tid):
        """get_skill() returns skill from current tenant bucket only."""
        skill_wf = JSONSkill(name='payment', description='WF payment', content='wf')
        skill_hk = JSONSkill(name='payment', description='HK payment', content='hk')
        SkillRegistry.register(skill_wf, tenant_id='worldfirst')
        SkillRegistry.register(skill_hk, tenant_id='example_tenant')

        result = SkillRegistry.get_skill('payment')
        assert result is skill_wf
        assert result.description == 'WF payment'

    @patch('apps.tenant.context.get_current_tenant_id', return_value='example_tenant')
    def test_get_skill_different_tenant(self, mock_tid):
        """get_skill() returns the correct tenant's skill."""
        skill_wf = JSONSkill(name='payment', description='WF', content='wf')
        skill_hk = JSONSkill(name='payment', description='HK', content='hk')
        SkillRegistry.register(skill_wf, tenant_id='worldfirst')
        SkillRegistry.register(skill_hk, tenant_id='example_tenant')

        result = SkillRegistry.get_skill('payment')
        assert result is skill_hk

    @patch('apps.tenant.context.get_current_tenant_id', return_value='empty-tenant')
    def test_list_skills_no_fallback(self, mock_tid):
        """Tenant with no skills returns empty list, no fallback to global."""
        global_skill = JSONSkill(name='global-sk', description='global', content='...')
        SkillRegistry.register(global_skill, tenant_id=None)

        assert SkillRegistry.list_skills() == []
        assert SkillRegistry.get_skill('global-sk') is None

    @patch('apps.tenant.context.get_current_tenant_id', return_value=None)
    def test_default_tenant_uses_none_bucket(self, mock_tid):
        """When no tenant is set, None bucket is used."""
        skill = JSONSkill(name='default-skill', description='desc', content='...')
        SkillRegistry.register(skill)  # tenant_id defaults to None

        assert SkillRegistry.get_skill('default-skill') is skill
        assert 'default-skill' in SkillRegistry.list_skills()

    def test_clear_all(self):
        """clear() without arguments clears all tenant buckets."""
        SkillRegistry.register(
            JSONSkill(name='s1', description='', content=''), tenant_id=None
        )
        SkillRegistry.register(
            JSONSkill(name='s2', description='', content=''), tenant_id='wf'
        )
        SkillRegistry.clear()
        assert SkillRegistry._skills == {}

    def test_clear_specific_tenant(self):
        """clear(tenant_id) clears only that tenant's bucket."""
        SkillRegistry.register(
            JSONSkill(name='s1', description='', content=''), tenant_id=None
        )
        SkillRegistry.register(
            JSONSkill(name='s2', description='', content=''), tenant_id='wf'
        )
        SkillRegistry.clear(tenant_id='wf')
        assert 'wf' not in SkillRegistry._skills
        assert None in SkillRegistry._skills

    @patch('apps.tenant.context.get_current_tenant_id', return_value='wf')
    def test_list_skills_with_descriptions_tenant_scoped(self, mock_tid):
        """list_skills_with_descriptions returns only current tenant's skills."""
        from apps.integrations.skill.registry import SkillRegistry as ExtendedRegistry

        ExtendedRegistry.register(
            JSONSkill(name='global', description='G', content=''), tenant_id=None
        )
        ExtendedRegistry.register(
            JSONSkill(name='wf-skill', description='WF', content=''), tenant_id='wf'
        )

        result = ExtendedRegistry.list_skills_with_descriptions()
        assert len(result) == 1
        assert result[0]['name'] == 'wf-skill'


class TestLoadSkillsForTenant:
    """Test the unified load_skills_for_tenant dispatcher."""

    def setup_method(self):
        SkillRegistry._skills = {}

    def teardown_method(self):
        SkillRegistry._skills = {}

    def test_load_via_loader_callable(self):
        """SKILLS_LOADER triggers dynamic import and call."""
        from apps.integrations.skill.loader import load_skills_for_tenant

        mock_skills = [
            JSONSkill(name='loader-skill', description='from loader', content='c'),
        ]
        with patch(
            'apps.integrations.skill.loader.import_string',
            return_value=lambda: mock_skills,
        ):
            config = {'SKILLS_LOADER': 'some.module.load_skills'}
            count = load_skills_for_tenant(config, tenant_id='t2')

        assert count == 1
        assert 'loader-skill' in SkillRegistry._skills.get('t2', {})

    def test_no_config_returns_zero(self):
        """Empty config returns 0 without errors."""
        from apps.integrations.skill.loader import load_skills_for_tenant
        count = load_skills_for_tenant({}, tenant_id='empty')
        assert count == 0
        assert SkillRegistry._skills.get('empty') is None

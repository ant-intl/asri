"""
Tests for tenant authentication and data isolation.
"""
import hashlib

import pytest
from asgiref.sync import sync_to_async
from django.test import TestCase, TransactionTestCase

from apps.entities import (
    Tenant, ChatSession, ChatMessage, SessionContext,
    LLMProviderConfig, RAGProviderConfig, ToolConfig,
)
from apps.services.session_service import SessionService
from apps.tenant.context import set_current_tenant_id, tenant_id_var
from apps.tenant.registry import TenantRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class _TenantTestMixin:
    """Mixin that creates two tenants and resets contextvar after each test."""

    TENANT_A_ID = 'tenant_a'
    TENANT_A_TOKEN = 'token-aaa-111'
    TENANT_B_ID = 'tenant_b'
    TENANT_B_TOKEN = 'token-bbb-222'

    def setUp(self):
        super().setUp()
        Tenant.objects.create(
            tenant_id=self.TENANT_A_ID,
            name='Tenant A',
            token_hash=_hash(self.TENANT_A_TOKEN),
            config_json={'AGENT_MODE': 'react'},
            is_active=True,
        )
        Tenant.objects.create(
            tenant_id=self.TENANT_B_ID,
            name='Tenant B',
            token_hash=_hash(self.TENANT_B_TOKEN),
            config_json={'AGENT_MODE': 'pipeline'},
            is_active=True,
        )
        self._ctx_token = set_current_tenant_id(self.TENANT_A_ID)

    def tearDown(self):
        tenant_id_var.reset(self._ctx_token)
        super().tearDown()


# ---------------------------------------------------------------------------
# 1. Tenant Model Tests
# ---------------------------------------------------------------------------

class TestTenantModel(TestCase):
    """Tests for the Tenant model."""

    def test_create_tenant(self):
        t = Tenant.objects.create(
            tenant_id='demo',
            name='Demo Tenant',
            token_hash=_hash('demo-token'),
        )
        assert t.pk is not None
        assert t.tenant_id == 'demo'
        assert t.is_active is True

    def test_hash_token_static(self):
        raw = 'my-secret-token'
        assert Tenant.hash_token(raw) == _hash(raw)

    def test_tenant_id_unique(self):
        Tenant.objects.create(tenant_id='unique', name='A', token_hash=_hash('t1'))
        with pytest.raises(Exception):
            Tenant.objects.create(tenant_id='unique', name='B', token_hash=_hash('t2'))

    def test_token_hash_unique(self):
        h = _hash('same')
        Tenant.objects.create(tenant_id='x', name='X', token_hash=h)
        with pytest.raises(Exception):
            Tenant.objects.create(tenant_id='y', name='Y', token_hash=h)


# ---------------------------------------------------------------------------
# 2. TenantRegistry Tests
# ---------------------------------------------------------------------------

class TestTenantRegistry(_TenantTestMixin, TestCase):
    """Tests for the in-memory TenantRegistry."""

    def test_resolve_valid_token(self):
        reg = TenantRegistry()
        reg.force_reload()
        assert reg.get_tenant_id_by_token(self.TENANT_A_TOKEN) == self.TENANT_A_ID

    def test_resolve_invalid_token(self):
        reg = TenantRegistry()
        reg.force_reload()
        assert reg.get_tenant_id_by_token('bad-token') is None

    def test_get_config_merges_defaults(self):
        reg = TenantRegistry()
        reg.force_reload()
        cfg = reg.get_config(self.TENANT_A_ID)
        assert cfg.get('AGENT_MODE') == 'react'

    def test_get_config_no_tenant(self):
        """When tenant_id is None, returns settings.CHATBOT defaults."""
        reg = TenantRegistry()
        reg.force_reload()
        cfg = reg.get_config(None)
        assert isinstance(cfg, dict)

    def test_inactive_tenant_not_resolved(self):
        Tenant.objects.filter(tenant_id=self.TENANT_B_ID).update(is_active=False)
        reg = TenantRegistry()
        reg.force_reload()
        assert reg.get_tenant_id_by_token(self.TENANT_B_TOKEN) is None

    def test_reload_picks_up_changes(self):
        reg = TenantRegistry()
        reg.force_reload()
        # Create a new tenant after initial load
        new_token = 'token-new'
        Tenant.objects.create(
            tenant_id='new_t', name='New', token_hash=_hash(new_token),
        )
        # Before reload - not found
        assert reg.get_tenant_id_by_token(new_token) is None
        # After reload - found
        reg.force_reload()
        assert reg.get_tenant_id_by_token(new_token) == 'new_t'


# ---------------------------------------------------------------------------
# 3. HTTP Middleware Tests
# ---------------------------------------------------------------------------

class TestTokenAuthMiddleware(_TenantTestMixin, TestCase):
    """Tests for TokenAuthMiddleware via Django test client."""

    def _auth_header(self, token: str) -> dict:
        return {'HTTP_AUTHORIZATION': f'Bearer {token}'}

    def test_valid_token_returns_200(self):
        resp = self.client.get(
            '/chatbot/api/sessions/',
            {'user_id': 'u1'},
            **self._auth_header(self.TENANT_A_TOKEN),
        )
        assert resp.status_code == 200

    def test_missing_token_returns_401(self):
        resp = self.client.get('/chatbot/api/sessions/', {'user_id': 'u1'})
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self):
        resp = self.client.get(
            '/chatbot/api/sessions/',
            {'user_id': 'u1'},
            **self._auth_header('wrong-token'),
        )
        assert resp.status_code == 401

    def test_health_exempt(self):
        # Disable exception raising to check status code even if view errors
        self.client.raise_request_exception = False
        resp = self.client.get('/health_check/')
        # Health endpoint should not return 401
        assert resp.status_code != 401

    def test_frontend_path_exempt(self):
        """Frontend paths like /chat should not require authentication."""
        self.client.raise_request_exception = False
        resp = self.client.get('/chat')
        assert resp.status_code != 401


# ---------------------------------------------------------------------------
# 4. Data Isolation Tests
# ---------------------------------------------------------------------------

class TestDataIsolation(_TenantTestMixin, TestCase):
    """Tests for tenant data isolation across all models."""

    def test_session_isolation(self):
        """Sessions created by tenant A are invisible to tenant B."""
        ChatSession.objects.create(tenant_id=self.TENANT_A_ID, user_id='u1')
        ChatSession.objects.create(tenant_id=self.TENANT_B_ID, user_id='u1')

        a_sessions = ChatSession.objects.filter(tenant_id=self.TENANT_A_ID)
        b_sessions = ChatSession.objects.filter(tenant_id=self.TENANT_B_ID)
        assert a_sessions.count() == 1
        assert b_sessions.count() == 1

    def test_message_isolation(self):
        ChatMessage.objects.create(
            tenant_id=self.TENANT_A_ID, session_id='s1',
            role='user', content='Hello from A',
        )
        ChatMessage.objects.create(
            tenant_id=self.TENANT_B_ID, session_id='s1',
            role='user', content='Hello from B',
        )

        assert ChatMessage.objects.filter(tenant_id=self.TENANT_A_ID).count() == 1
        assert ChatMessage.objects.filter(tenant_id=self.TENANT_B_ID).count() == 1

    def test_session_context_isolation(self):
        SessionContext.objects.create(
            tenant_id=self.TENANT_A_ID, session_id='ctx_a',
            messages=[{'role': 'user', 'content': 'a'}],
        )
        SessionContext.objects.create(
            tenant_id=self.TENANT_B_ID, session_id='ctx_b',
            messages=[{'role': 'user', 'content': 'b'}],
        )

        assert SessionContext.objects.filter(tenant_id=self.TENANT_A_ID).count() == 1
        assert SessionContext.objects.filter(tenant_id=self.TENANT_B_ID).count() == 1

    def test_llm_provider_tenant_unique(self):
        """Same name allowed for different tenants; duplicate for same tenant fails."""
        LLMProviderConfig.objects.create(
            tenant_id=self.TENANT_A_ID, name='gpt4',
            provider_type='openai', model_name='gpt-4',
        )
        # Same name, different tenant - OK
        LLMProviderConfig.objects.create(
            tenant_id=self.TENANT_B_ID, name='gpt4',
            provider_type='openai', model_name='gpt-4',
        )
        # Same name, same tenant - FAIL
        with pytest.raises(Exception):
            LLMProviderConfig.objects.create(
                tenant_id=self.TENANT_A_ID, name='gpt4',
                provider_type='openai', model_name='gpt-4',
            )

    def test_rag_provider_tenant_unique(self):
        RAGProviderConfig.objects.create(
            tenant_id=self.TENANT_A_ID, name='rag1', provider_type='http',
        )
        RAGProviderConfig.objects.create(
            tenant_id=self.TENANT_B_ID, name='rag1', provider_type='http',
        )
        with pytest.raises(Exception):
            RAGProviderConfig.objects.create(
                tenant_id=self.TENANT_A_ID, name='rag1', provider_type='http',
            )

    def test_tool_config_tenant_unique(self):
        ToolConfig.objects.create(
            tenant_id=self.TENANT_A_ID, name='calc', tool_type='tool',
        )
        ToolConfig.objects.create(
            tenant_id=self.TENANT_B_ID, name='calc', tool_type='tool',
        )
        with pytest.raises(Exception):
            ToolConfig.objects.create(
                tenant_id=self.TENANT_A_ID, name='calc', tool_type='tool',
            )


# ---------------------------------------------------------------------------
# 5. SessionService Tenant Scoping Tests
# ---------------------------------------------------------------------------

class TestSessionServiceTenant(_TenantTestMixin, TransactionTestCase):
    """Tests that SessionService methods respect tenant_id from contextvar."""

    def setUp(self):
        super().setUp()
        self.service = SessionService()

    @pytest.mark.asyncio
    async def test_create_session_sets_tenant(self):
        session = await self.service.create_session(user_id='u1', title='T')
        assert session.tenant_id == self.TENANT_A_ID

    @pytest.mark.asyncio
    async def test_get_session_respects_tenant(self):
        session = await self.service.create_session(user_id='u1', title='T')
        # Reachable with correct tenant
        found = await self.service.get_session(str(session.session_id))
        assert found is not None

        # Switch to tenant B
        tok = set_current_tenant_id(self.TENANT_B_ID)
        try:
            not_found = await self.service.get_session(str(session.session_id))
            assert not_found is None
        finally:
            tenant_id_var.reset(tok)

    @pytest.mark.asyncio
    async def test_list_sessions_scoped(self):
        await self.service.create_session(user_id='u1', title='A1')
        await self.service.create_session(user_id='u1', title='A2')

        # Switch to tenant B and create one session
        tok = set_current_tenant_id(self.TENANT_B_ID)
        try:
            await self.service.create_session(user_id='u1', title='B1')
        finally:
            tenant_id_var.reset(tok)

        sessions, total = await self.service.list_sessions(user_id='u1')
        assert total == 2  # Only tenant A's sessions

    @pytest.mark.asyncio
    async def test_add_message_sets_tenant(self):
        session = await self.service.create_session(user_id='u1')
        msg = await self.service.add_message(
            session_id=str(session.session_id),
            role='user',
            content='Hello',
        )
        assert msg.tenant_id == self.TENANT_A_ID

    @pytest.mark.asyncio
    async def test_get_messages_scoped(self):
        session = await self.service.create_session(user_id='u1')
        sid = str(session.session_id)
        await self.service.add_message(session_id=sid, role='user', content='Hi')

        # Directly insert a message with tenant B (simulate cross-tenant)
        @sync_to_async
        def _insert_cross_tenant():
            ChatMessage.objects.create(
                tenant_id=self.TENANT_B_ID, session_id=sid,
                role='user', content='Intruder',
            )
        await _insert_cross_tenant()

        messages, total = await self.service.get_messages(session_id=sid)
        assert total == 1  # Only tenant A's message

    @pytest.mark.asyncio
    async def test_delete_session_cross_tenant_fails(self):
        session = await self.service.create_session(user_id='u1')
        sid = str(session.session_id)

        tok = set_current_tenant_id(self.TENANT_B_ID)
        try:
            result = await self.service.delete_session(sid)
            assert result is False
        finally:
            tenant_id_var.reset(tok)

    @pytest.mark.asyncio
    async def test_session_context_scoped(self):
        session = await self.service.create_session(user_id='u1')
        sid = str(session.session_id)

        await self.service.save_session_context(sid, [{'role': 'user', 'content': 'hi'}])
        ctx = await self.service.get_session_context(sid)
        assert len(ctx) == 1

        # Tenant B cannot see context
        tok = set_current_tenant_id(self.TENANT_B_ID)
        try:
            ctx_b = await self.service.get_session_context(sid)
            assert ctx_b == []  # empty - no context for B
        finally:
            tenant_id_var.reset(tok)

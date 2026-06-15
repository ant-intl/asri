"""
Snapshot service - create and manage session snapshots.

A snapshot freezes the complete agent configuration (LLM provider,
prompt template, skills, tools, RAG) at a point in time, allowing
sessions to be recreated with identical configuration or compared
side-by-side in the Playground.
"""
import asyncio
import json
import logging
from typing import List

from asgiref.sync import sync_to_async

from ..entities import (
    SessionSnapshot,
    ChatSession,
    Skill,
    ToolConfig,
    RAGProviderConfig,
    LLMProviderConfig,
)
from ..agent.prompts import get_active_prompt_async
from ..integrations.llm.registry import LLMRegistry
from ..tenant.context import get_current_tenant_id

logger = logging.getLogger(__name__)


def _ensure_tenant_id(tenant_id: str | None = None) -> str:
    """Return tenant_id or resolve from context."""
    if tenant_id:
        return tenant_id
    return get_current_tenant_id() or 'default'


# ── Sync helpers (wrapped for async usage) ──────────────────────────

@sync_to_async(thread_sensitive=False)
def _get_snapshot_by_id(snapshot_id: str, tenant_id: str) -> SessionSnapshot | None:
    """Fetch a single snapshot by ID (sync, for async wrapping)."""
    try:
        return SessionSnapshot.objects.get(id=snapshot_id, tenant_id=tenant_id, is_active=True)
    except SessionSnapshot.DoesNotExist:
        return None


@sync_to_async(thread_sensitive=False)
def _list_snapshots(
    tenant_id: str,
    page: int = 1,
    page_size: int = 20,
) -> tuple[List[SessionSnapshot], int]:
    """Paginated snapshot list (sync, for async wrapping)."""
    qs = SessionSnapshot.objects.filter(tenant_id=tenant_id, is_active=True)
    total = qs.count()
    offset = (page - 1) * page_size
    items = list(qs[offset:offset + page_size])
    return items, total


@sync_to_async(thread_sensitive=False)
def _create_snapshot(
    tenant_id: str,
    name: str,
    description: str,
    source_session_id: str | None,
    snapshot_data: dict,
    created_by: str,
) -> SessionSnapshot:
    """Persist a new snapshot (sync, for async wrapping)."""
    return SessionSnapshot.objects.create(
        tenant_id=tenant_id,
        name=name,
        description=description or '',
        source_session_id=source_session_id,
        snapshot_data=snapshot_data,
        created_by=created_by or '',
    )


@sync_to_async(thread_sensitive=False)
def _update_snapshot(
    snapshot_id: str,
    tenant_id: str,
    name: str | None = None,
    description: str | None = None,
) -> SessionSnapshot | None:
    """Update snapshot name/description (sync, for async wrapping)."""
    try:
        snap = SessionSnapshot.objects.get(id=snapshot_id, tenant_id=tenant_id)
    except SessionSnapshot.DoesNotExist:
        return None
    if name is not None:
        snap.name = name
    if description is not None:
        snap.description = description
    snap.save(update_fields=['name', 'description', 'gmt_modified'])
    return snap


@sync_to_async(thread_sensitive=False)
def _delete_snapshot(snapshot_id: str, tenant_id: str) -> bool:
    """Soft-delete a snapshot by setting is_active=False."""
    updated = SessionSnapshot.objects.filter(
        id=snapshot_id, tenant_id=tenant_id,
    ).update(is_active=False)
    return updated > 0


# ── SnapshotService ─────────────────────────────────────────────────


class SnapshotService:
    """Service for creating and managing session snapshots."""

    # ------------------------------------------------------------------
    # Capturing
    # ------------------------------------------------------------------

    @staticmethod
    async def _capture_llm_ref(session: ChatSession, tenant_id: str) -> dict | None:
        """Capture LLM provider reference from session or tenant config.

        Resolution priority (matches :meth:`LLMRegistry.get_provider_from_config`):
        1. ``session.llm_provider_id`` (forward-compat, currently never set)
        2. ``LLMProviderConfig`` with ``is_default=True`` for the tenant
        3. ``TenantRegistry`` model config (legacy tenant config fallback)
        """
        provider_id = session.llm_provider_id

        # 2. Try default LLMProviderConfig for this tenant
        if provider_id is None:
            try:
                @sync_to_async(thread_sensitive=False)
                def _get_default():
                    return LLMProviderConfig.objects.filter(
                        tenant_id=tenant_id, is_active=True, is_default=True,
                    ).first()

                default = await _get_default()
                if default:
                    provider_id = default.id
            except Exception:
                pass

        # If found via LLMProviderConfig, return reference
        if provider_id is not None:
            try:
                provider = await sync_to_async(
                    LLMProviderConfig.objects.get, thread_sensitive=False,
                )(id=provider_id, tenant_id=tenant_id)
                return {
                    'provider_config_id': provider.id,
                    'provider_type': provider.provider_type,
                    'model_name': provider.model_name,
                    'name': provider.name,
                }
            except LLMProviderConfig.DoesNotExist:
                pass

        # 3. Fall back to TenantRegistry model config (same as get_provider_from_config)
        try:
            from ..tenant.registry import get_tenant_registry
            registry = get_tenant_registry()
            model_config = registry.get_model_config(tenant_id)
            if model_config and model_config.get('provider_type'):
                return {
                    'provider_config_id': None,
                    'provider_type': model_config.get('provider_type'),
                    'model_name': model_config.get('model_name'),
                    'name': model_config.get('name') or model_config.get('model_name') or model_config.get('provider_type'),
                }
        except Exception:
            pass

        return None

    @staticmethod
    async def _capture_prompt(tenant_id: str) -> dict | None:
        """Capture active prompt template configuration.

        Uses the same resolution logic as ChatService._create_agent —
        ``get_active_prompt_async`` — to determine the active prompt
        template, then freezes all PromptTemplate fields so the prompt
        can be fully reconstructed at restore time.
        """
        try:
            prompt = await get_active_prompt_async(tenant_id)
            prompt_name = getattr(prompt, 'prompt_name', 'active')
            db_template = getattr(prompt, '_db_template', None)
            return {
                'prompt_id': str(db_template.id) if db_template else None,
                'name': prompt_name,
                'mode': prompt_name,
                'system_template': db_template.system_template if db_template else None,
                'user_template': db_template.user_template if db_template else None,
                'user_template_mode': db_template.user_template_mode if db_template else 'generic',
                'layers': db_template.layers if db_template else [],
                'extractor_config': prompt.get_extractor_config() if hasattr(prompt, 'get_extractor_config') else None,
            }
        except Exception as e:
            logger.warning("Failed to capture prompt for tenant '%s': %s", tenant_id, e)
            return None

    @staticmethod
    async def _capture_skills(tenant_id: str) -> list[dict]:
        """Capture active skills for the tenant."""
        skills = await sync_to_async(
            lambda: list(
                Skill.objects.filter(tenant_id=tenant_id, is_active=True).values(
                    'skill_id', 'name', 'description', 'content', 'metadata'
                )
            ),
            thread_sensitive=False,
        )()
        return skills or []

    @staticmethod
    async def _capture_tools(tenant_id: str) -> list[dict]:
        """Capture active tool configs for the tenant."""
        tools = await sync_to_async(
            lambda: list(
                ToolConfig.objects.filter(tenant_id=tenant_id, is_active=True).values(
                    'id', 'name', 'description', 'tool_type', 'parameters_schema', 'config_json'
                )
            ),
            thread_sensitive=False,
        )()
        return tools or []

    @staticmethod
    async def _capture_rag(tenant_id: str) -> list[dict]:
        """Capture active RAG providers for the tenant."""
        rags = await sync_to_async(
            lambda: list(
                RAGProviderConfig.objects.filter(tenant_id=tenant_id, is_active=True).values(
                    'id', 'name', 'provider_type', 'api_base', 'config_json'
                )
            ),
            thread_sensitive=False,
        )()
        return rags or []

    @classmethod
    async def capture_config(cls, session: ChatSession, tenant_id: str) -> dict:
        """Capture current configuration from a session into snapshot_data dict.

        This is the core capture logic, also usable standalone.
        """
        tenant_id = _ensure_tenant_id(tenant_id)

        llm_ref, prompt_cfg = await asyncio.gather(
            cls._capture_llm_ref(session, tenant_id),
            cls._capture_prompt(tenant_id),
        )

        skills, tools, rags = await asyncio.gather(
            cls._capture_skills(tenant_id),
            cls._capture_tools(tenant_id),
            cls._capture_rag(tenant_id),
        )

        return {
            'agent_type': session.agent_type or 'react',
            'llm_provider_ref': llm_ref,
            'prompt': prompt_cfg,
            'skills': skills,
            'tools': tools,
            'rag_providers': rags,
        }

    @classmethod
    async def create_from_session(
        cls,
        session: ChatSession,
        name: str,
        description: str = '',
        settings: dict | None = None,
        created_by: str = '',
        tenant_id: str | None = None,
    ) -> SessionSnapshot:
        """Create a snapshot from a session's current configuration.

        Args:
            session: The source ChatSession.
            name: Snapshot name.
            description: Optional description.
            settings: Optional runtime settings (interrupt strategy, connection type, etc.)
                      frozen alongside the agent configuration.
            created_by: Creator identifier.
            tenant_id: Tenant ID (resolved from context if not provided).

        Returns:
            The newly created SessionSnapshot instance.
        """
        tenant_id = _ensure_tenant_id(tenant_id)
        snapshot_data = await cls.capture_config(session, tenant_id)

        # Merge runtime settings into snapshot_data
        if settings:
            snapshot_data['settings'] = settings

        return await _create_snapshot(
            tenant_id=tenant_id,
            name=name,
            description=description,
            source_session_id=str(session.session_id),
            snapshot_data=snapshot_data,
            created_by=created_by,
        )

    # ------------------------------------------------------------------
    # Resolving frozen config
    # ------------------------------------------------------------------

    @classmethod
    async def get_frozen_config(
        cls,
        snapshot_id: str,
        tenant_id: str | None = None,
    ) -> dict | None:
        """Resolve a snapshot's frozen configuration into agent-ready parameters.

        Returns a dict with keys:
        - llm_provider: BaseLLMProvider instance
        - prompt_mode: str (prompt mode name)
        - system_prompt: str | None (frozen system template, if any)
        - extractor_config: dict | None
        - prompt_data: dict (full frozen prompt fields for DynamicPrompt.from_frozen)
        - skills: list[dict]
        - tools: list[dict]
        - rag_providers: list[dict]

        Returns None if the snapshot does not exist or is inactive.
        """
        tenant_id = _ensure_tenant_id(tenant_id)
        snap = await _get_snapshot_by_id(snapshot_id, tenant_id)
        if snap is None:
            return None

        data = snap.snapshot_data
        if isinstance(data, str):
            data = json.loads(data)

        # Reconstruct LLM provider from stored reference
        llm_provider = None
        llm_ref = data.get('llm_provider_ref') or {}
        provider_config_id = llm_ref.get('provider_config_id')
        if provider_config_id is not None:
            try:
                db_config = await sync_to_async(
                    LLMProviderConfig.objects.get, thread_sensitive=False,
                )(id=provider_config_id)
                config_dict = {
                    'provider_type': db_config.provider_type,
                    'api_base': db_config.api_base,
                    'api_key': db_config.api_key_encrypted,
                    'model_name': db_config.model_name,
                    'config': db_config.config_json or {},
                }
                llm_provider = LLMRegistry._create_from_config(config_dict)
            except (LLMProviderConfig.DoesNotExist, Exception) as e:
                logger.warning(
                    "Failed to resolve LLM provider %s for snapshot %s: %s",
                    provider_config_id, snapshot_id, e,
                )

        prompt_cfg = data.get('prompt') or {}
        prompt_mode = prompt_cfg.get('mode', 'skill_decision')
        settings = data.get('settings') or {}
        execution_mode = settings.get('execution_mode', 'interleaved')

        return {
            'llm_provider': llm_provider,
            'prompt_mode': prompt_mode,
            'execution_mode': execution_mode,
            'system_prompt': prompt_cfg.get('system_template'),
            'extractor_config': prompt_cfg.get('extractor_config'),
            'prompt_data': prompt_cfg,
            'skills': data.get('skills', []),
            'tools': data.get('tools', []),
            'rag_providers': data.get('rag_providers', []),
        }

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def list_snapshots(
        tenant_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict:
        """List snapshots with pagination.

        Returns:
            Dict with 'items' (list of dicts) and 'total' (int).
        """
        tenant_id = _ensure_tenant_id(tenant_id)
        items, total = await _list_snapshots(tenant_id, page=page, page_size=page_size)

        def _to_dict(s: SessionSnapshot) -> dict:
            return {
                'id': str(s.id),
                'name': s.name,
                'description': s.description,
                'source_session_id': s.source_session_id,
                'snapshot_data': s.snapshot_data,
                'tags': s.tags,
                'is_active': s.is_active,
                'created_by': s.created_by,
                'gmt_create': s.gmt_create.isoformat() if s.gmt_create else None,
                'gmt_modified': s.gmt_modified.isoformat() if s.gmt_modified else None,
            }

        return {
            'items': [_to_dict(s) for s in items],
            'total': total,
        }

    @staticmethod
    async def get_snapshot(
        snapshot_id: str,
        tenant_id: str | None = None,
    ) -> dict | None:
        """Get a single snapshot by ID."""
        tenant_id = _ensure_tenant_id(tenant_id)
        snap = await _get_snapshot_by_id(snapshot_id, tenant_id)
        if snap is None:
            return None
        return {
            'id': str(snap.id),
            'name': snap.name,
            'description': snap.description,
            'source_session_id': snap.source_session_id,
            'snapshot_data': snap.snapshot_data,
            'tags': snap.tags,
            'is_active': snap.is_active,
            'created_by': snap.created_by,
            'gmt_create': snap.gmt_create.isoformat() if snap.gmt_create else None,
            'gmt_modified': snap.gmt_modified.isoformat() if snap.gmt_modified else None,
        }

    @staticmethod
    async def update_snapshot(
        snapshot_id: str,
        tenant_id: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> dict | None:
        """Update snapshot name/description."""
        tenant_id = _ensure_tenant_id(tenant_id)
        snap = await _update_snapshot(snapshot_id, tenant_id, name=name, description=description)
        if snap is None:
            return None
        return {
            'id': str(snap.id),
            'name': snap.name,
            'description': snap.description,
            'gmt_modified': snap.gmt_modified.isoformat() if snap.gmt_modified else None,
        }

    @staticmethod
    async def delete_snapshot(
        snapshot_id: str,
        tenant_id: str | None = None,
    ) -> bool:
        """Soft-delete a snapshot."""
        tenant_id = _ensure_tenant_id(tenant_id)
        return await _delete_snapshot(snapshot_id, tenant_id)

    @staticmethod
    async def get_snapshot_config_preview(
        snapshot_id: str,
        tenant_id: str | None = None,
    ) -> dict | None:
        """Preview the resolved configuration for a snapshot (without creating an agent).

        Returns the snapshot_data enriched with resolved LLM provider info.
        """
        tenant_id = _ensure_tenant_id(tenant_id)
        snap = await _get_snapshot_by_id(snapshot_id, tenant_id)
        if snap is None:
            return None

        data = snap.snapshot_data
        if isinstance(data, str):
            data = json.loads(data)

        # Enrich with current LLM provider info (decrypts name etc.)
        llm_ref = data.get('llm_provider_ref') or {}
        provider_config_id = llm_ref.get('provider_config_id')
        resolved_llm = None
        if provider_config_id is not None:
            try:
                db_config = await sync_to_async(
                    LLMProviderConfig.objects.get, thread_sensitive=False,
                )(id=provider_config_id)
                resolved_llm = {
                    'id': db_config.id,
                    'provider_type': db_config.provider_type,
                    'model_name': db_config.model_name,
                    'name': db_config.name,
                }
            except LLMProviderConfig.DoesNotExist:
                resolved_llm = {'error': 'Provider config not found (may have been deleted)'}

        return {
            'id': str(snap.id),
            'name': snap.name,
            'description': snap.description,
            'source_session_id': snap.source_session_id,
            'snapshot_data': data,
            'resolved_llm': resolved_llm,
            'gmt_create': snap.gmt_create.isoformat() if snap.gmt_create else None,
        }

    # ------------------------------------------------------------------
    # Create agent from snapshot
    # ------------------------------------------------------------------

    @classmethod
    async def create_agent_from_snapshot(
        cls,
        snapshot_id: str,
        tenant_id: str | None = None,
    ):
        """Create a ChatAgent instance from a frozen snapshot configuration.

        This is the primary integration point with ChatService.
        Returns a (agent, frozen_config) tuple, or (None, None) if the
        snapshot cannot be resolved.

        The created agent fully honours frozen skills and tools from the
        snapshot by resolving full descriptions from the stored references
        before injecting them into the agent.
        """
        from ..agent.agent.chat_agent import ChatAgent

        frozen = await cls.get_frozen_config(snapshot_id, tenant_id)
        if frozen is None:
            return None, None

        llm_provider = frozen['llm_provider']
        if llm_provider is None:
            logger.error(
                "Cannot create agent from snapshot %s: LLM provider not resolvable",
                snapshot_id,
            )
            return None, frozen

        # Resolve full skill descriptions — prefer frozen data from snapshot
        full_skills = None
        frozen_skills = frozen.get('skills', [])
        if frozen_skills:
            if frozen_skills[0].get('content') is not None:
                # New snapshot: fully frozen skills
                full_skills = frozen_skills
                logger.info(
                    f"create_agent_from_snapshot: using {len(full_skills)} frozen skills "
                    f"from snapshot data"
                )
            else:
                # Legacy snapshot: only skill_id/name, resolve from live registry
                from ..integrations.skill.registry import SkillRegistry
                all_skills = SkillRegistry.list_skills_with_descriptions(
                    tenant_id=tenant_id,
                )
                skill_names = {s['name'] for s in frozen_skills}
                full_skills = [
                    s for s in all_skills if s['name'] in skill_names
                ]
                logger.info(
                    f"create_agent_from_snapshot: resolved {len(full_skills)} skills "
                    f"from live registry (legacy snapshot, {len(frozen_skills)} frozen refs)"
                )

        # Resolve full tool schemas — prefer frozen data from snapshot
        full_tools = None
        frozen_tools = frozen.get('tools', [])
        if frozen_tools:
            if frozen_tools[0].get('parameters_schema') is not None:
                # New snapshot: reconstruct tool schemas from frozen data
                full_tools = [
                    {
                        "type": "function",
                        "function": {
                            "name": t['name'],
                            "description": t.get('description', ''),
                            "parameters": t.get('parameters_schema', {}),
                        }
                    }
                    for t in frozen_tools
                ]
                logger.info(
                    f"create_agent_from_snapshot: reconstructed {len(full_tools)} tool schemas "
                    f"from frozen snapshot data"
                )
            else:
                # Legacy snapshot: only id/name/tool_type, resolve from live registry
                from ..integrations.tool.base import ToolRegistry
                all_tools = ToolRegistry.list_tools_with_schemas(
                    tenant_id=tenant_id,
                )
                tool_names = {t['name'] for t in frozen_tools}
                full_tools = [
                    t for t in all_tools
                    if t.get('function', {}).get('name') in tool_names
                ]
                logger.info(
                    f"create_agent_from_snapshot: resolved {len(full_tools)} tools "
                    f"from live registry (legacy snapshot, {len(frozen_tools)} frozen refs)"
                )

        # Reconstruct prompt from frozen data.
        # Priority: 1. DynamicPrompt.from_frozen  2. system_prompt string  3. live active prompt
        system_prompt = frozen.get('system_prompt')
        prompt_data = frozen.get('prompt_data')
        prompt_obj = None

        if prompt_data:
            try:
                from ..agent.prompts.dynamic_prompt import DynamicPrompt
                prompt_obj = DynamicPrompt.from_frozen(prompt_data)
            except Exception as e:
                logger.warning(
                    "Failed to reconstruct prompt from snapshot %s: %s",
                    snapshot_id, e,
                )

        # Fallback: live active prompt (both frozen paths failed)
        if prompt_obj is None and not system_prompt:
            try:
                prompt_obj = await get_active_prompt_async(tenant_id)
            except Exception as e:
                logger.warning(
                    "Failed to load active prompt for snapshot %s: %s",
                    snapshot_id, e,
                )

        agent = ChatAgent(
            llm_provider=llm_provider,
            system_prompt=system_prompt if prompt_obj is None else None,
            prompt=prompt_obj,
            execution_mode=frozen.get('execution_mode', 'interleaved'),
            tenant_id=tenant_id,
            frozen_skills=full_skills,
            frozen_tools=full_tools,
        )
        return agent, frozen

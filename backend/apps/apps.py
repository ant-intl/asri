"""
Chatbot Django application configuration.
"""
import logging
import sys

from django.apps import AppConfig
from asgiref.sync import async_to_sync

logger = logging.getLogger(__name__)

# Management command whitelist — skip DB query initialization when these commands are executed
_MGMT_SKIP_COMMANDS = frozenset({
    'migrate', 'makemigrations', 'sqlmigrate', 'showmigrations',
    'sqlflush', 'sqlsequencereset',
    'seed_data', 'shell', 'dbshell',
})


def _is_db_management_command() -> bool:
    """Detect whether a database management command is being executed, skip DB initialization if so."""
    return len(sys.argv) > 1 and sys.argv[1] in _MGMT_SKIP_COMMANDS


class ChatbotConfig(AppConfig):
    """Django AppConfig for Chatbot application."""

    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps'
    verbose_name = 'Chatbot'

    def ready(self) -> None:
        """Initialize chatbot components on app startup.

        Skips DB-heavy initialization during management commands (migrate etc.)
        to avoid 'no such table' errors before tables are created.
        """
        if _is_db_management_command():
            logger.debug('Skipping DB initialization during management command')
            return
        self._load_all_skills()
        self._load_all_tools()

    @staticmethod
    def _load_all_skills() -> None:
        """Load skills for global default and all tenants from database."""
        from django.conf import settings
        from .integrations.skill.loader import load_skills_for_tenant

        # 1. Load global default skills (settings.CHATBOT)
        global_config = getattr(settings, 'CHATBOT', {})
        count = load_skills_for_tenant(global_config, tenant_id=None)
        if count:
            logger.info(f"Loaded {count} global default skills")

        # 2. Load skills from database for all tenants
        from .services.skill_service import SkillService
        SkillService.load_all_tenant_skills()

    @staticmethod
    def _load_all_tools() -> None:
        """Load tools for global default and all tenants.

        Now unified: TOOLS config supports both 'class' and 'mcp' types.
        """
        from django.conf import settings
        from .integrations.tool.loader import load_tools_for_tenant

        # Import all tool modules FIRST to trigger auto-registration via __init_subclass__
        _import_all_tool_modules()

        # Use async_to_sync to handle async function
        async_to_sync(_load_tools_async)()


async def _load_tools_async() -> None:
    """Async helper to load all tools (including MCP) for global default and all tenants.

    Uses TenantRegistry (DB) exclusively to enumerate tenants and load configs.
    """
    from django.conf import settings
    from .integrations.tool.loader import load_tools_for_tenant
    from .integrations.tool.reload_manager import get_tool_reload_manager
    from .tenant.registry import get_tenant_registry

    # Force reload TenantRegistry to ensure latest config from DB
    registry = get_tenant_registry()
    registry.force_reload()

    # Collect all tenant IDs from DB
    all_tenant_ids: set[str] = set(registry.list_tenant_ids())

    # 1. Load global default tools (from settings.CHATBOT)
    global_config = registry.get_config(None)
    count = await load_tools_for_tenant(global_config, tenant_id=None)
    if count:
        logger.info(f"Loaded {count} global default tools (including MCP)")

    # Initialize hash for global config
    reload_manager = get_tool_reload_manager()
    reload_manager.update_hash(None, global_config)

    # 2. Load per-tenant tools from DB config
    for tenant_id in all_tenant_ids:
        if not tenant_id:
            continue

        config = registry.get_config(tenant_id)
        count = await load_tools_for_tenant(config, tenant_id=tenant_id)
        if count:
            logger.info(f"Loaded {count} tools for tenant '{tenant_id}'")

        # Initialize hash for tenant config
        reload_manager.update_hash(tenant_id, config)


def _import_all_tool_modules() -> None:
    """Import all tool modules to trigger auto-registration of BaseTool subclasses.

    This ensures all concrete tool classes are registered in ToolRegistry._tool_classes
    before we try to instantiate them by name.

    Scans tool modules from:
    - apps/integrations/tool/      # Core tool framework
    - apps/integrations/rag/       # RAG-related tools
    - apps/integrations/skill/     # Skill-related tools
    - apps/integrations/mcp/       # MCP-related tools
    """
    import importlib
    from pathlib import Path

    integrations_dir = Path(__file__).parent / 'integrations'

    # Directories to scan for tool modules
    tool_dirs = [
        ('tool', 'apps.integrations.tool'),
        ('rag', 'apps.integrations.rag'),
        ('skill', 'apps.integrations.skill'),
        ('mcp', 'apps.integrations.mcp'),
    ]

    for dir_name, module_prefix in tool_dirs:
        tool_dir = integrations_dir / dir_name
        if not tool_dir.exists():
            continue

        logger.debug(f"Scanning {dir_name} directory: {tool_dir}")

        for file_path in tool_dir.glob('*_tool.py'):
            module_name = f"{module_prefix}.{file_path.stem}"
            try:
                importlib.import_module(module_name)
                logger.debug(f"Imported tool module: {module_name}")
            except Exception as e:
                logger.error(f"Failed to import {module_name}: {e}", exc_info=True)

    # Log registered classes
    from .integrations.tool.base import ToolRegistry
    logger.info(f"Registered tool classes: {ToolRegistry.list_tool_classes()}")

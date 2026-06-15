"""
Memory Read Tool - Read user memories from database.
"""
import json
import logging

from asgiref.sync import sync_to_async

from apps.integrations.tool.base import BaseTool
from apps.chatbot.models.user_memory import UserMemory

logger = logging.getLogger(__name__)


class MemoryReadTool(BaseTool):
    """Memory Read Tool

    Used to read user memories saved previously, supports keyword-based queries.
    """

    name = 'memory_read'
    description = '读取用户之前的记忆信息。用于回答与用户历史相关的问题。'
    requires_config = False  # Zero configuration, auto-enabled

    parameters_schema = {
        'type': 'object',
        'properties': {
            'query': {
                'type': 'string',
                'description': '查询关键词（可选，不填返回最近记忆）'
            },
            'limit': {
                'type': 'integer',
                'description': '返回的记忆条数，默认10条',
                'default': 10
            },
            'category': {
                'type': 'string',
                'description': '按分类筛选（preference/fact/goal/other）'
            }
        }
    }

    def __init__(self, tenant_id: str = None, config: dict = None):
        super().__init__(config, tenant_id)

    async def execute(self, input_text: str, context) -> str:
        """Execute memory read"""
        args = json.loads(input_text)

        query = args.get('query')
        limit = args.get('limit', 10)
        category = args.get('category')

        user_id = getattr(context, 'user_id', 'default')
        tenant_id = getattr(context, 'tenant_id', '')

        # Asynchronously query database
        memories = await self._query_memories(user_id, tenant_id, query, category, limit)

        if not memories:
            return "暂无记忆"

        return self._format_memories(memories)

    @sync_to_async(thread_sensitive=False)
    def _query_memories(self, user_id: str, tenant_id: str, query: str, category: str, limit: int):
        """Query memories (sync to async)"""
        queryset = UserMemory.objects.filter(
            user_id=user_id,
            tenant_id=tenant_id
        )

        if query:
            queryset = queryset.filter(content__icontains=query)

        if category:
            queryset = queryset.filter(category=category)

        return list(queryset.order_by('-gmt_create')[:limit])

    def _format_memories(self, memories: list) -> str:
        """Format memory output"""
        lines = []
        for i, m in enumerate(memories, 1):
            category_label = m.get_category_display() if hasattr(m, 'get_category_display') else m.category
            lines.append(f"[{i}] [{category_label}] {m.content}")

        return "\n".join(lines) if lines else "暂无记忆"

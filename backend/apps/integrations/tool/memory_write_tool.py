"""
Memory Write Tool - Write user memories to database.
"""
import json
import logging

from asgiref.sync import sync_to_async

from apps.integrations.tool.base import BaseTool
from apps.chatbot.models.user_memory import UserMemory

logger = logging.getLogger(__name__)


class MemoryWriteTool(BaseTool):
    """Memory Write Tool

    Used to save important information to user memory, such as preferences, key facts, and goals.
    """

    name = 'memory_write'
    description = '保存重要信息到用户记忆中。用于记住用户的偏好、关键事实等。'
    requires_config = False  # Zero configuration, auto-enabled

    parameters_schema = {
        'type': 'object',
        'properties': {
            'content': {
                'type': 'string',
                'description': '要记忆的内容'
            },
            'category': {
                'type': 'string',
                'description': '记忆分类：preference(偏好)/fact(事实)/goal(目标)/other(其他)',
                'default': 'other'
            }
        },
        'required': ['content']
    }

    def __init__(self, tenant_id: str = None, config: dict = None):
        super().__init__(config, tenant_id)

    async def execute(self, input_text: str, context) -> str:
        """Execute memory write"""
        args = json.loads(input_text)

        content = args['content']
        category = args.get('category', 'other')

        user_id = getattr(context, 'user_id', 'default')
        tenant_id = getattr(context, 'tenant_id', '')

        # Asynchronously write to database
        memory_id = await self._create_memory(user_id, tenant_id, content, category)

        category_label = self._get_category_label(category)
        return f"记忆已保存（ID: {memory_id}，分类: {category_label}）"

    @sync_to_async(thread_sensitive=False)
    def _create_memory(self, user_id: str, tenant_id: str, content: str, category: str) -> str:
        """Create memory (sync to async)"""
        memory = UserMemory.objects.create(
            user_id=user_id,
            tenant_id=tenant_id,
            content=content,
            category=category
        )
        return str(memory.id)

    def _get_category_label(self, category: str) -> str:
        """Get category label"""
        labels = {
            'preference': '偏好',
            'fact': '事实',
            'goal': '目标',
            'other': '其他'
        }
        return labels.get(category, category)

"""
RAG search tool.
"""
import logging
import json
from typing import Any, Optional

from ..tool.base import BaseTool
from ..rag.base import BaseRAGProvider

logger = logging.getLogger(__name__)


class RAGSearchTool(BaseTool):
    """Tool for searching knowledge base via a configured RAG provider."""

    # Class-level attributes (required for __init_subclass__ auto-registration)
    name = "rag_search"
    is_factory_class = True  # 通过 RAGRegistry 工厂创建，不单独展示
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "用户原始问题"
            },
            "coreQuestion": {"type": "string", "description": "你根据上下文总结出来的核心问题"},
        },
        "required": ["query", "coreQuestion"]
    }

    def __init__(self, tenant_id: Optional[str] = None, config: Optional[dict] = None):
        self.tenant_id = tenant_id
        self.config = config or {}
        self._provider: Optional[BaseRAGProvider] = None

    @property
    def description(self) -> str:
        """Description of the RAG search tool."""
        return "使用此工具查询任何与业务有关的FAQ及知识"

    def _is_enabled(self) -> bool:
        """Check if the tool is enabled."""
        return self.config.get('enabled', True)

    def _get_provider(self) -> Optional[BaseRAGProvider]:
        """Get or create RAG provider from tool config.

        Subclasses or plugins can override this to provide custom RAG backends.
        """
        if self._provider is not None:
            return self._provider

        # Attempt to create a provider from the RAGRegistry
        try:
            from .rag_registry import RAGRegistry
            self._provider = RAGRegistry.create_provider(
                config=self.config,
                tenant_id=self.tenant_id,
            )
        except Exception as e:
            logger.warning(f"Failed to create RAG provider from registry: {e}")
            return None

        return self._provider

    async def execute(self, input_text: str, context: Any) -> str:
        """Execute RAG search and return results."""
        # Check if tool is enabled
        if not self._is_enabled():
            return "Error: RAG tool is disabled"

        args = self._parse_input(input_text)
        query = args.pop("query", "").strip()

        if not query:
            return "Error: Query is required"

        try:
            rag_provider = self._get_provider()
            if rag_provider is None:
                return "Error: No RAG provider configured"

            results = await rag_provider.search(query, **args)
            return "\n\n".join(f"[{i}] {doc.get('content', '')}" for i, doc in enumerate(results, 1))

        except Exception as e:
            logger.exception(f"RAG search failed: {e}")
            return f"RAG search failed: {str(e)}"

    def _parse_input(self, input_text: str) -> dict:
        """Parse input as JSON."""
        try:
            return json.loads(input_text)
        except json.JSONDecodeError:
            return {"query": input_text}

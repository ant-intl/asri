"""
Lightweight Tool / Skill / RAG implementations for E2E testing.

These are real (non-mock) implementations that perform actual work,
registered into the respective Registries during test setUp.
"""
import re
from datetime import datetime
from typing import Any, Dict, List

from apps.integrations.tool.base import BaseTool
from apps.integrations.skill.base import BaseSkill
from apps.integrations.rag.base import BaseRAGProvider


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class DateTimeTool(BaseTool):
    """Returns the current date and time."""

    name = 'datetime'

    @property
    def description(self) -> str:
        return 'Returns the current date and time'

    async def execute(self, input_text: str, context: Any) -> str:
        now = datetime.now()
        return f"Current date and time: {now.strftime('%Y-%m-%d %H:%M:%S')}"


class CalculatorTool(BaseTool):
    """Evaluates a safe math expression."""

    name = 'calculator'

    @property
    def description(self) -> str:
        return 'Evaluates a math expression and returns the result'

    async def execute(self, input_text: str, context: Any) -> str:
        expr = input_text.strip()
        # Only allow digits, whitespace, and basic math operators
        if not re.match(r'^[\d\s\+\-\*\/\.\(\)\%\^]+$', expr):
            return f"Invalid expression: {expr}"
        expr = expr.replace('^', '**')
        try:
            result = eval(expr)
            return f"Result: {result}"
        except Exception as e:
            return f"Calculation error: {e}"


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

class TranslateSkill(BaseSkill):
    """Simple hardcoded translation skill for testing."""

    name = 'translate'
    description = 'Translates text between languages'

    async def execute(self, input_text: str, context: Any) -> str:
        translations = {
            'hello': '你好',
            'goodbye': '再见',
            'thank you': '谢谢',
            'good morning': '早上好',
        }
        text = input_text.strip().lower()
        result = translations.get(text, f"[Translation of '{input_text}']")
        return f"Translation: {result}"


# ---------------------------------------------------------------------------
# RAG
# ---------------------------------------------------------------------------

class InMemoryRAGProvider(BaseRAGProvider):
    """In-memory RAG provider pre-loaded with test documents."""

    def __init__(self, docs: List[Dict[str, Any]] = None):
        super().__init__()
        self.docs = docs or []

    async def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Simple keyword-matching search."""
        scored = []
        query_lower = query.lower()
        for doc in self.docs:
            content = doc.get('content', '')
            score = 1.0 if query_lower in content.lower() else 0.3
            scored.append({**doc, 'score': score})
        scored.sort(key=lambda x: x['score'], reverse=True)
        return scored[:top_k]

    async def index(self, doc_id: str, content: str, metadata: Dict[str, Any] = None) -> bool:
        self.docs.append({
            'doc_id': doc_id,
            'content': content,
            'metadata': metadata or {},
        })
        return True

    def get_provider_type(self) -> str:
        return 'in_memory'

"""
Conversation memory implementation.
"""
from typing import List, Dict, Any
from collections import deque

from .base import BaseMemory


class ConversationMemory(BaseMemory):
    """In-memory conversation history."""
    
    def __init__(self, max_size: int = 100):
        self._messages: deque = deque(maxlen=max_size)
    
    async def add(self, message: Dict[str, Any]) -> None:
        """Add a message."""
        self._messages.append(message)
    
    async def get(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent messages."""
        messages = list(self._messages)
        return messages[-limit:] if limit else messages
    
    async def clear(self) -> None:
        """Clear all messages."""
        self._messages.clear()

"""
Summary memory with compression.
"""
from typing import List, Dict, Any

from .base import BaseMemory
from .conversation import ConversationMemory


class SummaryMemory(BaseMemory):
    """Memory with automatic summarization."""
    
    def __init__(self, max_size: int = 50, summary_threshold: int = 30):
        self._conversation = ConversationMemory(max_size=max_size)
        self._summary = ""
        self._summary_threshold = summary_threshold
    
    async def add(self, message: Dict[str, Any]) -> None:
        """Add a message, compress if needed."""
        await self._conversation.add(message)
        
        messages = await self._conversation.get()
        if len(messages) >= self._summary_threshold:
            await self._compress_history()
    
    async def get(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get messages with summary context."""
        messages = await self._conversation.get(limit)
        if self._summary:
            return [{'role': 'system', 'content': f'Summary: {self._summary}'}] + messages
        return messages
    
    async def clear(self) -> None:
        """Clear memory and summary."""
        await self._conversation.clear()
        self._summary = ""
    
    async def compress(self) -> str:
        """Get current summary."""
        return self._summary
    
    async def _compress_history(self) -> None:
        """Compress old messages into summary."""
        messages = await self._conversation.get()
        count = len(messages)
        self._summary = f"Previous conversation with {count} messages discussing various topics."
        # Keep only recent messages
        await self._conversation.clear()
        for msg in messages[-10:]:
            await self._conversation.add(msg)

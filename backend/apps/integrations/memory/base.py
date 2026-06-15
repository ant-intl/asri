"""
Base Memory abstract class.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseMemory(ABC):
    """Abstract base class for memory implementations."""
    
    @abstractmethod
    async def add(self, message: Dict[str, Any]) -> None:
        """Add a message to memory."""
        pass
    
    @abstractmethod
    async def get(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent messages from memory."""
        pass
    
    @abstractmethod
    async def clear(self) -> None:
        """Clear all memory."""
        pass
    
    async def compress(self) -> str:
        """Compress memory into a summary (optional)."""
        messages = await self.get(limit=100)
        if not messages:
            return ""
        return f"Previous conversation with {len(messages)} messages."

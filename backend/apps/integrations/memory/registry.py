"""
Memory registry.
"""
from .base import BaseMemory
from .conversation import ConversationMemory
from .summary import SummaryMemory


class MemoryRegistry:
    """Registry for memory instances."""
    
    _instances = {}
    
    @classmethod
    def get_memory(cls, session_id: str, memory_type: str = 'conversation') -> BaseMemory:
        """Get or create memory for a session."""
        key = f"{session_id}_{memory_type}"
        
        if key not in cls._instances:
            if memory_type == 'summary':
                cls._instances[key] = SummaryMemory()
            else:
                cls._instances[key] = ConversationMemory()
        
        return cls._instances[key]
    
    @classmethod
    def clear_session(cls, session_id: str) -> None:
        """Clear all memory for a session."""
        keys_to_remove = [k for k in cls._instances if k.startswith(f"{session_id}_")]
        for key in keys_to_remove:
            del cls._instances[key]

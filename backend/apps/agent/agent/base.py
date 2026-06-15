"""
Base agent abstract class.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, AsyncGenerator

from .context import AgentContext


class BaseAgent(ABC):
    """
    Abstract base class for agents.
    
    All agent implementations must inherit from this class
    and implement the required methods.
    """
    
    def __init__(self, **kwargs):
        self.config = kwargs
    
    @abstractmethod
    async def run(
        self,
        query: str,
        history: List[Dict[str, str]] = None,
        context: AgentContext = None,
    ) -> Dict[str, Any]:
        """
        Run the agent to completion.

        Args:
            query: User's query/question
            history: Conversation history
            context: Optional pre-configured context

        Returns:
            Dict containing 'answer', 'trace', and token usage
        """
        pass
    
    @abstractmethod
    async def stream(
        self,
        query: str,
        history: List[Dict[str, str]] = None,
        context: AgentContext = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Stream the agent's response.
        
        Args:
            query: User's query/question
            history: Conversation history
            context: Optional pre-configured context
        
        Yields:
            Dict chunks with 'type' and 'content'
        """
        pass
    
    async def get_context_messages(self) -> List[Dict[str, Any]] | None:
        """
        Get current accumulated context messages.
        
        Returns None if not available or not yet initialized.
        Subclasses should override to provide actual implementation.
        """
        return None

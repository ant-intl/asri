"""
Base RAG Provider abstract class.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseRAGProvider(ABC):
    """
    Abstract base class for RAG (Retrieval-Augmented Generation) providers.
    """
    
    def __init__(self, api_base: str = '', api_key: str = '', **kwargs):
        self.api_base = api_base
        self.api_key = api_key
        self.config = kwargs
    
    @abstractmethod
    async def search(self, query: str, **kwargs) -> List[Dict[str, Any]]:
        """
        Search for relevant documents.
        
        Args:
            query: Search query
            top_k: Number of results to return
        
        Returns:
            List of dicts with 'content', 'score', and optional 'metadata'
        """
        pass
    
    @abstractmethod
    async def index(self, doc_id: str, content: str, metadata: Dict[str, Any] = None) -> bool:
        """
        Index a document.
        
        Args:
            doc_id: Document identifier
            content: Document content
            metadata: Optional metadata
        
        Returns:
            True if successful
        """
        pass
    
    @abstractmethod
    def get_provider_type(self) -> str:
        """Return the provider type identifier."""
        pass

"""
ContentExtractor abstract base class
"""
from abc import ABC, abstractmethod

from .base import LLMRes, LLMResChunk


class BaseContentExtractor(ABC):
    """Base content extractor class"""

    def __init__(self, default_type: str = "think"):
        self.default_type = default_type

    @abstractmethod
    def extract(self, response: str) -> LLMRes:
        """Non-streaming extraction

        Args:
            response: Raw LLM response text

        Returns:
            LLMRes: Extracted key-value pairs and original content
        """
        pass

    @abstractmethod
    def extract_stream(self, chunk: str) -> list[LLMResChunk]:
        """Streaming extraction

        A single chunk may span multiple tag boundaries, hence returning a list.

        Args:
            chunk: Raw LLM response chunk

        Returns:
            list[LLMResChunk]: Extraction result list; empty list means more data is needed
        """
        pass

    @abstractmethod
    def flush_stream(self) -> list[LLMResChunk]:
        """Flush remaining buffered content at stream end or turn boundary

        Returns:
            list[LLMResChunk]: Extraction results for remaining content
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset streaming state, preparing for a new round of streaming parsing"""
        pass

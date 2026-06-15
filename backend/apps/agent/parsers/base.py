"""
LLM output parser data type definitions
"""
from dataclasses import dataclass
from typing import List, Tuple, Optional, Union


@dataclass
class LLMRes:
    """Non-streaming parse result"""
    kv_pairs: List[Tuple[str, str]]   # List of extracted key-value pairs
    content: str                       # Original complete content


@dataclass
class LLMResChunk:
    """Streaming parse result chunk"""
    kv_key: str               # Current key being output
    kv_delta: str             # Incremental content since last emission
    is_key_complete: bool     # Whether this key output is complete (determined by Extractor)
    raw_delta: str            # Raw incremental content (for logging)


@dataclass
class ToolCall:
    """Tool call"""
    name: str           # Tool name
    input: dict         # Tool input parameters (parsed as dict)


@dataclass
class LLMOutput:
    """Non-streaming standard output"""
    tool: Optional[ToolCall]     # Tool call
    think: Optional[str]         # Thinking process
    answer: Optional[str]        # Answer content


@dataclass
class LLMOutputChunk:
    """Streaming standard output chunk"""
    type: str                    # "tool" | "think" | "answer"
    content: Union[str, dict]    # Complete content (str for text, dict for tool)
    is_complete: bool            # Whether this type output is complete
    raw_delta: str               # Raw incremental content

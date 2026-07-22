"""
Agent Loop Core - framework-agnostic multi-round LLM + Tool execution loop.

This module provides AgentLoopCore, a shared implementation used by both
Django's FullDuplexLLMProcessor and Voice's OpenApiModelHandler.
"""

from .core import (
    # Main class
    AgentLoopCore,
    # Events
    TextChunk,
    ReasoningChunk,
    ToolCallStarted,
    ToolCallDispatched,
    ToolCallReady,
    ToolResult,
    IterationMetrics,
    Error,
    AgentEvent,
    # Stream input
    StreamChunk,
)

__all__ = [
    "AgentLoopCore",
    "TextChunk",
    "ReasoningChunk",
    "ToolCallStarted",
    "ToolCallDispatched",
    "ToolCallReady",
    "ToolResult",
    "IterationMetrics",
    "Error",
    "AgentEvent",
    "StreamChunk",
]

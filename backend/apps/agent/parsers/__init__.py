"""
LLM output parser module

Provides configurable and extensible LLM output parsing, supporting XML, JSON, ReAct, and other formats.
"""
from typing import Tuple

from .base import (
    LLMRes,
    LLMResChunk,
    LLMOutput,
    LLMOutputChunk,
    ToolCall,
)
from .extractor import BaseContentExtractor
from .xml_tag_extractor import XMLTagExtractor
from .json_extractor import JSONExtractor
from .react_extractor import ReActExtractor
from .mapper import OutputMapper


class OutputParserFactory:
    """Parser factory

    Creates Extractor and Mapper instances based on configuration
    """

    @staticmethod
    def create(
        extractor_cfg: dict,
        mapper_cfg: dict
    ) -> Tuple[BaseContentExtractor, OutputMapper]:
        """Create parser instances

        Args:
            extractor_cfg: Extractor configuration
                - type: "xml_tags" | "json" | "react"
                - default_type: Fallback type, default "think"
            mapper_cfg: Mapper configuration
                - tool_keys: Keys mapped to tool
                - think_keys: Keys mapped to think
                - answer_keys: Keys mapped to answer

        Returns:
            Tuple[BaseContentExtractor, OutputMapper]: Extractor and Mapper instances
        """
        # Create Extractor
        extractor_type = extractor_cfg.get("type", "xml_tags")
        default_type = extractor_cfg.get("default_type", "think")

        if extractor_type == "xml_tags":
            known_tags = list(set(
                mapper_cfg.get("tool_keys", [])
                + mapper_cfg.get("think_keys", [])
                + mapper_cfg.get("answer_keys", [])
            ))
            extractor = XMLTagExtractor(
                default_type=default_type,
                known_tags=known_tags or None,
            )
        elif extractor_type == "json":
            extractor = JSONExtractor(default_type=default_type)
        elif extractor_type == "react":
            extractor = ReActExtractor(default_type=default_type)
        else:
            raise ValueError(f"Unknown extractor type: {extractor_type}")

        # Create Mapper
        mapper = OutputMapper(
            tool_keys=mapper_cfg.get("tool_keys", ["tool_call"]),
            think_keys=mapper_cfg.get("think_keys", ["think"]),
            answer_keys=mapper_cfg.get("answer_keys", ["answer"])
        )

        return extractor, mapper


__all__ = [
    # Data types
    "LLMRes",
    "LLMResChunk",
    "LLMOutput",
    "LLMOutputChunk",
    "ToolCall",
    # Extractor
    "BaseContentExtractor",
    "XMLTagExtractor",
    "JSONExtractor",
    "ReActExtractor",
    # Mapper
    "OutputMapper",
    # Factory
    "OutputParserFactory",
]

"""
ReAct text content extractor
"""
import re
from typing import List, Tuple

from .extractor import BaseContentExtractor
from .base import LLMRes, LLMResChunk


class ReActExtractor(BaseContentExtractor):
    """ReAct text extractor

    Parses Thought: xxx\nAction: yyy format
    """

    # ReAct pattern matching (case-insensitive)
    THOUGHT_PATTERN = re.compile(r'Thought:\s*(.+?)(?=\n(?:Action|Observation):|$)', re.DOTALL | re.IGNORECASE)
    ACTION_PATTERN = re.compile(r'Action:\s*(\w+)', re.IGNORECASE)
    ACTION_INPUT_PATTERN = re.compile(
        r'Action\s*Input:\s*(.+?)(?=\n(?:Thought|Action|Observation):|$)', re.DOTALL | re.IGNORECASE
    )

    def __init__(self, default_type: str = "think"):
        super().__init__(default_type)
        # Streaming state
        self._buffer = ""
        self._thought_extracted = False
        self._action_extracted = False
        self._input_extracted = False
        self._fallback_extracted = False

    def extract(self, response: str) -> LLMRes:
        """Non-streaming ReAct format extraction"""
        kv_pairs: List[Tuple[str, str]] = []

        # Extract Thought
        thought_match = self.THOUGHT_PATTERN.search(response)
        if thought_match:
            kv_pairs.append(("thought", thought_match.group(1).strip()))

        # Extract Action
        action_match = self.ACTION_PATTERN.search(response)
        if action_match:
            kv_pairs.append(("action", action_match.group(1).strip()))

        # Extract Action Input
        input_match = self.ACTION_INPUT_PATTERN.search(response)
        if input_match:
            kv_pairs.append(("action_input", input_match.group(1).strip()))

        # If no ReAct pattern matched, use default_type
        if not kv_pairs:
            kv_pairs.append((self.default_type, response.strip()))

        return LLMRes(kv_pairs=kv_pairs, content=response)

    def extract_stream(self, chunk: str) -> list[LLMResChunk]:
        """Streaming extraction

        Recognizes ReAct pattern boundaries, returns when a complete pattern is detected
        """
        self._buffer += chunk

        # Check if a complete Thought pattern exists
        thought_match = self.THOUGHT_PATTERN.search(self._buffer)
        if thought_match and not self._thought_extracted:
            self._thought_extracted = True
            thought_content = thought_match.group(1).strip()

            # Check if Action follows Thought
            remaining = self._buffer[thought_match.end():]
            has_action = self.ACTION_PATTERN.search(remaining) is not None

            return [LLMResChunk(
                kv_key="thought",
                kv_delta=thought_content,
                is_key_complete=has_action,  # If Action present, Thought is complete
                raw_delta=chunk,
            )]

        # Check if a complete Action pattern exists
        action_match = self.ACTION_PATTERN.search(self._buffer)
        if action_match and not self._action_extracted:
            self._action_extracted = True
            action_content = action_match.group(1).strip()

            return [LLMResChunk(
                kv_key="action",
                kv_delta=action_content,
                is_key_complete=True,
                raw_delta=chunk,
            )]

        # Check if a complete Action Input pattern exists
        input_match = self.ACTION_INPUT_PATTERN.search(self._buffer)
        if input_match and not self._input_extracted:
            self._input_extracted = True
            input_content = input_match.group(1).strip()

            return [LLMResChunk(
                kv_key="action_input",
                kv_delta=input_content,
                is_key_complete=True,
                raw_delta=chunk,
            )]

        # If no pattern matched and buffer is long, use default_type
        if len(self._buffer) > 100 and not self._fallback_extracted:
            # Check if ReAct markers are present
            if not any(marker in self._buffer.lower() for marker in ['thought:', 'action:', 'observation:']):
                self._fallback_extracted = True
                return [LLMResChunk(
                    kv_key=self.default_type,
                    kv_delta=self._buffer.strip(),
                    is_key_complete=True,
                    raw_delta=chunk,
                )]

        return []

    def flush_stream(self) -> list[LLMResChunk]:
        """Flush remaining buffer content"""
        if self._buffer and not (self._thought_extracted or self._action_extracted
                                 or self._input_extracted or self._fallback_extracted):
            result = [LLMResChunk(
                kv_key=self.default_type,
                kv_delta=self._buffer.strip(),
                is_key_complete=True,
                raw_delta=self._buffer,
            )]
            self._buffer = ''
            return [r for r in result if r.kv_delta]
        return []

    def reset(self) -> None:
        """Reset streaming state"""
        self._buffer = ""
        self._thought_extracted = False
        self._action_extracted = False
        self._input_extracted = False
        self._fallback_extracted = False

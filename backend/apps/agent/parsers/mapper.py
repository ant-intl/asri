"""
Output mapper
"""
import json
import logging
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)

from .base import (
    LLMRes, LLMResChunk,
    LLMOutput, LLMOutputChunk,
    ToolCall
)


class OutputMapper:
    """Output mapper

    Maps LLMRes to standard output format (tool/think/answer)
    """

    def __init__(
        self,
        tool_keys: List[str],
        think_keys: List[str],
        answer_keys: List[str]
    ):
        self.tool_keys = tool_keys
        self.think_keys = think_keys
        self.answer_keys = answer_keys

        # Streaming state
        self._tool_buffer = ""      # tool content accumulation buffer
        self._current_tool_key = None  # current tool key

    def map(self, llm_res: LLMRes) -> LLMOutput:
        """Non-streaming mapping

        Args:
            llm_res: Extractor output

        Returns:
            LLMOutput: Standard output format
        """
        kv_dict: Dict[str, str] = dict(llm_res.kv_pairs)

        # Find key by priority
        tool_value = self._find_first(kv_dict, self.tool_keys)
        think_value = self._find_first(kv_dict, self.think_keys)
        answer_value = self._find_first(kv_dict, self.answer_keys)

        # Parse tool (hardcoded as json)
        tool = None
        if tool_value:
            try:
                tool_obj = json.loads(tool_value)
                # Support two formats: {"name": "xxx", "input": {...}} or {"name": "xxx", ...}
                name = tool_obj.get("name", "")
                tool = ToolCall(name=name, input=tool_obj)
            except json.JSONDecodeError:
                # JSON parse failed, silently discard (tool already executed by API layer function calling)
                # Do not downgrade to answer, avoid Qwen native format garbled output to user
                logger.warning("tool_call JSON parse failed, discarding: %s", tool_value[:100])

        return LLMOutput(
            tool=tool,
            think=think_value,
            answer=answer_value
        )

    def map_stream(self, chunk: LLMResChunk) -> Optional[LLMOutputChunk]:
        """Streaming mapping

        Args:
            chunk: Extractor streaming output

        Returns:
            LLMOutputChunk: Standard streaming output, None means no output (e.g., suppressed when tool is incomplete)
        """
        kv_key = chunk.kv_key
        kv_delta = chunk.kv_delta
        is_complete = chunk.is_key_complete

        # Determine type
        output_type = self._determine_type(kv_key)

        if output_type == "tool":
            # tool needs to accumulate complete content before parsing JSON
            if kv_key != self._current_tool_key:
                # New tool key, reset buffer
                self._current_tool_key = kv_key
                self._tool_buffer = ""

            self._tool_buffer += kv_delta

            if is_complete:
                # Parse JSON when complete
                try:
                    tool_obj = json.loads(self._tool_buffer)
                    return LLMOutputChunk(
                        type="tool",
                        content=tool_obj,
                        is_complete=True,
                        raw_delta=chunk.raw_delta
                    )
                except json.JSONDecodeError:
                    # JSON parse failed, silently discard (tool already executed by API layer function calling)
                    logger.warning("tool_call JSON parse failed, discarding: %s", self._tool_buffer[:100])
                    return None
            else:
                # tool incomplete, suppress output
                return None

        elif output_type == "think":
            return LLMOutputChunk(
                type="think",
                content=kv_delta,
                is_complete=is_complete,
                raw_delta=chunk.raw_delta
            )

        elif output_type == "answer":
            return LLMOutputChunk(
                type="answer",
                content=kv_delta,
                is_complete=is_complete,
                raw_delta=chunk.raw_delta
            )

        return None

    def _find_first(self, kv_dict: Dict[str, str], keys: List[str]) -> Optional[str]:
        """Find the first existing key by priority"""
        for key in keys:
            if key in kv_dict:
                return kv_dict[key]
        return None

    def _determine_type(self, key: str) -> str:
        """Determine output type for key"""
        if key in self.tool_keys:
            return "tool"
        if key in self.think_keys:
            return "think"
        if key in self.answer_keys:
            return "answer"
        # Default as answer
        return "answer"

    def reset(self) -> None:
        """Reset streaming state"""
        self._tool_buffer = ""
        self._current_tool_key = None

"""
XML tag content extractor

Non-streaming uses regex extraction, streaming uses incremental state machine (absorbed from StreamingTagFilter).
"""
import logging
import re
from typing import Optional, List, Tuple

from .extractor import BaseContentExtractor
from .base import LLMRes, LLMResChunk

logger = logging.getLogger(__name__)


class XMLTagExtractor(BaseContentExtractor):
    """XML tag extractor

    Parses <tag>value</tag> format, supports streaming and non-streaming extraction.

    Non-streaming extract() uses regex to match all tags at once.
    Streaming extract_stream() uses incremental state machine to identify tag boundaries chunk by chunk,
    supports tags split across chunks, and incrementally emits content inside tags.

    Args:
        default_type: Fallback key when no tags exist in non-streaming extract().
        known_tags: List of tag names recognized by the streaming state machine.
            Default ``['think', 'tool_call', 'answer']``.
    """

    # Match <tag>content</tag>, supports multi-line content
    TAG_PATTERN = re.compile(r'<(\w+)>(.*?)</\1>', re.DOTALL)

    def __init__(
        self,
        default_type: str = "think",
        known_tags: list[str] | None = None,
    ):
        super().__init__(default_type)
        self._known_tags = known_tags or ['think', 'tool_call', 'answer']

        # Precompute open/close tag strings
        self._open_tags: dict[str, str] = {
            name: f'<{name}>' for name in self._known_tags
        }
        self._close_tags: dict[str, str] = {
            name: f'</{name}>' for name in self._known_tags
        }
        self._all_open_strings: list[str] = list(self._open_tags.values())

        # Streaming state machine
        self._state: Optional[str] = None   # None=OUTSIDE, otherwise=tag name
        self._buffer: str = ''
        self._prev_char: str = ''  # Track last character when consuming buffer, for backtick detection

    # ------------------------------------------------------------------
    # Non-streaming extraction
    # ------------------------------------------------------------------

    # Match <tag> or </tag>
    TAG_PATTERN = re.compile(r'<(/?)(\w+)>', re.DOTALL)

    def extract(self, response: str) -> LLMRes:
        """Non-streaming extraction of all tags, auto-closes current tag when encountering new tag"""
        kv_pairs: List[Tuple[str, str]] = []
        current_tag: str | None = None
        current_content: list[str] = []

        last_end = 0
        for match in self.TAG_PATTERN.finditer(response):
            # Backtick escape check: skip if backticks on both sides
            if (match.start() > 0 and response[match.start() - 1] == '`'
                    and match.end() < len(response) and response[match.end()] == '`'):
                continue

            # Text before tag
            before = response[last_end:match.start()]
            last_end = match.end()

            is_close = match.group(1) == '/'
            tag_name = match.group(2)

            if is_close:
                # Close tag: complete current tag
                if current_tag:
                    if before:
                        current_content.append(before)
                    kv_pairs.append((current_tag, ''.join(current_content)))
                current_tag = None
                current_content = []
            else:
                # Open tag
                if current_tag:
                    # Encountered new tag, close current tag (think content truncation rule)
                    if before:
                        current_content.append(before)
                    kv_pairs.append((current_tag, ''.join(current_content)))
                current_tag = tag_name
                current_content = []

        # Handle trailing residue
        if last_end < len(response):
            remaining = response[last_end:]
            if current_tag:
                current_content.append(remaining)
            elif remaining:
                kv_pairs.append((self.default_type, remaining))

        if current_tag:
            kv_pairs.append((current_tag, ''.join(current_content)))

        return LLMRes(kv_pairs=kv_pairs, content=response)

    # ------------------------------------------------------------------
    # Streaming extraction (incremental state machine)
    # ------------------------------------------------------------------

    def extract_stream(self, chunk: str) -> list[LLMResChunk]:
        """Streaming extraction

        Appends chunk to internal buffer, uses state machine to produce as many
        determined (kv_key, kv_delta) pairs as possible. A chunk may span multiple
        tag boundaries, hence returns list.

        Args:
            chunk: Raw LLM response chunk

        Returns:
            list[LLMResChunk]: Extraction result list, empty list means more data needed
        """
        if not chunk:
            return []
        self._buffer += chunk
        return self._drain(chunk)

    def flush_stream(self) -> list[LLMResChunk]:
        """Flush remaining buffer content (called at stream end or turn boundary)

        Returns:
            list[LLMResChunk]: Extraction result of remaining content
        """
        results: list[LLMResChunk] = []
        if self._buffer:
            if self._state is not None:
                logger.warning(
                    "XMLTagExtractor: flushing while inside tag state=%r, "
                    "forcing reset",
                    self._state,
                )
                results.append(LLMResChunk(
                    kv_key=self._state,
                    kv_delta=self._buffer,
                    is_key_complete=True,
                    raw_delta=self._buffer,
                ))
            else:
                results.append(LLMResChunk(
                    kv_key=self.default_type,
                    kv_delta=self._buffer,
                    is_key_complete=True,
                    raw_delta=self._buffer,
                ))
            self._buffer = ''
        self._state = None
        return [r for r in results if r.kv_delta]

    def reset(self) -> None:
        """Reset streaming state"""
        self._state = None
        self._buffer = ''
        self._prev_char = ''

    # ------------------------------------------------------------------
    # State machine internal implementation
    # ------------------------------------------------------------------

    def _drain(self, raw_delta: str) -> list[LLMResChunk]:
        """Process _buffer, extract all determinable segments."""
        results: list[LLMResChunk] = []

        while self._buffer:
            if self._state is None:
                advanced = self._drain_outside(results, raw_delta)
            else:
                advanced = self._drain_inside(results, raw_delta)

            if not advanced:
                break

        return [r for r in results if r.kv_delta]

    def _drain_outside(self, results: list[LLMResChunk], raw_delta: str) -> bool:
        """Handle OUTSIDE state (not inside any tag).

        Returns:
            True means progress (consumed buffer), False means need more data.
        """
        lt_idx = self._buffer.find('<')

        if lt_idx < 0:
            # No '<' — entire buffer is ordinary text
            results.append(LLMResChunk(
                kv_key=self.default_type,
                kv_delta=self._buffer,
                is_key_complete=False,
                raw_delta=raw_delta,
            ))
            self._prev_char = self._buffer[-1] if self._buffer else ''
            self._buffer = ''
            return True

        if lt_idx > 0:
            # Text before '<', emit first
            results.append(LLMResChunk(
                kv_key=self.default_type,
                kv_delta=self._buffer[:lt_idx],
                is_key_complete=False,
                raw_delta=raw_delta,
            ))
            self._prev_char = self._buffer[lt_idx - 1]
            self._buffer = self._buffer[lt_idx:]
            return True

        # buffer starts with '<'
        # 1. First check isolated close tags (e.g., </think> appearing outside)
        if self._buffer.startswith('</'):
            gt_idx = self._buffer.find('>')
            if gt_idx >= 0:
                self._buffer = self._buffer[gt_idx + 1:]
                return True
            return False

        # 2. Check if it's a known open tag
        for tag_name, open_str in self._open_tags.items():
            if self._buffer.startswith(open_str):
                escaped = self._is_backtick_escaped(0, len(open_str))
                if escaped is True:
                    # Backtick escaped: emit as ordinary text
                    results.append(LLMResChunk(
                        kv_key=self.default_type,
                        kv_delta=open_str,
                        is_key_complete=False,
                        raw_delta=raw_delta,
                    ))
                    self._prev_char = '>'
                    self._buffer = self._buffer[len(open_str):]
                    return True
                if escaped is None:
                    return False  # Wait for trailing characters
                # escaped is False: normally enter tag
                self._prev_char = '>'
                self._buffer = self._buffer[len(open_str):]
                self._state = tag_name
                return True

        # 3. Check if it's a prefix of a known open tag (needs more data)
        if self._is_prefix_of_any_open_tag(self._buffer):
            return False

        # 4. Not a known tag — emit '<' as ordinary text
        results.append(LLMResChunk(
            kv_key=self.default_type,
            kv_delta='<',
            is_key_complete=False,
            raw_delta=raw_delta,
        ))
        self._prev_char = '<'
        self._buffer = self._buffer[1:]
        return True

    def _drain_inside(self, results: list[LLMResChunk], raw_delta: str) -> bool:
        """Handle INSIDE state (inside a tag).

        Returns:
            True means progress, False means need more data.
        """
        # Get close tag string (may be unknown tag)
        close_str = self._close_tags.get(self._state) or f'</{self._state}>'

        # First check if new open tag appears before close tag
        lt_idx = self._buffer.find('<')
        if lt_idx >= 0:
            # Check if it's a close tag prefix (needs to be kept)
            is_close_prefix = self._buffer[lt_idx:].startswith('</') and close_str.startswith(self._buffer[lt_idx:])

            if not is_close_prefix:
                # Not a close tag prefix, may be a new open tag
                tag_match = re.match(r'<(\w+)>', self._buffer[lt_idx:])
                if tag_match:
                    new_tag = tag_match.group(1)
                    new_tag_len = tag_match.end()
                    escaped = self._is_backtick_escaped(lt_idx, new_tag_len)
                    if escaped is True:
                        # Backtick escaped: emit escaped tag as ordinary text
                        content_before = self._buffer[:lt_idx]
                        escaped_tag = self._buffer[lt_idx:lt_idx + new_tag_len]
                        if content_before:
                            results.append(LLMResChunk(
                                kv_key=self._state,
                                kv_delta=content_before,
                                is_key_complete=False,
                                raw_delta=raw_delta,
                            ))
                        results.append(LLMResChunk(
                            kv_key=self._state,
                            kv_delta=escaped_tag,
                            is_key_complete=False,
                            raw_delta=raw_delta,
                        ))
                        self._prev_char = '>'
                        self._buffer = self._buffer[lt_idx + new_tag_len:]
                        return True
                    elif escaped is None:
                        pass  # Uncertain, wait for more data
                    else:
                        # escaped is False: non-escaped tag, trigger implicit close (including same-name tag)
                        content = self._buffer[:lt_idx]
                        if content:
                            results.append(LLMResChunk(
                                kv_key=self._state,
                                kv_delta=content,
                                is_key_complete=False,
                                raw_delta=raw_delta,
                            ))
                            self._prev_char = content[-1]
                        self._buffer = self._buffer[lt_idx:]
                        self._state = None
                        return True

        # Scan for non-escaped close tags (skip backtick-wrapped close tags)
        close_idx = -1
        search_start = 0
        ambiguous_pos = -1
        escaped_close_end = -1  # Record position of last skipped escaped close tag
        while True:
            idx = self._buffer.find(close_str, search_start)
            if idx < 0:
                break
            escaped = self._is_backtick_escaped(idx, len(close_str))
            if escaped is True:
                # Record end position of escaped close tag
                escaped_close_end = idx + len(close_str)
                search_start = escaped_close_end
                continue
            if escaped is None:
                ambiguous_pos = idx
                break  # Uncertain, use safe_emit logic
            close_idx = idx
            break

        # If escaped close tags found, consume them first (emit as text)
        if escaped_close_end > 0 and close_idx < 0:
            # No real close tag found, but has escaped close tags
            # Emit escaped close tags as content
            escaped_tag = self._buffer[:escaped_close_end]
            results.append(LLMResChunk(
                kv_key=self._state,
                kv_delta=escaped_tag,
                is_key_complete=False,
                raw_delta=raw_delta,
            ))
            self._prev_char = '>'
            self._buffer = self._buffer[escaped_close_end:]
            return True

        if close_idx >= 0:
            # Found close tag
            content = self._buffer[:close_idx]
            if content:
                results.append(LLMResChunk(
                    kv_key=self._state,
                    kv_delta=content,
                    is_key_complete=True,
                    raw_delta=raw_delta,
                ))
                self._prev_char = content[-1]
            self._buffer = self._buffer[close_idx + len(close_str):]
            self._state = None
            return True

        # Handle uncertain case: close tag may be at buffer end
        if ambiguous_pos >= 0:
            safe_end = ambiguous_pos
            if safe_end < len(self._buffer):
                content = self._buffer[:safe_end]
                if content:
                    results.append(LLMResChunk(
                        kv_key=self._state,
                        kv_delta=content,
                        is_key_complete=False,
                        raw_delta=raw_delta,
                    ))
                    self._prev_char = content[-1]
                self._buffer = self._buffer[safe_end:]
                return bool(content)

        # Check if buffer end is a partial prefix of close tag
        safe_end = self._safe_emit_end(close_str)
        if safe_end < len(self._buffer):
            content = self._buffer[:safe_end]
            if content:
                results.append(LLMResChunk(
                    kv_key=self._state,
                    kv_delta=content,
                    is_key_complete=False,
                    raw_delta=raw_delta,
                ))
                self._prev_char = content[-1]
            self._buffer = self._buffer[safe_end:]
            return bool(content)

        return False

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def _is_prefix_of_any_open_tag(self, text: str) -> bool:
        """Check if text is a proper prefix of any known open tag."""
        for open_str in self._all_open_strings:
            if open_str.startswith(text) and len(text) < len(open_str):
                return True
        return False

    def _is_backtick_escaped(self, pos: int, tag_len: int) -> bool | None:
        """Check if tag at pos in buffer is wrapped by backticks.

        Args:
            pos: Start position of tag '<' in buffer
            tag_len: Total length of tag string

        Returns:
            True: Confirmed escaped (skip)
            False: Confirmed not escaped (process normally)
            None: Uncertain (need to wait for more data)
        """
        # Check leading backtick
        if pos > 0:
            has_leading = self._buffer[pos - 1] == '`'
        elif pos == 0:
            # Check buffer start or _prev_char (from end of previously emitted content)
            has_leading = (self._buffer.startswith('`') if self._buffer else False) or self._prev_char == '`'
        else:
            has_leading = False

        if not has_leading:
            return False

        # Check trailing backtick
        after_pos = pos + tag_len
        if after_pos > len(self._buffer):
            return None  # Insufficient data, wait for next chunk
        if after_pos == len(self._buffer):
            # Tag exactly at buffer end, check last character
            return False if not self._buffer else self._buffer[-1] != '`'
        return self._buffer[after_pos] == '`'

    def _safe_emit_end(self, close_tag: str) -> int:
        """Return safe end index in buffer for emission.

        Content after this index *may* be a partial prefix of close tag,
        needs to be kept waiting for next chunk.
        """
        for i in range(1, len(close_tag)):
            suffix = self._buffer[-i:]
            if close_tag.startswith(suffix):
                return len(self._buffer) - i
        return len(self._buffer)

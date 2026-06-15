"""
XMLTagExtractor tests
"""
import pytest

from apps.agent.parsers import XMLTagExtractor


class TestXMLTagExtractor:
    """XML tag extractor tests"""

    def test_extract_single_tag(self):
        """Test single tag extraction"""
        extractor = XMLTagExtractor(default_type="think")
        result = extractor.extract("<think>让我搜索</think>")
        assert result.kv_pairs == [("think", "让我搜索")]
        assert result.content == "<think>让我搜索</think>"

    def test_extract_multiple_tags(self):
        """Test multiple tag extraction"""
        extractor = XMLTagExtractor(default_type="think")
        result = extractor.extract(
            '<think>让我搜索</think><tool_call>{"name": "search"}</tool_call>'
        )
        assert result.kv_pairs == [
            ("think", "让我搜索"),
            ("tool_call", '{"name": "search"}')
        ]

    def test_extract_empty_tag(self):
        """Test empty tag"""
        extractor = XMLTagExtractor(default_type="think")
        result = extractor.extract("<think></think>")
        assert result.kv_pairs == [("think", "")]

    def test_extract_no_tags_use_default(self):
        """Test using default_type when no tags"""
        extractor = XMLTagExtractor(default_type="think")
        result = extractor.extract("纯文本内容")
        assert result.kv_pairs == [("think", "纯文本内容")]

    def test_extract_multiline_content(self):
        """Test multiline content"""
        extractor = XMLTagExtractor(default_type="think")
        result = extractor.extract("<think>第一行\n第二行\n第三行</think>")
        assert result.kv_pairs == [("think", "第一行\n第二行\n第三行")]

    # ------------------------------------------------------------------
    # Stream extraction tests (incremental state machine)
    # ------------------------------------------------------------------

    def test_extract_stream_single_chunk_complete(self):
        """Test stream single chunk complete tag"""
        extractor = XMLTagExtractor(default_type="think")
        chunks = extractor.extract_stream("<think>完整</think>")
        # There should be at least one chunk containing 'complete'
        deltas = [(c.kv_key, c.kv_delta) for c in chunks if c.kv_delta]
        assert ("think", "完整") in deltas

    def test_extract_stream_partial_tag_across_chunks(self):
        """Test tag split across chunks"""
        extractor = XMLTagExtractor(default_type="think")
        all_chunks = []
        for text in ["<th", "ink>部", "分</think>"]:
            all_chunks.extend(extractor.extract_stream(text))

        think_deltas = [c.kv_delta for c in all_chunks if c.kv_key == "think"]
        assert ''.join(think_deltas) == "部分"

    def test_extract_stream_switch_tags(self):
        """Test stream tag switching"""
        extractor = XMLTagExtractor(default_type="think")
        all_chunks = []
        for text in ["<think>思考</think>", "<answer>答案</answer>"]:
            all_chunks.extend(extractor.extract_stream(text))

        think_deltas = [c.kv_delta for c in all_chunks if c.kv_key == "think"]
        answer_deltas = [c.kv_delta for c in all_chunks if c.kv_key == "answer"]
        assert ''.join(think_deltas) == "思考"
        assert ''.join(answer_deltas) == "答案"

    def test_extract_stream_no_tag(self):
        """Test stream content without tag — OUTSIDE state outputs default_type key"""
        extractor = XMLTagExtractor(default_type="think")
        chunks = extractor.extract_stream("纯文本内容")
        assert len(chunks) > 0
        assert chunks[0].kv_key == "think"
        assert chunks[0].kv_delta == "纯文本内容"

    def test_extract_stream_returns_list(self):
        """Test extract_stream returns list"""
        extractor = XMLTagExtractor(default_type="think")
        result = extractor.extract_stream("")
        assert isinstance(result, list)
        assert len(result) == 0

    def test_flush_stream_inside_tag(self):
        """Test flush inside tag"""
        extractor = XMLTagExtractor(default_type="think")
        extractor.extract_stream("<think>未闭合内容")
        flushed = extractor.flush_stream()
        assert len(flushed) > 0
        assert flushed[0].kv_key == "think"
        assert "未闭合内容" in flushed[0].kv_delta

    def test_flush_stream_outside(self):
        """Test flush in OUTSIDE state"""
        extractor = XMLTagExtractor(default_type="think")
        extractor.extract_stream("残留文本")
        # drain already emitted, buffer is empty
        flushed = extractor.flush_stream()
        # May be empty (since drain already processed) or may have residual
        # The key point is it should not error
        assert isinstance(flushed, list)

    def test_reset_stream_state(self):
        """Test reset stream state"""
        extractor = XMLTagExtractor(default_type="think")
        extractor.extract_stream("<think>部分")
        extractor.reset()

        # After reset, should be able to parse new content normally
        chunks = extractor.extract_stream("<think>新内容</think>")
        think_deltas = [c.kv_delta for c in chunks if c.kv_key == "think"]
        assert ''.join(think_deltas) == "新内容"

    def test_safe_emit_end_partial_close_tag(self):
        """Test _safe_emit_end — buffer ends with closing tag prefix"""
        extractor = XMLTagExtractor(default_type="think")
        # First enter <think> tag
        chunks1 = extractor.extract_stream("<think>content</thi")
        # Buffer tail "</thi" is prefix of "</think>", should not be emitted
        think_deltas = [c.kv_delta for c in chunks1 if c.kv_key == "think"]
        joined = ''.join(think_deltas)
        assert "content" in joined
        assert "</thi" not in joined

        # Complete closing tag
        chunks2 = extractor.extract_stream("nk>")
        # Should not have extra content
        all_think = [c.kv_delta for c in chunks1 + chunks2 if c.kv_key == "think"]
        assert ''.join(all_think) == "content"

    def test_single_chunk_multi_tag_switch(self):
        """Test multiple tag switches in single chunk"""
        extractor = XMLTagExtractor(default_type="think")
        chunks = extractor.extract_stream(
            "<think>思考</think><answer>Hello</answer>"
        )
        think_deltas = [c.kv_delta for c in chunks if c.kv_key == "think"]
        answer_deltas = [c.kv_delta for c in chunks if c.kv_key == "answer"]
        assert ''.join(think_deltas) == "思考"
        assert ''.join(answer_deltas) == "Hello"

    def test_orphan_close_tag_skipped(self):
        """Test orphaned close tag is skipped"""
        extractor = XMLTagExtractor(default_type="think")
        chunks = extractor.extract_stream("</think>Hello")
        # Orphaned </think> should be skipped, Hello output as default_type
        text_deltas = [c.kv_delta for c in chunks if c.kv_key == "think"]
        assert ''.join(text_deltas) == "Hello"

    def test_unknown_tag_treated_as_text(self):
        """Test unknown tag treated as plain text"""
        extractor = XMLTagExtractor(
            default_type="think", known_tags=["think", "answer"]
        )
        chunks = extractor.extract_stream("<unknown>text</unknown>")
        # <unknown> is not in known_tags, should be treated as plain text
        text_deltas = [c.kv_delta for c in chunks if c.kv_key == "think"]
        assert len(text_deltas) > 0

    def test_known_tags_parameter(self):
        """Test known_tags parameter"""
        extractor = XMLTagExtractor(
            default_type="think",
            known_tags=["thinking", "response"],
        )
        chunks = extractor.extract_stream(
            "<thinking>思考</thinking><response>回答</response>"
        )
        think_deltas = [c.kv_delta for c in chunks if c.kv_key == "thinking"]
        resp_deltas = [c.kv_delta for c in chunks if c.kv_key == "response"]
        assert ''.join(think_deltas) == "思考"
        assert ''.join(resp_deltas) == "回答"

    def test_incremental_emission_inside_tag(self):
        """Test incremental emission inside tag"""
        extractor = XMLTagExtractor(default_type="think")
        chunks1 = extractor.extract_stream("<think>第一部分")
        chunks2 = extractor.extract_stream("第二部分")
        chunks3 = extractor.extract_stream("</think>")

        all_think = []
        for c in chunks1 + chunks2 + chunks3:
            if c.kv_key == "think":
                all_think.append(c.kv_delta)

        assert ''.join(all_think) == "第一部分第二部分"

    def test_flush_then_reset_new_round(self):
        """Test flush then reset to start new round"""
        extractor = XMLTagExtractor(default_type="think")

        # Round 1
        extractor.extract_stream("<think>R1</think>")
        extractor.flush_stream()
        extractor.reset()

        # Round 2
        chunks = extractor.extract_stream("<answer>R2</answer>")
        answer_deltas = [c.kv_delta for c in chunks if c.kv_key == "answer"]
        assert ''.join(answer_deltas) == "R2"

    # ------------------------------------------------------------------
    # Implicit close tag tests
    # ------------------------------------------------------------------

    def test_extract_implicit_close(self):
        """Test implicit close scenario: <think>123<answer>ans</answer>"""
        extractor = XMLTagExtractor(default_type="think")
        result = extractor.extract('<think>123<answer>ans</answer></think>')
        assert result.kv_pairs == [
            ("think", "123"),
            ("answer", "ans")
        ]

    def test_extract_nested_in_think(self):
        """Test nesting other tags inside think, truncate when encountering new tag"""
        extractor = XMLTagExtractor(default_type="think")
        result = extractor.extract('<think>思考内容<tool_call>{"name":"test"}</tool_call></think>')
        assert result.kv_pairs == [
            ("think", "思考内容"),
            ("tool_call", '{"name":"test"}')
        ]

    def test_extract_multiple_implicit_closes(self):
        """Test multiple consecutive implicit closes"""
        extractor = XMLTagExtractor(default_type="think")
        result = extractor.extract('<think>A<answer>B<answer>C</think>')
        assert result.kv_pairs == [
            ("think", "A"),
            ("answer", "B"),
            ("answer", "C")
        ]

    def test_stream_implicit_close(self):
        """Test stream implicit close"""
        extractor = XMLTagExtractor(default_type="think")
        chunks = extractor.extract_stream('<think>123<answer>ans</answer></think>')
        think_deltas = [c.kv_delta for c in chunks if c.kv_key == "think"]
        answer_deltas = [c.kv_delta for c in chunks if c.kv_key == "answer"]
        assert ''.join(think_deltas) == "123"
        assert ''.join(answer_deltas) == "ans"

    def test_stream_known_tags_implicit_close(self):
        """Test stream implicit close when known tag nests another known tag"""
        # When another known tag is encountered inside a known tag, implicitly close current tag
        extractor = XMLTagExtractor(default_type="think")
        chunks = extractor.extract_stream('<think>123<answer>456</answer></think>')
        think_deltas = [c.kv_delta for c in chunks if c.kv_key == "think"]
        answer_deltas = [c.kv_delta for c in chunks if c.kv_key == "answer"]
        assert ''.join(think_deltas) == "123"
        assert ''.join(answer_deltas) == "456"

    def test_stream_implicit_close_across_chunks(self):
        """Test stream implicit close across chunks"""
        extractor = XMLTagExtractor(default_type="think")
        chunks1 = extractor.extract_stream('<think>123<answer')
        chunks2 = extractor.extract_stream('>ans</answer></think>')
        think_deltas = [c.kv_delta for c in chunks1 + chunks2 if c.kv_key == "think"]
        answer_deltas = [c.kv_delta for c in chunks1 + chunks2 if c.kv_key == "answer"]
        assert ''.join(think_deltas) == "123"
        assert ''.join(answer_deltas) == "ans"

    # ------------------------------------------------------------------
    # Backtick escape tests
    # ------------------------------------------------------------------

    def test_extract_backtick_escaped_tag(self):
        """Backtick-wrapped tag treated as plain text"""
        extractor = XMLTagExtractor(default_type="think")
        # `<answer>` should be skipped, second <answer> parsed normally
        result = extractor.extract('<answer>`<answer>`text<answer>real</answer>')
        # First and second `<answer>` are skipped, third is normal
        assert result.kv_pairs == [
            ("answer", "`<answer>`text"),
            ("answer", "real"),
        ]

    def test_extract_backtick_escaped_close_tag(self):
        """Backtick-wrapped close tag does not close current tag"""
        extractor = XMLTagExtractor(default_type="think")
        result = extractor.extract('<answer>use `</answer>` to close</answer>')
        assert result.kv_pairs == [
            ("answer", "use `</answer>` to close"),
        ]

    def test_extract_backtick_only_leading_not_escaped(self):
        """Only leading backtick does not trigger escape, tag still parsed normally"""
        extractor = XMLTagExtractor(default_type="think")
        result = extractor.extract('<answer>`text</answer>')
        # Only leading backtick, not a complete escape
        assert result.kv_pairs == [
            ("answer", "`text"),
        ]

    def test_extract_backtick_only_trailing_not_escaped(self):
        """Only trailing backtick does not trigger escape, tag still parsed normally"""
        extractor = XMLTagExtractor(default_type="think")
        result = extractor.extract('<answer>text`</answer>')
        # Only trailing backtick, not a complete escape
        assert result.kv_pairs == [
            ("answer", "text`"),
        ]

    def test_stream_backtick_escaped_open_tag(self):
        """Stream: backtick-wrapped open tag as plain text"""
        extractor = XMLTagExtractor(default_type="think")
        chunks = extractor.extract_stream('<answer>`<answer>` text</answer>')
        answer_deltas = [c.kv_delta for c in chunks if c.kv_key == "answer"]
        joined = ''.join(answer_deltas)
        assert '<answer>`' in joined
        assert '` text' in joined

    def test_stream_backtick_escaped_across_chunks(self):
        """Stream: leading backtick in previous chunk, tag in next chunk"""
        extractor = XMLTagExtractor(default_type="think")
        chunks1 = extractor.extract_stream('<answer>`')
        chunks2 = extractor.extract_stream('<answer>`text</answer>')
        answer_deltas = [c.kv_delta for c in chunks1 + chunks2 if c.kv_key == "answer"]
        joined = ''.join(answer_deltas)
        # First `<answer>` is escaped, second is normal
        assert '<answer>`' in joined
        assert 'text' in joined

    def test_stream_backtick_escaped_trailing_delayed(self):
        """Stream: tag complete but trailing backtick in next chunk (test ambiguous handling)"""
        extractor = XMLTagExtractor(default_type="think")
        # First chunk ends with potentially escaped tag (trailing backtick at buffer end)
        chunks1 = extractor.extract_stream('<answer>`<answer>`')
        # Second chunk continues to complete
        chunks2 = extractor.extract_stream('</answer>')
        answer_deltas = [c.kv_delta for c in chunks1 + chunks2 if c.kv_key == "answer"]
        joined = ''.join(answer_deltas)
        # First `<answer>` is escaped as text
        assert '`<answer>`' in joined

    def test_stream_backtick_escaped_close_inside(self):
        """Stream: `</answer>` inside tag does not trigger close"""
        extractor = XMLTagExtractor(default_type="think")
        chunks = extractor.extract_stream('<answer>use `</answer>` to close</answer>')
        answer_deltas = [c.kv_delta for c in chunks if c.kv_key == "answer"]
        joined = ''.join(answer_deltas)
        assert '`</answer>`' in joined

    def test_stream_same_name_implicit_close(self):
        """Stream: same-name open tag triggers implicit close (consistent with non-stream behavior)"""
        extractor = XMLTagExtractor(default_type="think")
        chunks = extractor.extract_stream('<answer>first<answer>second</answer>')
        answer_deltas = [c.kv_delta for c in chunks if c.kv_key == "answer"]
        # Should produce two segments: "first" and "second"
        assert ''.join(answer_deltas) == "firstsecond"

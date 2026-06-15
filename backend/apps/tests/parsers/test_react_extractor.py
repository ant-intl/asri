"""
ReActExtractor tests
"""
import pytest

from apps.agent.parsers import ReActExtractor


class TestReActExtractor:
    """ReAct extractor tests"""

    def test_extract_standard_format(self):
        """Test standard ReAct format"""
        extractor = ReActExtractor(default_type="think")
        result = extractor.extract(
            "Thought: 让我搜索\nAction: TOOL\nAction Input: search query"
        )
        kv_dict = dict(result.kv_pairs)
        assert kv_dict.get("thought") == "让我搜索"
        assert kv_dict.get("action") == "TOOL"
        assert kv_dict.get("action_input") == "search query"

    def test_extract_finish_action(self):
        """Test FINISH action"""
        extractor = ReActExtractor(default_type="think")
        result = extractor.extract(
            "Thought: 我有足够信息\nAction: FINISH\nAction Input: 最终答案"
        )
        kv_dict = dict(result.kv_pairs)
        assert kv_dict.get("action") == "FINISH"
        assert kv_dict.get("action_input") == "最终答案"

    def test_extract_multiline_thought(self):
        """Test multiline Thought"""
        extractor = ReActExtractor(default_type="think")
        result = extractor.extract(
            "Thought: 第一行\n第二行\n第三行\nAction: FINISH"
        )
        kv_dict = dict(result.kv_pairs)
        assert "第一行\n第二行\n第三行" in kv_dict.get("thought", "")

    def test_extract_no_action(self):
        """Test no Action (plain text)"""
        extractor = ReActExtractor(default_type="think")
        result = extractor.extract("纯文本回答")
        # Use default_type
        assert ("think", "纯文本回答") in result.kv_pairs

    def test_extract_case_insensitive(self):
        """Test case insensitive"""
        extractor = ReActExtractor(default_type="think")
        result = extractor.extract(
            "thought: 思考\naction: tool\naction input: input"
        )
        kv_dict = dict(result.kv_pairs)
        # Should match (case insensitive)
        assert any("thought" in k.lower() for k in kv_dict.keys())

    def test_extract_only_thought(self):
        """Test only Thought without Action"""
        extractor = ReActExtractor(default_type="think")
        result = extractor.extract("Thought: 只是思考")
        kv_dict = dict(result.kv_pairs)
        assert kv_dict.get("thought") == "只是思考"

    def test_extract_stream_partial(self):
        """Test stream partial input"""
        extractor = ReActExtractor(default_type="think")
        # ReAct stream needs to recognize complete pattern
        chunks1 = extractor.extract_stream("Thought: 让我思考")
        chunks2 = extractor.extract_stream("\nAction: FINISH")

        # When Action appears, may return action
        all_chunks = chunks1 + chunks2
        assert len(all_chunks) > 0

    def test_extract_stream_returns_list(self):
        """Test stream returns list"""
        extractor = ReActExtractor(default_type="think")
        result = extractor.extract_stream("partial")
        assert isinstance(result, list)

    def test_flush_stream_with_residual(self):
        """Test flush_stream with residual content"""
        extractor = ReActExtractor(default_type="think")
        # Short content won't trigger fallback
        result = extractor.flush_stream()
        assert isinstance(result, list)

    def test_reset_stream_state(self):
        """Test reset stream state"""
        extractor = ReActExtractor(default_type="think")
        extractor.extract_stream("Thought: 部分")
        extractor.reset()

        # After reset, should be able to parse new content normally
        chunks = extractor.extract_stream("Thought: 新内容\nAction: FINISH")
        assert len(chunks) > 0
        assert any("新内容" in c.kv_delta for c in chunks)

"""
JSONExtractor tests
"""
import json

import pytest

from apps.agent.parsers import JSONExtractor


class TestJSONExtractor:
    """JSON extractor tests"""

    def test_extract_simple_object(self):
        """Test simple object"""
        extractor = JSONExtractor(default_type="think")
        result = extractor.extract('{"think": "思考", "answer": "答案"}')
        assert ("think", "思考") in result.kv_pairs
        assert ("answer", "答案") in result.kv_pairs

    def test_extract_nested_object(self):
        """Test nested object (value should be serialized to string)"""
        extractor = JSONExtractor(default_type="think")
        result = extractor.extract('{"tool": {"name": "search", "input": "query"}}')
        assert result.kv_pairs[0][0] == "tool"
        assert '"name": "search"' in result.kv_pairs[0][1]

    def test_extract_array_value(self):
        """Test array value"""
        extractor = JSONExtractor(default_type="think")
        result = extractor.extract('{"items": ["a", "b", "c"]}')
        assert result.kv_pairs[0][0] == "items"
        assert '["a", "b", "c"]' in result.kv_pairs[0][1]

    def test_extract_empty_object(self):
        """Test empty object"""
        extractor = JSONExtractor(default_type="think")
        result = extractor.extract('{}')
        assert result.kv_pairs == []

    def test_extract_invalid_json(self):
        """Test invalid JSON - use default_type to return raw content"""
        extractor = JSONExtractor(default_type="think")
        result = extractor.extract('{"invalid json')
        # JSON parsing failed, use default_type to return raw content
        assert ("think", '{"invalid json') in result.kv_pairs

    def test_extract_non_object(self):
        """Test non-object type (array)"""
        extractor = JSONExtractor(default_type="think")
        result = extractor.extract('["a", "b", "c"]')
        # Non-object type, use default_type
        assert ("think", '["a", "b", "c"]') in result.kv_pairs

    def test_extract_stream_complete_object(self):
        """Test stream complete object"""
        extractor = JSONExtractor(default_type="think")
        chunks = extractor.extract_stream('{"think": "思考"}')
        assert len(chunks) == 1
        assert chunks[0].kv_key == "think"
        assert chunks[0].kv_delta == "思考"
        assert chunks[0].is_key_complete is True

    def test_extract_stream_multiple_keys(self):
        """Test stream multiple keys - extract_stream returns first key, flush_stream returns remaining keys"""
        extractor = JSONExtractor(default_type="think")
        # Complete JSON
        chunks = extractor.extract_stream('{"think": "思考", "answer": "答案"}')
        # First call returns first key
        assert len(chunks) == 1
        assert chunks[0].kv_key in ["think", "answer"]

        # flush_stream returns remaining keys
        flush_chunks = extractor.flush_stream()
        assert len(flush_chunks) == 1
        assert flush_chunks[0].kv_key in ["think", "answer"]
        # The two keys should not be the same
        assert flush_chunks[0].kv_key != chunks[0].kv_key

    def test_extract_stream_returns_list(self):
        """Test stream returns list"""
        extractor = JSONExtractor(default_type="think")
        result = extractor.extract_stream('{"incomplete')
        assert isinstance(result, list)
        assert len(result) == 0

    def test_flush_stream(self):
        """Test flush_stream returns empty list"""
        extractor = JSONExtractor(default_type="think")
        extractor.extract_stream('{"incomplete')
        result = extractor.flush_stream()
        assert isinstance(result, list)
        assert len(result) == 0

    def test_reset_stream_state(self):
        """Test reset stream state"""
        extractor = JSONExtractor(default_type="think")
        extractor.extract_stream('{"think": "')
        extractor.reset()

        # After reset, should be able to parse new content normally
        chunks = extractor.extract_stream('{"new": "内容"}')
        assert len(chunks) == 1
        assert chunks[0].kv_key == "new"

"""
OutputMapper tests
"""
import json

import pytest

from apps.agent.parsers import OutputMapper, LLMRes, LLMResChunk


class TestOutputMapper:
    """Output mapper tests"""

    def test_map_tool(self):
        """Test mapping tool"""
        mapper = OutputMapper(
            tool_keys=["tool_call", "tool"],
            think_keys=["think"],
            answer_keys=["answer"]
        )
        llm_res = LLMRes(
            kv_pairs=[("tool_call", '{"name": "search", "input": "query"}')],
            content=""
        )
        output = mapper.map(llm_res)

        assert output.tool is not None
        assert output.tool.name == "search"
        assert output.tool.input == {"name": "search", "input": "query"}

    def test_map_think(self):
        """Test mapping think"""
        mapper = OutputMapper(
            tool_keys=["tool_call"],
            think_keys=["think", "thinking"],
            answer_keys=["answer"]
        )
        llm_res = LLMRes(
            kv_pairs=[("thinking", "让我思考")],
            content=""
        )
        output = mapper.map(llm_res)

        assert output.think == "让我思考"
        assert output.tool is None

    def test_map_answer(self):
        """Test mapping answer"""
        mapper = OutputMapper(
            tool_keys=["tool_call"],
            think_keys=["think"],
            answer_keys=["answer", "content"]
        )
        llm_res = LLMRes(
            kv_pairs=[("content", "这是答案")],
            content=""
        )
        output = mapper.map(llm_res)

        assert output.answer == "这是答案"

    def test_map_priority(self):
        """Test key priority"""
        mapper = OutputMapper(
            tool_keys=["tool_call", "tool"],
            think_keys=["think"],
            answer_keys=["answer"]
        )
        # Should match tool_call (higher priority)
        llm_res = LLMRes(
            kv_pairs=[("tool_call", '{"name": "search"}')],
            content=""
        )
        output = mapper.map(llm_res)

        assert output.tool is not None
        assert output.tool.name == "search"

    def test_map_all_three(self):
        """Test mapping all three types simultaneously"""
        mapper = OutputMapper(
            tool_keys=["tool_call"],
            think_keys=["think"],
            answer_keys=["answer"]
        )
        llm_res = LLMRes(
            kv_pairs=[
                ("think", "思考过程"),
                ("tool_call", '{"name": "search"}'),
                ("answer", "部分答案")
            ],
            content=""
        )
        output = mapper.map(llm_res)

        assert output.think == "思考过程"
        assert output.tool is not None
        assert output.answer == "部分答案"

    def test_map_invalid_tool_json(self):
        """Test invalid tool JSON"""
        mapper = OutputMapper(
            tool_keys=["tool_call"],
            think_keys=["think"],
            answer_keys=["answer"]
        )
        llm_res = LLMRes(
            kv_pairs=[("tool_call", "invalid json")],
            content=""
        )
        # JSON parsing failed, should output as answer
        output = mapper.map(llm_res)
        assert output.tool is None
        assert output.answer == "invalid json"

    def test_map_stream_think(self):
        """Test stream think mapping"""
        mapper = OutputMapper(
            tool_keys=["tool_call"],
            think_keys=["think"],
            answer_keys=["answer"]
        )
        chunk = LLMResChunk(
            kv_key="think",
            kv_delta="让我",
            is_key_complete=False,
            raw_delta="让"
        )
        output_chunk = mapper.map_stream(chunk)

        assert output_chunk.type == "think"
        assert output_chunk.content == "让我"
        assert output_chunk.is_complete is False

    def test_map_stream_tool_complete(self):
        """Test stream tool completion"""
        mapper = OutputMapper(
            tool_keys=["tool_call"],
            think_keys=["think"],
            answer_keys=["answer"]
        )
        # Accumulate tool content (incremental delta)
        mapper.map_stream(LLMResChunk("tool_call", '{"name": "sea', False, ""))
        mapper.map_stream(LLMResChunk("tool_call", 'rch", "input": ', False, ""))
        chunk = mapper.map_stream(
            LLMResChunk("tool_call", '"q"}', True, "")
        )

        assert chunk.type == "tool"
        assert chunk.is_complete is True
        assert chunk.content == {"name": "search", "input": "q"}

    def test_map_stream_answer(self):
        """Test stream answer mapping"""
        mapper = OutputMapper(
            tool_keys=["tool_call"],
            think_keys=["think"],
            answer_keys=["answer", "content"]
        )
        chunk = LLMResChunk(
            kv_key="content",
            kv_delta="这是答案",
            is_key_complete=True,
            raw_delta=""
        )
        output_chunk = mapper.map_stream(chunk)

        assert output_chunk.type == "answer"
        assert output_chunk.content == "这是答案"
        assert output_chunk.is_complete is True

    def test_reset_stream_state(self):
        """Test reset stream state"""
        mapper = OutputMapper(
            tool_keys=["tool_call"],
            think_keys=["think"],
            answer_keys=["answer"]
        )
        # Accumulate partial content
        mapper.map_stream(LLMResChunk(kv_key="tool_call", kv_delta='{"name": "sea', is_key_complete=False, raw_delta=""))
        mapper.reset()

        # After reset, should be able to parse new content normally
        chunk = mapper.map_stream(
            LLMResChunk(kv_key="tool_call", kv_delta='{"name": "new"}', is_key_complete=True, raw_delta="")
        )
        assert chunk is not None
        assert chunk.content == {"name": "new"}

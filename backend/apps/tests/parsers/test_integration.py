"""
Integration tests
"""
import pytest

from apps.agent.parsers import (
    XMLTagExtractor,
    JSONExtractor,
    ReActExtractor,
    OutputMapper,
    OutputParserFactory,
)


class TestIntegration:
    """Integration tests"""

    def test_xml_to_output(self):
        """Test XML full flow"""
        extractor = XMLTagExtractor(default_type="think")
        mapper = OutputMapper(
            tool_keys=["tool_call"],
            think_keys=["think"],
            answer_keys=["answer"]
        )

        llm_res = extractor.extract(
            '<think>让我搜索</think><tool_call>{"name": "search"}</tool_call>'
        )
        output = mapper.map(llm_res)

        assert output.think == "让我搜索"
        assert output.tool.name == "search"

    def test_json_to_output(self):
        """Test JSON full flow"""
        extractor = JSONExtractor(default_type="think")
        mapper = OutputMapper(
            tool_keys=["tool"],
            think_keys=["think"],
            answer_keys=["answer"]
        )

        llm_res = extractor.extract(
            '{"think": "思考", "tool": {"name": "calc"}, "answer": "结果"}'
        )
        output = mapper.map(llm_res)

        assert output.think == "思考"
        assert output.tool.name == "calc"
        assert output.answer == "结果"

    def test_react_to_output(self):
        """Test ReAct full flow"""
        extractor = ReActExtractor(default_type="think")
        mapper = OutputMapper(
            tool_keys=["action"],
            think_keys=["thought"],
            answer_keys=["action_input"]
        )

        llm_res = extractor.extract(
            "Thought: 让我计算\nAction: TOOL\nAction Input: 1+1"
        )
        output = mapper.map(llm_res)

        assert output.think == "让我计算"
        # action mapped as tool, but action value "TOOL" is not JSON
        # In this case tool parsing will fail, fallback to answer
        assert output.answer == "TOOL"

    def test_stream_xml_to_output(self):
        """Test XML stream full flow"""
        extractor = XMLTagExtractor(default_type="think")
        mapper = OutputMapper(
            tool_keys=["tool_call"],
            think_keys=["think"],
            answer_keys=["answer"]
        )

        chunks = []
        for text in ["<think>思", "考</think>", '<tool_call>{"name": "', 'search"}</tool_call>']:
            for res_chunk in extractor.extract_stream(text):
                output_chunk = mapper.map_stream(res_chunk)
                if output_chunk:
                    chunks.append(output_chunk)

        # Verify stream output
        think_chunks = [c for c in chunks if c.type == "think"]
        tool_chunks = [c for c in chunks if c.type == "tool"]

        assert len(think_chunks) > 0
        assert len(tool_chunks) > 0
        assert tool_chunks[-1].is_complete is True
        assert tool_chunks[-1].content == {"name": "search"}

    def test_factory_create_xml(self):
        """Test factory creates XML parser"""
        extractor_cfg = {"type": "xml_tags", "default_type": "think"}
        mapper_cfg = {
            "tool_keys": ["tool_call"],
            "think_keys": ["think"],
            "answer_keys": ["answer"]
        }

        extractor, mapper = OutputParserFactory.create(extractor_cfg, mapper_cfg)

        assert isinstance(extractor, XMLTagExtractor)
        assert extractor.default_type == "think"

    def test_factory_create_json(self):
        """Test factory creates JSON parser"""
        extractor_cfg = {"type": "json", "default_type": "think"}
        mapper_cfg = {
            "tool_keys": ["tool"],
            "think_keys": ["think"],
            "answer_keys": ["answer"]
        }

        extractor, mapper = OutputParserFactory.create(extractor_cfg, mapper_cfg)

        assert isinstance(extractor, JSONExtractor)

    def test_factory_create_react(self):
        """Test factory creates ReAct parser"""
        extractor_cfg = {"type": "react", "default_type": "think"}
        mapper_cfg = {
            "tool_keys": ["action"],
            "think_keys": ["thought"],
            "answer_keys": ["action_input"]
        }

        extractor, mapper = OutputParserFactory.create(extractor_cfg, mapper_cfg)

        assert isinstance(extractor, ReActExtractor)

    def test_factory_unknown_type(self):
        """Test factory unknown type"""
        extractor_cfg = {"type": "unknown"}
        mapper_cfg = {}

        with pytest.raises(ValueError) as exc_info:
            OutputParserFactory.create(extractor_cfg, mapper_cfg)

        assert "Unknown extractor type" in str(exc_info.value)

    def test_end_to_end_xml(self):
        """Test XML end-to-end scenario"""
        extractor_cfg = {"type": "xml_tags", "default_type": "think"}
        mapper_cfg = {
            "tool_keys": ["tool_call"],
            "think_keys": ["think"],
            "answer_keys": ["answer"]
        }

        extractor, mapper = OutputParserFactory.create(extractor_cfg, mapper_cfg)

        # Simulate LLM output
        llm_response = '<think>用户询问天气</think><tool_call>{"name": "weather", "city": "北京"}</tool_call><answer>北京今天晴朗</answer>'

        llm_res = extractor.extract(llm_response)
        output = mapper.map(llm_res)

        assert output.think == "用户询问天气"
        assert output.tool.name == "weather"
        assert output.answer == "北京今天晴朗"

    def test_end_to_end_stream_xml(self):
        """Test XML stream end-to-end"""
        extractor_cfg = {"type": "xml_tags", "default_type": "think"}
        mapper_cfg = {
            "tool_keys": ["tool_call"],
            "think_keys": ["think"],
            "answer_keys": ["answer"]
        }

        extractor, mapper = OutputParserFactory.create(extractor_cfg, mapper_cfg)

        # Simulate stream input
        stream_chunks = [
            "<think>用户询问",
            "天气</think>",
            "<answer>北京",
            "今天晴朗</answer>",
        ]

        output_chunks = []
        for text in stream_chunks:
            for res_chunk in extractor.extract_stream(text):
                out = mapper.map_stream(res_chunk)
                if out is not None:
                    output_chunks.append(out)

        # flush
        for res_chunk in extractor.flush_stream():
            out = mapper.map_stream(res_chunk)
            if out is not None:
                output_chunks.append(out)

        think_content = ''.join(
            str(c.content) for c in output_chunks if c.type == "think"
        )
        answer_content = ''.join(
            str(c.content) for c in output_chunks if c.type == "answer"
        )

        assert "用户询问天气" == think_content
        assert "北京今天晴朗" == answer_content

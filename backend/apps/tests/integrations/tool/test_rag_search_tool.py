"""
Tests for RAG Search Tool.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.integrations.rag import RAGSearchTool


# -----------------------------------------------------------------------------
# Tests: RAGSearchTool
# -----------------------------------------------------------------------------

class TestRAGSearchTool:
    """Test RAGSearchTool implementation."""

    def test_name_class_attribute(self):
        """name is a class attribute."""
        assert RAGSearchTool.name == 'rag_search'

    def test_description_property(self):
        """description is a property."""
        tool = RAGSearchTool()
        assert tool.description == "使用此工具查询任何与业务有关的FAQ及知识"

    def test_parameters_schema(self):
        """parameters_schema is defined."""
        assert 'query' in RAGSearchTool.parameters_schema['properties']
        assert 'coreQuestion' in RAGSearchTool.parameters_schema['properties']

    def test_is_enabled_default(self):
        """enabled is True by default."""
        tool = RAGSearchTool()
        assert tool._is_enabled() is True

    def test_is_enabled_from_config(self):
        """enabled can be set from config."""
        tool = RAGSearchTool(config={'enabled': False})
        assert tool._is_enabled() is False

    @pytest.mark.asyncio
    async def test_execute_disabled(self):
        """Returns error when tool is disabled."""
        tool = RAGSearchTool(config={'enabled': False})

        result = await tool.execute('test query', None)

        assert 'disabled' in result.lower()

    @pytest.mark.asyncio
    async def test_execute_query_required(self):
        """Returns error when query is missing."""
        tool = RAGSearchTool(config={
            'enabled': True,
            'config': {'rag_url': 'http://test', 'biz_user_id': 'test'}
        })

        result = await tool.execute('', None)

        assert 'required' in result.lower()

    @pytest.mark.asyncio
    async def test_execute_no_provider(self):
        """Returns error when no RAG provider configured."""
        tool = RAGSearchTool(config={'enabled': True, 'config': {}})

        result = await tool.execute('test query', None)

        assert 'not configured' in result.lower() or 'error' in result.lower()

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Returns search results on success."""
        tool = RAGSearchTool(config={
            'enabled': True,
            'rag_url': 'http://test',
            'biz_user_id': 'test'
        })

        mock_provider = AsyncMock()
        mock_provider.search = AsyncMock(return_value=[
            {'content': 'Result 1'},
            {'content': 'Result 2'}
        ])

        with patch('apps.integrations.rag.rag_search_tool.FAQRAGProvider', return_value=mock_provider):
            result = await tool.execute('test query', None)

        assert 'Result 1' in result
        assert 'Result 2' in result

    @pytest.mark.asyncio
    async def test_execute_with_top_k(self):
        """top_k parameter is correctly passed."""
        tool = RAGSearchTool(config={
            'enabled': True,
            'rag_url': 'http://test',
            'biz_user_id': 'test'
        })

        mock_provider = AsyncMock()
        mock_provider.search = AsyncMock(return_value=[])

        with patch('apps.integrations.rag.rag_search_tool.FAQRAGProvider', return_value=mock_provider):
            await tool.execute('{"query": "test", "top_k": 10}', None)

        # Check that top_k was passed correctly
        mock_provider.search.assert_called_once_with('test', top_k=10)

    @pytest.mark.asyncio
    async def test_execute_handles_exception(self):
        """Handles exceptions gracefully."""
        tool = RAGSearchTool(config={
            'enabled': True,
            'rag_url': 'http://test',
            'biz_user_id': 'test'
        })

        mock_provider = AsyncMock()
        mock_provider.search = AsyncMock(side_effect=Exception('Connection error'))

        with patch('apps.integrations.rag.rag_search_tool.FAQRAGProvider', return_value=mock_provider):
            result = await tool.execute('test query', None)

        assert 'failed' in result.lower() or 'error' in result.lower()

    @pytest.mark.asyncio
    async def test_execute_empty_results(self):
        """Handles empty results."""
        tool = RAGSearchTool(config={
            'enabled': True,
            'rag_url': 'http://test',
            'biz_user_id': 'test'
        })

        mock_provider = AsyncMock()
        mock_provider.search = AsyncMock(return_value=[])

        with patch('apps.integrations.rag.rag_search_tool.FAQRAGProvider', return_value=mock_provider):
            result = await tool.execute('test query', None)

        # Empty results should return empty string
        assert result == ''

    @pytest.mark.asyncio
    async def test_get_provider_missing_rag_url(self):
        """Returns None when rag_url is missing."""
        tool = RAGSearchTool(config={'enabled': True, 'biz_user_id': 'test'})

        provider = tool._get_provider()

        assert provider is None

    @pytest.mark.asyncio
    async def test_get_provider_missing_biz_user_id(self):
        """Returns None when biz_user_id is missing."""
        tool = RAGSearchTool(config={'enabled': True, 'rag_url': 'http://test'})

        provider = tool._get_provider()

        assert provider is None


# -----------------------------------------------------------------------------
# Tests: Input Parsing
# -----------------------------------------------------------------------------

class TestRAGSearchToolInputParsing:
    """Test RAGSearchTool input parsing."""

    def test_parse_input_json(self):
        """_parse_input() parses JSON input."""
        tool = RAGSearchTool()

        result = tool._parse_input('{"query": "test", "top_k": 5}')

        assert result == {'query': 'test', 'top_k': 5}

    def test_parse_input_plain_text(self):
        """_parse_input() treats plain text as query."""
        tool = RAGSearchTool()

        result = tool._parse_input('plain text query')

        assert result == {'query': 'plain text query'}

    def test_parse_input_empty(self):
        """_parse_input() returns empty dict for empty input."""
        tool = RAGSearchTool()

        result = tool._parse_input('')

        assert result == {'query': ''}

    def test_parse_input_invalid_json(self):
        """_parse_input() falls back to query for invalid JSON."""
        tool = RAGSearchTool()

        result = tool._parse_input('not valid json {')

        assert 'query' in result


# -----------------------------------------------------------------------------
# Tests: Tool Schema
# -----------------------------------------------------------------------------

class TestRAGSearchToolSchema:
    """Test RAGSearchTool schema generation."""

    def test_to_tool_schema(self):
        """to_tool_schema() returns correct format."""
        tool = RAGSearchTool()
        schema = tool.to_tool_schema()

        assert schema['type'] == 'function'
        assert schema['function']['name'] == 'rag_search'
        assert 'query' in schema['function']['parameters']['properties']

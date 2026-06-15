"""Tests for security utilities."""

import pytest

from apps.utils.security import mask_api_key, is_masked_value


class TestMaskApiKey:
    """Test cases for mask_api_key function."""

    def test_empty_string_returns_not_configured(self):
        """Empty string should return 'not_configured'."""
        assert mask_api_key('') == 'not_configured'

    def test_whitespace_only_returns_not_configured(self):
        """Whitespace-only string should return 'not_configured'."""
        assert mask_api_key('   ') == 'not_configured'
        assert mask_api_key('\t\n') == 'not_configured'

    def test_none_returns_not_configured(self):
        """None value should return 'not_configured'."""
        assert mask_api_key(None) == 'not_configured'

    def test_encrypted_value_returns_configured(self):
        """Non-empty value should return 'configured'."""
        assert mask_api_key('encrypted_value_123') == 'configured'
        assert mask_api_key('sk-test-api-key') == 'configured'

    def test_realistic_encrypted_key_returns_configured(self):
        """Realistic encrypted key should return 'configured'."""
        assert mask_api_key('gAAAAABhABC123xyz') == 'configured'


class TestIsMaskedValue:
    """Test cases for is_masked_value function."""

    def test_configured_is_masked(self):
        """'configured' should be recognized as masked value."""
        assert is_masked_value('configured') is True

    def test_not_configured_is_masked(self):
        """'not_configured' should be recognized as masked value."""
        assert is_masked_value('not_configured') is True

    def test_real_api_key_is_not_masked(self):
        """Real API key should not be recognized as masked value."""
        assert is_masked_value('sk-abc123xyz') is False
        assert is_masked_value('gAAAAABhABC123xyz') is False

    def test_none_is_not_masked(self):
        """None should not be recognized as masked value."""
        assert is_masked_value(None) is False

    def test_empty_string_is_not_masked(self):
        """Empty string should not be recognized as masked value."""
        assert is_masked_value('') is False

    def test_partial_match_not_masked(self):
        """Partial match should not be masked."""
        assert is_masked_value('configured_key') is False
        assert is_masked_value('not_config') is False

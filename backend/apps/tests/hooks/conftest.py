"""
Shared fixtures for hook tests.
"""
from unittest.mock import MagicMock

import pytest

from apps.agent.hooks.base import HookManager


@pytest.fixture
def mock_agent_context():
    """Return a minimal AgentContext-like object.

    ToolRuleDenyHook.on_tool_pre_execute accepts ``context`` but does not
    actually read any attributes from it, so a simple MagicMock suffices.
    """
    return MagicMock(
        session_id="test-session",
        user_id="test-user",
        tenant_id="tenant-1",
    )


@pytest.fixture
def sample_rules_config():
    """Return a typical tool_rule_deny configuration dict with one rule."""
    return {
        "rules": [
            {
                "name": "deny-kyc",
                "tool_name": "mcpToolExecute",
                "deny_message": "拒绝 {value} ({tool})",
                "conditions": [
                    {
                        "path": "mcpExecuteTools.*.mcpToolName",
                        "op": "not_in",
                        "value": ["kycSummaryQuery", "certifyFailReasonQuery"],
                    }
                ],
            }
        ]
    }


@pytest.fixture
def empty_hook_manager():
    """Return a fresh empty HookManager."""
    return HookManager()

"""Shared fixtures for dev-infra tests."""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest
from models import AgentConfig

SAMPLE_AGENTS = [
    AgentConfig(label="agent:claude", branch_prefix="claude/", name="Agent A", mention="@claude", harness="claude", model_id="global.anthropic.claude-opus-4-6-v1", model_label="opus-4-6"),
    AgentConfig(label="agent:codex", branch_prefix="codex/", name="Agent B", mention="@codex", harness="codex", model_id="gpt-5.3-codex", model_label="gpt-5.3"),
    AgentConfig(label="agent:openhands", branch_prefix="openhands/", name="Agent C", mention="@openhands-agent", harness="openhands", model_id="gemini/gemini-3.1-pro-preview", model_label="gemini-3.1-pro"),
]

SAMPLE_STATUS_TABLE = """## Agent Implementations

| Agent | Status | PR | Preview | Run |
|-------|--------|-----|---------|-----|
| Agent A | ⏳ Running... |  |  |  |
| Agent B | ⏳ Running... |  |  |  |
| Agent C | ⏳ Running... |  |  |  |

---
*Agents are working on this issue. This comment will be updated as each completes.*"""

SAMPLE_STATUS_TABLE_DONE = """## Agent Implementations

| Agent | Status | PR | Preview | Run |
|-------|--------|-----|---------|-----|
| Agent A | ✅ Done | #10 |  | [Logs](https://example.com/run1) |
| Agent B | ✅ Done | #11 |  | [Logs](https://example.com/run2) |
| Agent C | ❌ Failed |  |  | [Logs](https://example.com/run3) |

---
*Agents are working on this issue. This comment will be updated as each completes.*"""


@pytest.fixture
def agents():
    return SAMPLE_AGENTS.copy()


@pytest.fixture
def status_table():
    return SAMPLE_STATUS_TABLE


@pytest.fixture
def status_table_done():
    return SAMPLE_STATUS_TABLE_DONE

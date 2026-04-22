"""Tests for scripts/models.py — dataclass config models."""

from __future__ import annotations  # noqa: I001

import os, sys  # noqa: E401

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import pytest  # noqa: E402, I001
from models import AgentConfig, ChecksConfig, LLMConfig, LBMConfig  # noqa: E402

# ---------------------------------------------------------------------------
# Sample TOML dicts (as parsed by tomllib)
# ---------------------------------------------------------------------------

FULL_TOML_DICT = {
    "harnesses": {
        "claude": {"mention": "@claude"},
        "codex": {"mention": "@codex"},
    },
    "agents": [
        {
            "harness": "claude",
            "model_id": "claude-opus-4-6",
            "model_label": "opus-4-6",
        },
        {
            "harness": "codex",
            "model_id": "gpt-5.3",
            "model_label": "gpt-5.3",
        },
    ],
    "checks": {
        "required": ["CI", "Lint"],
        "repair_from": ["CI"],
        "max_repair_attempts": 5,
        "max_ralph_loops": 2,
    },
    "llm": {
        "provider": "portkey",
        "summary_model": "custom-model",
    },
}

MINIMAL_TOML_DICT = {
    "harnesses": {
        "claude": {"mention": "@claude"},
    },
    "agents": [
        {
            "harness": "claude",
            "model_id": "claude-sonnet-4-6",
            "model_label": "sonnet-4-6",
        },
    ],
}


# ---------------------------------------------------------------------------
# AgentConfig tests
# ---------------------------------------------------------------------------


class TestAgentConfig:
    def test_from_dict_round_trip(self):
        d = {
            "label": "agent:claude",
            "harness": "claude",
            "model_id": "claude-opus-4-6",
            "model_label": "opus-4-6",
            "branch_prefix": "claude-opus-4-6/",
            "name": "Agent A",
            "mention": "@claude",
        }
        agent = AgentConfig.from_dict(d)
        assert agent.label == "agent:claude"
        assert agent.harness == "claude"
        assert agent.model_id == "claude-opus-4-6"
        assert agent.model_label == "opus-4-6"
        assert agent.branch_prefix == "claude-opus-4-6/"
        assert agent.name == "Agent A"
        assert agent.mention == "@claude"

    def test_from_dict_is_frozen(self):
        d = {
            "label": "agent:claude",
            "harness": "claude",
            "model_id": "x",
            "model_label": "y",
            "branch_prefix": "claude/",
            "name": "Agent A",
            "mention": "@claude",
        }
        agent = AgentConfig.from_dict(d)
        with pytest.raises(Exception):
            agent.label = "new-label"  # type: ignore[misc]

    def test_from_dict_all_fields_required(self):
        with pytest.raises((KeyError, TypeError)):
            AgentConfig.from_dict({"label": "only-label"})


# ---------------------------------------------------------------------------
# ChecksConfig tests
# ---------------------------------------------------------------------------


class TestChecksConfig:
    def test_from_dict_with_all_fields(self):
        d = {
            "required": ["CI", "Lint"],
            "repair_from": ["CI"],
            "max_repair_attempts": 5,
            "max_ralph_loops": 3,
        }
        cfg = ChecksConfig.from_dict(d)
        assert cfg.required == ["CI", "Lint"]
        assert cfg.repair_from == ["CI"]
        assert cfg.max_repair_attempts == 5
        assert cfg.max_ralph_loops == 3

    def test_from_dict_defaults(self):
        cfg = ChecksConfig.from_dict({})
        assert cfg.required == []
        assert cfg.repair_from == []
        assert cfg.max_repair_attempts == 10
        assert cfg.max_ralph_loops == 0

    def test_from_dict_partial_overrides(self):
        cfg = ChecksConfig.from_dict({"max_repair_attempts": 3})
        assert cfg.max_repair_attempts == 3
        assert cfg.required == []
        assert cfg.max_ralph_loops == 0

    def test_from_dict_empty_is_same_as_defaults(self):
        cfg_empty = ChecksConfig.from_dict({})
        cfg_default = ChecksConfig()
        assert cfg_empty.required == cfg_default.required
        assert cfg_empty.max_repair_attempts == cfg_default.max_repair_attempts


# ---------------------------------------------------------------------------
# LLMConfig tests
# ---------------------------------------------------------------------------


class TestLLMConfig:
    def test_from_dict_defaults(self):
        cfg = LLMConfig.from_dict({})
        assert cfg.provider == "anthropic"
        assert cfg.summary_model == "claude-sonnet-4-6"

    def test_from_dict_portkey_override(self):
        cfg = LLMConfig.from_dict({"provider": "portkey", "summary_model": "custom-model"})
        assert cfg.provider == "portkey"
        assert cfg.summary_model == "custom-model"

    def test_from_dict_partial(self):
        cfg = LLMConfig.from_dict({"provider": "portkey"})
        assert cfg.provider == "portkey"
        assert cfg.summary_model == "claude-sonnet-4-6"

    def test_from_dict_is_frozen(self):
        cfg = LLMConfig.from_dict({})
        with pytest.raises(Exception):
            cfg.provider = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# LBMConfig tests
# ---------------------------------------------------------------------------


class TestLBMConfig:
    def test_from_parsed_toml_full(self):
        cfg = LBMConfig.from_parsed_toml(FULL_TOML_DICT)

        # Two agents
        assert len(cfg.agents) == 2

        # First agent: claude
        a0 = cfg.agents[0]
        assert a0.harness == "claude"
        assert a0.model_id == "claude-opus-4-6"
        assert a0.model_label == "opus-4-6"
        assert a0.label == "agent:claude-opus-4-6"
        assert a0.branch_prefix == "claude-opus-4-6/"
        assert a0.name == "Agent A"
        assert a0.mention == "@claude"

        # Second agent: codex
        a1 = cfg.agents[1]
        assert a1.harness == "codex"
        assert a1.name == "Agent B"
        assert a1.mention == "@codex"
        assert a1.label == "agent:codex-gpt-5.3"
        assert a1.branch_prefix == "codex-gpt-5.3/"

        # Checks
        assert cfg.checks.required == ["CI", "Lint"]
        assert cfg.checks.repair_from == ["CI"]
        assert cfg.checks.max_repair_attempts == 5
        assert cfg.checks.max_ralph_loops == 2

        # LLM
        assert cfg.llm.provider == "portkey"
        assert cfg.llm.summary_model == "custom-model"

    def test_from_parsed_toml_minimal(self):
        cfg = LBMConfig.from_parsed_toml(MINIMAL_TOML_DICT)

        # One agent
        assert len(cfg.agents) == 1
        a0 = cfg.agents[0]
        assert a0.harness == "claude"
        assert a0.name == "Agent A"
        assert a0.label == "agent:claude-sonnet-4-6"
        assert a0.branch_prefix == "claude-sonnet-4-6/"

        # Checks use defaults
        assert cfg.checks.required == []
        assert cfg.checks.max_repair_attempts == 10
        assert cfg.checks.max_ralph_loops == 0

        # LLM uses defaults
        assert cfg.llm.provider == "anthropic"
        assert cfg.llm.summary_model == "claude-sonnet-4-6"

    def test_from_parsed_toml_with_override_label(self):
        raw = {
            "harnesses": {"claude": {"mention": "@claude"}},
            "agents": [
                {
                    "harness": "claude",
                    "model_id": "x",
                    "model_label": "y",
                    "override_label": "agent:claude",
                    "override_branch_prefix": "claude/",
                }
            ],
        }
        cfg = LBMConfig.from_parsed_toml(raw)
        assert cfg.agents[0].label == "agent:claude"
        assert cfg.agents[0].branch_prefix == "claude/"

    def test_from_parsed_toml_duplicate_prefix_raises(self):
        raw = {
            "harnesses": {
                "claude": {"mention": "@claude"},
                "codex": {"mention": "@codex"},
            },
            "agents": [
                {
                    "harness": "claude",
                    "model_id": "x",
                    "model_label": "y",
                    "override_branch_prefix": "shared/",
                },
                {
                    "harness": "codex",
                    "model_id": "z",
                    "model_label": "y",
                    "override_branch_prefix": "shared/",
                },
            ],
        }
        with pytest.raises(ValueError, match="Duplicate branch_prefix"):
            LBMConfig.from_parsed_toml(raw)

    def test_from_parsed_toml_undefined_harness_raises(self):
        raw = {
            "harnesses": {"claude": {"mention": "@claude"}},
            "agents": [
                {
                    "harness": "nonexistent",
                    "model_id": "x",
                    "model_label": "y",
                }
            ],
        }
        with pytest.raises(ValueError, match="not defined in"):
            LBMConfig.from_parsed_toml(raw)

    def test_from_parsed_toml_name_letters(self):
        raw = {
            "harnesses": {
                "h1": {"mention": "@h1"},
                "h2": {"mention": "@h2"},
                "h3": {"mention": "@h3"},
            },
            "agents": [
                {"harness": "h1", "model_id": "a", "model_label": "m1"},
                {"harness": "h2", "model_id": "b", "model_label": "m2"},
                {"harness": "h3", "model_id": "c", "model_label": "m3"},
            ],
        }
        cfg = LBMConfig.from_parsed_toml(raw)
        assert cfg.agents[0].name == "Agent A"
        assert cfg.agents[1].name == "Agent B"
        assert cfg.agents[2].name == "Agent C"

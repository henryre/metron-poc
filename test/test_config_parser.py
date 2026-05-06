"""Tests for scripts/config_parser.py."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import config_parser

SAMPLE_TOML = """
[lbm]
version = 1
ready_label = "ready-for-dev"
guidance_file = "AGENTS.md"

[build]
runtime = "node"
install = "npm ci"
lint = "npm run lint"
typecheck = "npx tsc --noEmit"
build = "npm run build"
verify = "npm run verify"

[checks]
required = ["CI"]
repair_from = ["CI"]
max_repair_attempts = 10

[deploy]
platform = "vercel"
preview_env = "Preview"

[database]
orm = "prisma"
validate = "npx prisma validate"

[llm]
provider = "portkey"
summary_model = "@bedrock/global.anthropic.claude-sonnet-4-6"

[harnesses.claude]
mention = "@claude"

[harnesses.codex]
mention = "@codex"

[[agents]]
harness = "claude"
model_id = "claude-opus-4-6"
model_label = "opus-4-6"

[[agents]]
harness = "codex"
model_id = "gpt-5.3"
model_label = "gpt-5.3"
"""


@pytest.fixture
def config():
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
    return tomllib.loads(SAMPLE_TOML)


class TestGetBuildCommands:
    def test_returns_all_commands(self, config):
        cmds = config_parser.get_build_commands(config)
        assert cmds["install"] == "npm ci"
        assert cmds["lint"] == "npm run lint"
        assert cmds["build"] == "npm run build"
        assert cmds["verify"] == "npm run verify"

    def test_runtime_defaults_applied(self):
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib
        minimal = tomllib.loads('[build]\nruntime = "python"\ninstall = "pip install ."')
        cmds = config_parser.get_build_commands(minimal)
        assert cmds["install"] == "pip install ."
        # Python runtime supplies default lint
        assert cmds["lint"] == "ruff check ."


class TestGetAgents:
    def test_returns_agents_with_defaults(self, config):
        agents = config_parser.get_agents(config)
        assert len(agents) == 2
        assert agents[0]["harness"] == "claude"
        assert agents[0]["mention"] == "@claude"
        assert agents[0]["name"] == "Agent A"
        assert agents[0]["label"] == "agent:claude-opus-4-6"
        assert agents[0]["branch_prefix"] == "claude-opus-4-6/"

    def test_override_label(self):
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib
        toml = """
[harnesses.claude]
mention = "@claude"
[[agents]]
harness = "claude"
model_id = "x"
model_label = "y"
override_label = "agent:claude"
override_branch_prefix = "claude/"
"""
        config = tomllib.loads(toml)
        agents = config_parser.get_agents(config)
        assert agents[0]["label"] == "agent:claude"
        assert agents[0]["branch_prefix"] == "claude/"


class TestGetCheckNames:
    def test_returns_required(self, config):
        checks = config_parser.get_check_names(config)
        assert checks == ["CI"]


class TestGetDeployPlatform:
    def test_returns_platform(self, config):
        assert config_parser.get_deploy_platform(config) == "vercel"


class TestDeriveAllowedTools:
    def test_node_runtime(self, config):
        agent = config_parser.get_agents(config)[0]
        tools = config_parser.derive_allowed_tools(config, agent)
        assert any("npm run lint" in t for t in tools)
        assert any("npm run build" in t for t in tools)
        assert any("git status" in t for t in tools)

    def test_python_runtime(self):
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib
        config = tomllib.loads("""
[build]
runtime = "python"
install = "pip install ."
lint = "ruff check ."
[harnesses.claude]
mention = "@claude"
[[agents]]
harness = "claude"
model_id = "x"
model_label = "y"
""")
        agent = config_parser.get_agents(config)[0]
        tools = config_parser.derive_allowed_tools(config, agent)
        assert any("pip" in t for t in tools)
        assert any("ruff" in t for t in tools)


class TestGetDeployConfig:
    def test_returns_full_config(self):
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib
        toml = """
[deploy]
platform = "fly"
preview_env = "Preview"
app_prefix = "myapp-pr"
region = "iad"
registry = "ghcr"
"""
        config = tomllib.loads(toml)
        result = config_parser.get_deploy_config(config)
        assert result["platform"] == "fly"
        assert result["app_prefix"] == "myapp-pr"
        assert result["region"] == "iad"
        assert result["registry"] == "ghcr"

    def test_defaults_when_missing(self):
        result = config_parser.get_deploy_config({})
        assert result["platform"] == "none"
        assert result["preview_env"] == "Preview"
        assert result["app_prefix"] == ""
        assert result["region"] == "iad"
        assert result["registry"] == "ghcr"

    def test_existing_vercel_config(self, config):
        result = config_parser.get_deploy_config(config)
        assert result["platform"] == "vercel"
        assert result["preview_env"] == "Preview"


class TestIsActiveDeployPlatform:
    def test_fly_is_active(self):
        try:
            import tomllib
        except ModuleNotFoundError:
            import tomli as tomllib
        config = tomllib.loads('[deploy]\nplatform = "fly"')
        assert config_parser.is_active_deploy_platform(config) is True

    def test_vercel_is_not_active(self, config):
        assert config_parser.is_active_deploy_platform(config) is False

    def test_none_is_not_active(self):
        assert config_parser.is_active_deploy_platform({}) is False


class TestDeriveRepairInstructions:
    def test_includes_build_commands(self, config):
        instructions = config_parser.derive_repair_instructions(config)
        assert "npm run lint" in instructions
        assert "npm run build" in instructions

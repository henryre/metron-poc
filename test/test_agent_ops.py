"""Tests for scripts/agent_ops.py — pure functions and mocked I/O."""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import patch

# Add scripts/ to path so we can import agent_ops
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import agent_ops
from models import AgentConfig, ChecksConfig, LBMConfig, LLMConfig

# ---------------------------------------------------------------------------
# Pure function tests: agent lookup
# ---------------------------------------------------------------------------


class TestBranchToAgent:
    def test_exact_prefix(self, agents):
        result = agent_ops.branch_to_agent(agents, "claude/42-fix-bug")
        assert result.label == "agent:claude"

    def test_case_insensitive(self, agents):
        result = agent_ops.branch_to_agent(agents, "Claude/42-fix-bug")
        assert result.label == "agent:claude"

    def test_codex_prefix(self, agents):
        result = agent_ops.branch_to_agent(agents, "codex/10-add-feature")
        assert result.label == "agent:codex"

    def test_openhands_prefix(self, agents):
        result = agent_ops.branch_to_agent(agents, "openhands/5-refactor")
        assert result.label == "agent:openhands"

    def test_no_match(self, agents):
        result = agent_ops.branch_to_agent(agents, "feature/something")
        assert result is None

    def test_empty_branch(self, agents):
        result = agent_ops.branch_to_agent(agents, "")
        assert result is None


class TestLabelToAgent:
    def test_exact_match(self, agents):
        result = agent_ops.label_to_agent(agents, "agent:claude")
        assert result.name == "Agent A"

    def test_codex(self, agents):
        result = agent_ops.label_to_agent(agents, "agent:codex")
        assert result.name == "Agent B"

    def test_no_match(self, agents):
        result = agent_ops.label_to_agent(agents, "agent:gemini")
        assert result is None


class TestNameToAgent:
    def test_full_name(self, agents):
        result = agent_ops.name_to_agent(agents, "Agent A")
        assert result.label == "agent:claude"

    def test_letter_only(self, agents):
        result = agent_ops.name_to_agent(agents, "A")
        assert result.label == "agent:claude"

    def test_lowercase(self, agents):
        result = agent_ops.name_to_agent(agents, "agent b")
        assert result.label == "agent:codex"

    def test_letter_c(self, agents):
        result = agent_ops.name_to_agent(agents, "C")
        assert result.label == "agent:openhands"

    def test_no_match(self, agents):
        result = agent_ops.name_to_agent(agents, "D")
        assert result is None

    def test_whitespace(self, agents):
        result = agent_ops.name_to_agent(agents, "  B  ")
        assert result.label == "agent:codex"


# ---------------------------------------------------------------------------
# Pure function tests: status table
# ---------------------------------------------------------------------------


class TestFindStatusRow:
    def test_finds_agent_a(self, status_table):
        match = agent_ops.find_status_row(status_table, "Agent A")
        assert match is not None
        assert "Agent A" in match.group(0)

    def test_finds_agent_c(self, status_table):
        match = agent_ops.find_status_row(status_table, "Agent C")
        assert match is not None

    def test_no_match(self, status_table):
        match = agent_ops.find_status_row(status_table, "Agent D")
        assert match is None


class TestUpdateStatusRow:
    def test_done_with_pr(self, status_table):
        result = agent_ops.update_status_row(status_table, "Agent A", "done", "42", "", "https://example.com/run")
        assert "✅ Done" in result
        assert "#42" in result
        assert "[Logs](https://example.com/run)" in result
        assert "⏳ Running..." not in result.split("Agent A")[1].split("Agent B")[0]

    def test_failed(self, status_table):
        result = agent_ops.update_status_row(status_table, "Agent B", "failed", "", "", "")
        assert "❌ Failed" in result

    def test_no_changes(self, status_table):
        result = agent_ops.update_status_row(status_table, "Agent C", "no-changes", "", "", "https://example.com/run")
        assert "⚠️ No changes" in result

    def test_preview_only(self, status_table_done):
        result = agent_ops.update_status_row(
            status_table_done, "Agent A", "preview", "", "https://preview.example.com", ""
        )
        # Status should remain unchanged
        assert "✅ Done" in result
        assert "[Preview](https://preview.example.com)" in result

    def test_no_match_returns_unchanged(self, status_table):
        result = agent_ops.update_status_row(status_table, "Agent D", "done", "1", "", "")
        assert result == status_table


class TestCheckAllDone:
    def test_still_running(self, status_table):
        result = agent_ops.check_all_done(status_table)
        assert "*Agents are working on this issue" in result

    def test_all_done(self, status_table_done):
        result = agent_ops.check_all_done(status_table_done)
        assert "All agents have completed" in result
        assert "⏳" not in result


# ---------------------------------------------------------------------------
# Pure function tests: summary prompt
# ---------------------------------------------------------------------------


class TestBuildSummaryPrompt:
    def test_includes_diff(self):
        prompt, truncated = agent_ops.build_summary_prompt("+ added line\n- removed line")
        assert "+ added line" in prompt
        assert "```diff" in prompt
        assert not truncated

    def test_truncation(self):
        long_diff = "x" * 250000
        prompt, truncated = agent_ops.build_summary_prompt(long_diff)
        assert truncated
        assert len(prompt) < 250000

    def test_with_issue_body(self):
        prompt, _ = agent_ops.build_summary_prompt("+ some change", "1. Add dark mode\n2. Add search")
        assert "Coverage" in prompt
        assert "Requested" in prompt
        assert "Add dark mode" in prompt

    def test_without_issue_body(self):
        prompt, _ = agent_ops.build_summary_prompt("+ some change", "")
        assert "What changed" in prompt
        assert "Coverage" not in prompt


# ---------------------------------------------------------------------------
# Mocked I/O tests
# ---------------------------------------------------------------------------


class TestClosePreviousPrs:
    @patch("agent_ops.gh")
    def test_closes_matching_prs(self, mock_gh):
        mock_gh.side_effect = [
            "10\n11",  # pr list returns two PRs
            "",  # close PR 10
            "",  # close PR 11
        ]
        agent_ops.cmd_close_previous_prs(["42", "claude/", "agent:claude"])
        assert mock_gh.call_count == 3
        # Verify close calls
        assert mock_gh.call_args_list[1][0][1] == "close"
        assert mock_gh.call_args_list[2][0][1] == "close"

    @patch("agent_ops.gh")
    def test_no_matching_prs(self, mock_gh):
        mock_gh.return_value = ""
        agent_ops.cmd_close_previous_prs(["42", "claude/", "agent:claude"])
        assert mock_gh.call_count == 1  # only the list call


class TestPostAgentResult:
    @patch("agent_ops.cmd_update_status")
    @patch("agent_ops.gh")
    @patch("agent_ops.load_agents")
    def test_with_pr(self, mock_agents, mock_gh, mock_status):
        mock_agents.return_value = [
            AgentConfig(label="agent:claude", name="Agent A", branch_prefix="claude/", mention="@claude", harness="claude", model_id="claude-opus", model_label="opus-4-6")
        ]
        mock_gh.return_value = ""
        agent_ops.cmd_post_agent_result(["42", "agent:claude", "10", "https://example.com/run"])
        # Should label the PR (with all three labels in one call)
        pr_edit_calls = [c for c in mock_gh.call_args_list if c[0][:3] == ("pr", "edit", "10")]
        assert len(pr_edit_calls) == 1
        assert "agent:claude" in pr_edit_calls[0][0]
        # Should update status
        mock_status.assert_called_once()
        # Should post comment
        assert any("issue" in str(c) and "comment" in str(c) for c in mock_gh.call_args_list)

    @patch("agent_ops.cmd_update_status")
    @patch("agent_ops.gh")
    @patch("agent_ops.load_agents")
    def test_no_pr(self, mock_agents, mock_gh, mock_status):
        mock_agents.return_value = [
            AgentConfig(label="agent:claude", name="Agent A", branch_prefix="claude/", mention="@claude", harness="claude", model_id="claude-opus", model_label="opus-4-6")
        ]
        agent_ops.cmd_post_agent_result(["42", "agent:claude", "", "https://example.com/run"])
        mock_status.assert_called_once()
        # Should NOT call gh pr edit (no PR to label)
        assert not any("pr" in str(c) and "edit" in str(c) for c in mock_gh.call_args_list)

    @patch("agent_ops.cmd_update_status")
    @patch("agent_ops.gh")
    @patch("agent_ops.load_agents")
    def test_applies_three_labels(self, mock_agents, mock_gh, mock_status):
        mock_agents.return_value = [
            AgentConfig(label="agent:claude", name="Agent A", branch_prefix="claude/", mention="@claude", harness="claude", model_id="claude-opus", model_label="opus-4-6")
        ]
        mock_gh.return_value = ""
        agent_ops.cmd_post_agent_result(["42", "agent:claude", "10", "https://example.com/run"])
        # Should apply 3 labels: agent label, harness label, model label
        label_calls = [c for c in mock_gh.call_args_list if c[0][:3] == ("pr", "edit", "10")]
        assert len(label_calls) == 1
        label_args = label_calls[0][0]
        assert "agent:claude" in label_args
        assert "harness:claude" in label_args
        assert "model:opus-4-6" in label_args


class TestClosingLosingPrs:
    @patch("agent_ops.gh")
    @patch("agent_ops.load_agents")
    def test_closes_non_winner(self, mock_agents, mock_gh):
        mock_agents.return_value = [
            AgentConfig(label="agent:claude", branch_prefix="claude/", name="Agent A", mention="@claude", harness="claude", model_id="claude-opus", model_label="opus-4-6"),
            AgentConfig(label="agent:codex", branch_prefix="codex/", name="Agent B", mention="@codex", harness="codex", model_id="gpt-5", model_label="gpt-5"),
        ]
        mock_gh.side_effect = [
            "10",  # claude PR
            "",  # close PR 10
            "11",  # codex PR (is winner)
        ]
        agent_ops.cmd_close_losing_prs(["42", "11", "Agent B"])
        # PR 10 should be closed, PR 11 should be skipped
        close_calls = [c for c in mock_gh.call_args_list if len(c[0]) > 1 and c[0][1] == "close"]
        assert len(close_calls) == 1
        assert close_calls[0][0][2] == "10"

    @patch("agent_ops.gh")
    @patch("agent_ops.load_agents")
    def test_empty_list(self, mock_agents, mock_gh):
        mock_agents.return_value = [AgentConfig(label="agent:claude", branch_prefix="claude/", name="Agent A", mention="@claude", harness="claude", model_id="claude-opus", model_label="opus-4-6")]
        mock_gh.return_value = ""
        agent_ops.cmd_close_losing_prs(["42", "10", "Agent A"])
        # Only list call, no close calls
        assert mock_gh.call_count == 1


class TestDispatchRepair:
    @patch("agent_ops.load_config")
    @patch("agent_ops.gh")
    def test_max_repairs_reached(self, mock_gh, mock_config):
        mock_config.return_value = LBMConfig(
            agents=[AgentConfig(label="agent:claude", branch_prefix="claude/", name="Agent A", mention="@claude", harness="claude", model_id="claude-opus", model_label="opus-4-6")],
            checks=ChecksConfig(max_repair_attempts=2),
            llm=LLMConfig(),
        )
        mock_gh.side_effect = [
            "claude/42-fix",  # branch
            "2",  # repair count = 2 (at max)
            '{"body": "Implements #42"}',  # pr body (for issue extraction — but we use --jq)
            "",  # issue comment
        ]
        # repair_count_str "2" >= max 2, so should post "max attempts" comment
        agent_ops.cmd_dispatch_repair(["10", "CI failed"])

    @patch("agent_ops.load_config")
    @patch("agent_ops.gh")
    def test_not_agent_branch(self, mock_gh, mock_config):
        mock_config.return_value = LBMConfig(
            agents=[AgentConfig(label="agent:claude", branch_prefix="claude/", name="Agent A", mention="@claude", harness="claude", model_id="claude-opus", model_label="opus-4-6")],
            checks=ChecksConfig(max_repair_attempts=2),
            llm=LLMConfig(),
        )
        mock_gh.return_value = "feature/something"  # not an agent branch
        agent_ops.cmd_dispatch_repair(["10", "CI failed"])
        # Should exit early after branch lookup
        assert mock_gh.call_count == 1


class TestUpdateStatus:
    @patch("agent_ops.gh")
    @patch("agent_ops.load_agents")
    def test_updates_row(self, mock_agents, mock_gh):
        mock_agents.return_value = [AgentConfig(label="agent:claude", name="Agent A", branch_prefix="claude/", mention="@claude", harness="claude", model_id="claude-opus", model_label="opus-4-6")]
        table_body = (
            "## Agent Implementations\n\n"
            "| Agent | Status | PR | Preview | Run |\n"
            "|-------|--------|-----|---------|-----|\n"
            "| Agent A | ⏳ Running... |  |  |  |\n\n"
            "---\n*Agents are working on this issue. "
            "This comment will be updated as each completes.*"
        )
        comment_json = json.dumps({"id": 123, "body": table_body})
        mock_gh.side_effect = [
            comment_json,  # api get comments
            "",  # api patch
        ]
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            agent_ops.cmd_update_status(["42", "agent:claude", "done", "10", "", "https://example.com/run"])
        assert mock_gh.call_count == 2

    @patch("agent_ops.gh")
    @patch("agent_ops.load_agents")
    def test_no_status_comment(self, mock_agents, mock_gh):
        mock_agents.return_value = [AgentConfig(label="agent:claude", name="Agent A", branch_prefix="claude/", mention="@claude", harness="claude", model_id="claude-opus", model_label="opus-4-6")]
        mock_gh.return_value = ""
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            agent_ops.cmd_update_status(["42", "agent:claude", "done", "10", "", ""])
        # Should only make the one API call to find comments
        assert mock_gh.call_count == 1


# ---------------------------------------------------------------------------
# New helper tests
# ---------------------------------------------------------------------------


class TestCountPrComments:
    @patch("agent_ops.gh")
    def test_counts_repair_markers(self, mock_gh):
        mock_gh.return_value = "3"
        result = agent_ops.count_pr_comments("10", "repair-attempt")
        assert result == 3
        mock_gh.assert_called_once_with(
            "pr", "view", "10",
            "--json", "comments",
            "--jq", '[.comments[].body | select(contains("[repair-attempt"))] | length',
            check=False,
        )

    @patch("agent_ops.gh")
    def test_returns_zero_on_empty(self, mock_gh):
        mock_gh.return_value = ""
        result = agent_ops.count_pr_comments("10", "repair-attempt")
        assert result == 0

    @patch("agent_ops.gh")
    def test_returns_zero_on_non_digit(self, mock_gh):
        mock_gh.return_value = "null"
        result = agent_ops.count_pr_comments("10", "repair-attempt")
        assert result == 0


class TestCountIssueComments:
    @patch("agent_ops.gh")
    def test_counts_ralph_markers_scoped_to_agent(self, mock_gh):
        comments = [
            {"body": "[ralph] Agent A did something"},
            {"body": "[ralph] Agent B did something"},
            {"body": "[ralph] Agent A again"},
            {"body": "no marker"},
        ]
        mock_gh.return_value = json.dumps(comments)
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            result = agent_ops.count_issue_comments("42", "ralph", scope="Agent A")
        assert result == 2

    @patch("agent_ops.gh")
    def test_counts_without_scope(self, mock_gh):
        comments = [
            {"body": "[ralph] Agent A did something"},
            {"body": "[ralph] Agent B did something"},
            {"body": "no marker"},
        ]
        mock_gh.return_value = json.dumps(comments)
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            result = agent_ops.count_issue_comments("42", "ralph")
        assert result == 2

    @patch("agent_ops.gh")
    def test_returns_zero_on_empty(self, mock_gh):
        mock_gh.return_value = ""
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            result = agent_ops.count_issue_comments("42", "ralph")
        assert result == 0

    @patch("agent_ops.gh")
    def test_returns_zero_without_repo_env(self, mock_gh):
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_REPOSITORY"}
        with patch.dict(os.environ, env, clear=True):
            result = agent_ops.count_issue_comments("42", "ralph")
        assert result == 0
        mock_gh.assert_not_called()

    @patch("agent_ops.gh")
    def test_returns_zero_on_null_response(self, mock_gh):
        mock_gh.return_value = "null"
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            result = agent_ops.count_issue_comments("42", "ralph")
        assert result == 0


class TestExtractIssueFromPr:
    @patch("agent_ops.gh")
    def test_extracts_issue_number(self, mock_gh):
        mock_gh.return_value = "Implements #42\nSome more body text."
        result = agent_ops.extract_issue_from_pr("10")
        assert result == "42"
        mock_gh.assert_called_once_with(
            "pr", "view", "10",
            "--json", "body",
            "--jq", ".body",
            check=False,
        )

    @patch("agent_ops.gh")
    def test_returns_none_when_missing(self, mock_gh):
        mock_gh.return_value = "This PR fixes a bug."
        result = agent_ops.extract_issue_from_pr("10")
        assert result is None

    @patch("agent_ops.gh")
    def test_returns_none_on_empty_body(self, mock_gh):
        mock_gh.return_value = ""
        result = agent_ops.extract_issue_from_pr("10")
        assert result is None


class TestCloseAndCleanupPr:
    @patch("agent_ops.gh")
    def test_closes_pr_and_deletes_branch(self, mock_gh):
        mock_gh.side_effect = [
            "",                 # pr close
            "feat/my-branch",  # pr view headRefName
            "",                # api DELETE
        ]
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            agent_ops.close_and_cleanup_pr("10", "Closing due to failure.")
        assert mock_gh.call_count == 3
        # Verify close call
        close_call = mock_gh.call_args_list[0]
        assert close_call[0][:2] == ("pr", "close")
        assert close_call[0][2] == "10"
        assert "Closing due to failure." in close_call[0]
        # Verify delete branch call
        delete_call = mock_gh.call_args_list[2]
        assert "DELETE" in delete_call[0]
        assert "refs/heads/feat/my-branch" in delete_call[0][-1]

    @patch("agent_ops.gh")
    def test_skips_delete_if_no_branch(self, mock_gh):
        mock_gh.side_effect = [
            "",   # pr close
            "",   # pr view returns empty branch
        ]
        with patch.dict(os.environ, {"GITHUB_REPOSITORY": "owner/repo"}):
            agent_ops.close_and_cleanup_pr("10", "Closing.")
        # No DELETE call made
        assert mock_gh.call_count == 2
        delete_calls = [c for c in mock_gh.call_args_list if "DELETE" in str(c)]
        assert len(delete_calls) == 0

    @patch("agent_ops.gh")
    def test_skips_delete_if_no_repo_env(self, mock_gh):
        mock_gh.side_effect = [
            "",              # pr close
            "some-branch",  # pr view headRefName
        ]
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_REPOSITORY"}
        with patch.dict(os.environ, env, clear=True):
            agent_ops.close_and_cleanup_pr("10", "Closing.")
        # No DELETE call when GITHUB_REPOSITORY is missing
        assert mock_gh.call_count == 2
        delete_calls = [c for c in mock_gh.call_args_list if "DELETE" in str(c)]
        assert len(delete_calls) == 0


class TestDispatchAgent:
    @patch("agent_ops.gh")
    def test_dispatches_workflow_with_correct_args(self, mock_gh):
        mock_gh.return_value = ""
        agent_ops.dispatch_agent("42", "claude-code")
        mock_gh.assert_called_once_with(
            "workflow", "run", "lbm-agents.yml",
            "-f", "issue_number=42",
            "-f", "agent=claude-code",
            check=False,
        )


# ---------------------------------------------------------------------------
# call_llm helper tests
# ---------------------------------------------------------------------------


class TestCallLLM:
    def test_returns_none_without_api_key(self):
        from models import LLMConfig
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
            result = agent_ops.call_llm("Hello", LLMConfig())
        assert result is None

    @patch("http.client.HTTPSConnection")
    def test_returns_text_on_success(self, mock_conn_cls):
        from models import LLMConfig
        mock_resp = mock_conn_cls.return_value.getresponse.return_value
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps(
            {"content": [{"text": "Summary here"}]}
        ).encode()
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=False):
            result = agent_ops.call_llm("Summarize this", LLMConfig())
        assert result == "Summary here"

    @patch("http.client.HTTPSConnection")
    def test_returns_none_on_http_error(self, mock_conn_cls):
        from models import LLMConfig
        mock_resp = mock_conn_cls.return_value.getresponse.return_value
        mock_resp.status = 401
        mock_resp.read.return_value = b'{"error": "unauthorized"}'
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=False):
            result = agent_ops.call_llm("Summarize this", LLMConfig())
        assert result is None

#!/usr/bin/env python3
"""Consolidated dev-infra operations for the LBM agent orchestration.

Replaces: close-previous-prs.sh, post-agent-result.sh, close-losing-prs.sh,
dispatch-repair.sh, agent-lookup.py, update-status.py, summarize-pr.py.

Usage:
  python3 scripts/agent_ops.py <command> [args...]

Commands:
  lookup <subcommand> <value> [field]
  close-previous-prs <issue> <prefix> <label>
  post-agent-result <issue> <label> [pr] [run_url]
  close-losing-prs <issue> <winner_pr> [winner_name]
  dispatch-repair <pr> <context>
  update-status <issue> <label> <status> [pr] [preview] [run]
  summarize-pr <pr_number>
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

from models import AgentConfig, LBMConfig

CONFIG_PATH = os.environ.get(
    "LBM_CONFIG_PATH",
    os.path.join(os.getcwd(), "lbm.toml"),
)


# ---------------------------------------------------------------------------
# gh CLI wrapper
# ---------------------------------------------------------------------------


def gh(*args: str, check: bool = True) -> str:
    """Run a gh CLI command and return stdout."""
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=check)
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_lbm_config(path: str | None = None) -> LBMConfig:
    """Read lbm.toml and return a typed LBMConfig."""
    config_path = path or CONFIG_PATH
    with open(config_path, "rb") as f:
        parsed = tomllib.load(f)
    return LBMConfig.from_parsed_toml(parsed)


def load_config(path: str | None = None) -> LBMConfig:
    """Load the config as a typed LBMConfig."""
    return load_lbm_config(path)


def load_agents(path: str | None = None) -> list[AgentConfig]:
    """Load the agents list from config."""
    return load_config(path).agents


# ---------------------------------------------------------------------------
# Agent lookup (pure functions)
# ---------------------------------------------------------------------------


def branch_to_agent(agents: list[AgentConfig], branch: str) -> AgentConfig | None:
    """Find agent config by branch prefix."""
    for a in agents:
        if branch.startswith(a.branch_prefix) or branch.lower().startswith(a.branch_prefix.lower()):
            return a
    return None


def label_to_agent(agents: list[AgentConfig], label: str) -> AgentConfig | None:
    """Find agent config by label."""
    for a in agents:
        if a.label == label:
            return a
    return None


def name_to_agent(agents: list[AgentConfig], name: str) -> AgentConfig | None:
    """Find agent config by name (e.g. 'A', 'Agent A', 'agent a')."""
    name = name.strip().upper()
    if not name.startswith("AGENT"):
        name = f"AGENT {name}"
    for a in agents:
        if a.name.upper() == name:
            return a
    return None


# ---------------------------------------------------------------------------
# Status table helpers (pure functions)
# ---------------------------------------------------------------------------


def find_status_row(body: str, agent_name: str) -> re.Match | None:
    """Find a row in the status table for the given agent name."""
    pattern = re.compile(
        rf"^\| {re.escape(agent_name)} \|[^|]*\|[^|]*\|[^|]*\|[^|]*\|([^|]*\|)?$",
        re.MULTILINE,
    )
    return pattern.search(body)


def update_status_row(body: str, agent_name: str, status: str, pr: str, preview: str, run: str) -> str:
    """Update a single row in the status table. Returns the updated body."""
    match = find_status_row(body, agent_name)
    if not match:
        return body

    old_row = match.group(0)
    cells = [c.strip() for c in old_row.split("|")[1:-1]]
    while len(cells) < 5:
        cells.append("")

    # Format cell values
    if status == "done" and pr:
        status_text = "✅ Done"
        pr_text = f"#{pr}"
    elif status == "failed":
        status_text = "❌ Failed"
        pr_text = ""
    elif status == "no-changes":
        status_text = "⚠️ No changes"
        pr_text = ""
    elif status == "preview":
        status_text = None
        pr_text = None
    else:
        status_text = "✅ Done"
        pr_text = ""

    if status_text is not None:
        cells[1] = status_text
    if pr_text is not None:
        cells[2] = pr_text
    if preview:
        cells[3] = f"[Preview]({preview})"
    if run:
        cells[4] = f"[Logs]({run})"

    new_row = "| " + " | ".join(cells) + " |"
    return body[: match.start()] + new_row + body[match.end() :]


def check_all_done(body: str) -> str:
    """If no pending indicator remains in the body, replace the 'agents working' message."""
    if "Pending" not in body and "Running" not in body:
        return body.replace(
            "*Agents are working on this issue. This comment will be updated as each completes.*",
            "*All agents have completed. Review the PRs and use `/merge agent X` to select the best one.*",
        )
    return body


# ---------------------------------------------------------------------------
# Summary prompt builder (pure function)
# ---------------------------------------------------------------------------

MAX_DIFF_LENGTH = 200000
MAX_FILE_DIFF_LINES = 500


def build_summary_prompt(diff: str, issue_body: str = "") -> tuple[str, bool]:
    """Build the LLM prompt for PR summary generation.

    Returns (prompt, was_truncated) tuple.
    """
    was_truncated = len(diff) > MAX_DIFF_LENGTH
    truncated = diff[:MAX_DIFF_LENGTH]

    if issue_body:
        return (
            f"""You are reviewing a pull request that implements features from a GitHub issue.

## Requested changes (from the issue)

{issue_body}

## PR diff

```diff
{truncated}
```

{"**Note: The diff was truncated. Some changes may not be visible.**" if was_truncated else ""}

Write a summary with these three sections:

### Coverage

Create a markdown table mapping each requested feature to what was done.
Use this exact format (one row per requested item):

| | Requested | Status |
|---|-----------|--------|
| <emoji> | <feature name from issue> | <what was implemented, or "Not implemented"> |

For the emoji column use exactly one of:
- if fully implemented (all requirements from the issue met)
- if partially implemented (state what's done and what's missing)
- if not implemented at all

### Other changes
- List changes that don't map to a requested feature (refactors, config, utilities). Omit section if none.

Focus ONLY on completeness — whether each requested feature was implemented or not.
Do NOT assess code quality, implementation approach, or whether it was done "the right way".
Do NOT flag concerns, suggest improvements, or critique decisions.
Be specific and terse. One sentence per bullet. No filler.""",
            was_truncated,
        )
    else:
        return (
            f"""You are reviewing a pull request diff. Write a concise summary.

### What changed
- Key behavioral/user-facing changes

### Implementation notes
- Notable implementation decisions

Be specific and terse. One sentence per bullet. No filler.

```diff
{truncated}
```

{"**Note: The diff was truncated. Some changes may not be visible.**" if was_truncated else ""}""",
            was_truncated,
        )


# ---------------------------------------------------------------------------
# Commands (orchestrators with I/O)
# ---------------------------------------------------------------------------


def cmd_lookup(args: list[str]) -> None:
    """Lookup agent config. Usage: lookup <subcommand> <value> [field]"""
    if len(args) < 2:
        print("Usage: lookup <branch-to-name|label-to-name|name-to-label> <value> [field]", file=sys.stderr)
        sys.exit(1)

    subcmd, value = args[0], args[1]
    field = args[2] if len(args) > 2 else None
    agents = load_agents()

    if subcmd == "branch-to-name":
        agent = branch_to_agent(agents, value)
    elif subcmd == "label-to-name":
        agent = label_to_agent(agents, value)
    elif subcmd == "name-to-label":
        agent = name_to_agent(agents, value)
    else:
        print(f"Unknown lookup subcommand: {subcmd}", file=sys.stderr)
        sys.exit(1)

    if agent:
        if field:
            print(getattr(agent, field, ""))
        else:
            from dataclasses import fields as dc_fields
            for f in dc_fields(agent):
                print(f"{f.name}={getattr(agent, f.name)}")
    else:
        sys.exit(1)


def cmd_close_previous_prs(args: list[str]) -> None:
    """Close previous agent PRs for an issue."""
    if len(args) < 3:
        print("Usage: close-previous-prs <issue_number> <branch_prefix> <agent_label>", file=sys.stderr)
        sys.exit(1)

    issue_num, branch_prefix, agent_label = args[0], args[1], args[2]

    jq_filter = (
        f".[] | select("
        f'(.body | test("Implements #{issue_num}\\\\b")) and '
        f'((.headRefName | startswith("{branch_prefix}")) or '
        f'(.labels | map(.name) | index("{agent_label}"))))'
        f" | .number"
    )

    output = gh(
        "pr",
        "list",
        "--json",
        "number,body,headRefName,labels",
        "--jq",
        jq_filter,
        check=False,
    )

    for line in output.splitlines():
        pr = line.strip()
        if pr:
            print(f"Closing old PR #{pr}")
            gh("pr", "close", pr, "--comment", "Superseded by new agent run.", "--delete-branch", check=False)


def cmd_post_agent_result(args: list[str]) -> None:
    """Post agent result: label PR, update status table, comment on issue."""
    if len(args) < 2:
        print("Usage: post-agent-result <issue_number> <agent_label> [pr_number] [run_url]", file=sys.stderr)
        sys.exit(1)

    issue_num = args[0]
    agent_label = args[1]
    pr_num = args[2] if len(args) > 2 else ""
    run_url = args[3] if len(args) > 3 else ""

    agents = load_agents()
    agent = label_to_agent(agents, agent_label)
    agent_name = agent.name if agent else "Agent"

    if not pr_num:
        cmd_update_status([issue_num, agent_label, "no-changes", "", "", run_url])
        return

    # Apply three labels: agent (stable ID), harness, model
    harness_label = f"harness:{agent.harness}" if agent and agent.harness else ""
    model_label_tag = f"model:{agent.model_label}" if agent and agent.model_label else ""
    all_labels = list(filter(None, [agent_label, harness_label, model_label_tag]))
    # Ensure labels exist on the repo (gh pr edit silently fails for missing labels)
    for lbl in all_labels:
        gh("label", "create", lbl, "--force", check=False)
    label_args_list: list[str] = []
    for lbl in all_labels:
        label_args_list += ["--add-label", lbl]
    gh("pr", "edit", pr_num, *label_args_list, check=False)
    cmd_update_status([issue_num, agent_label, "done", pr_num, "", run_url])

    body = f"""## {agent_name} Implementation
- **PR**: #{pr_num}
- **Preview**: Deploying..."""

    if run_url:
        body += f"\n- **Run**: [View logs]({run_url})"

    body += "\n\n---\n*Review and compare agent implementations, then merge the best one.*"

    gh("issue", "comment", issue_num, "--body", body)


def cmd_close_losing_prs(args: list[str]) -> None:
    """Close all agent PRs for an issue except the winner."""
    if len(args) < 2:
        print("Usage: close-losing-prs <issue_number> <winner_pr> [winner_name]", file=sys.stderr)
        sys.exit(1)

    issue_num = args[0]
    winner_pr = args[1]
    winner_name = args[2] if len(args) > 2 else "Agent"

    agents = load_agents()
    for agent in agents:
        prefix = agent.branch_prefix
        jq_filter = (
            f".[] | select("
            f'(.body | test("Implements #{issue_num}\\\\b")) and '
            f'(.headRefName | startswith("{prefix}")))'
            f" | .number"
        )
        output = gh(
            "pr",
            "list",
            "--json",
            "number,body,headRefName",
            "--jq",
            jq_filter,
            check=False,
        )
        for line in output.splitlines():
            pr = line.strip()
            if pr and pr != winner_pr:
                print(f"Closing PR #{pr}")
                gh(
                    "pr",
                    "close",
                    pr,
                    "--comment",
                    f"Closed: {winner_name} (PR #{winner_pr}) was selected.",
                    "--delete-branch",
                    check=False,
                )


def cmd_dispatch_repair(args: list[str]) -> None:
    """Dispatch a repair request to an agent for a failing PR."""
    if len(args) < 2:
        print("Usage: dispatch-repair <pr_number> <failure_context>", file=sys.stderr)
        sys.exit(1)

    pr_num = args[0]
    failure_context = args[1]

    config = load_config()
    max_repairs = config.checks.max_repair_attempts
    agents = config.agents

    branch = gh("pr", "view", pr_num, "--json", "headRefName", "--jq", ".headRefName", check=False)
    if not branch:
        print(f"PR #{pr_num} not found")
        return

    agent = branch_to_agent(agents, branch)
    if not agent:
        print(f"Not an agent branch: {branch}")
        return

    agent_name = agent.name
    mention = agent.mention

    repair_count_str = gh(
        "pr",
        "view",
        pr_num,
        "--json",
        "comments",
        "--jq",
        '[.comments[].body | select(contains("[repair-attempt]"))] | length',
        check=False,
    )
    repair_count = int(repair_count_str) if repair_count_str.isdigit() else 0

    print(f"{agent_name} PR #{pr_num}: {repair_count} / {max_repairs} repairs")

    if repair_count >= max_repairs:
        print("Max repair attempts reached")
        pr_body = gh("pr", "view", pr_num, "--json", "body", "--jq", ".body", check=False)
        m = re.search(r"Implements #(\d+)", pr_body)
        if m:
            issue_num = m.group(1)
            gh(
                "issue",
                "comment",
                issue_num,
                "--body",
                f"{agent_name} PR #{pr_num} has failed after {max_repairs} repair attempts."
                " Manual intervention needed.",
            )
        return

    pat_token = os.environ.get("PAT_TOKEN", "")
    if not mention or not pat_token:
        print("Cannot dispatch repair (no mention or no PAT_TOKEN)")
        return

    repair_body = (
        f"{mention} [repair-attempt] {failure_context}\n\n"
        f"Fix ALL errors listed above -- there may be multiple issues across lint, typecheck, and build.\n"
        f"Before committing, run the full CI check locally.\n"
        f"Only commit and push when ALL steps pass."
    )

    env = {**os.environ, "GH_TOKEN": pat_token}
    subprocess.run(
        ["gh", "pr", "comment", pr_num, "--body", repair_body],
        env=env,
        check=False,
    )

    print(f"Dispatched repair attempt {repair_count + 1} for {agent_name} PR #{pr_num}")


def cmd_update_status(args: list[str]) -> None:
    """Update an agent's row in the status comment on an issue."""
    if len(args) < 3:
        print("Usage: update-status <issue_number> <agent_label> <status> [pr] [preview] [run]", file=sys.stderr)
        sys.exit(1)

    issue_num = args[0]
    agent_label = args[1]
    status = args[2]
    pr_number = args[3] if len(args) > 3 else ""
    preview_url = args[4] if len(args) > 4 else ""
    run_url = args[5] if len(args) > 5 else ""

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if not repo:
        print("GITHUB_REPOSITORY not set", file=sys.stderr)
        sys.exit(1)

    agents = load_agents()
    agent = label_to_agent(agents, agent_label)
    if not agent:
        print(f"Unknown agent label: {agent_label}", file=sys.stderr)
        sys.exit(1)

    agent_name = agent.name

    comments_json = gh(
        "api",
        f"repos/{repo}/issues/{issue_num}/comments",
        "--jq",
        '[.[] | select(.body | startswith("## Agent Implementations")) | {id, body}] | last',
        check=False,
    )

    if not comments_json or comments_json == "null":
        print("No status comment found")
        return

    comment = json.loads(comments_json)
    comment_id = comment["id"]
    body = comment["body"]

    new_body = update_status_row(body, agent_name, status, pr_number, preview_url, run_url)
    new_body = check_all_done(new_body)

    gh(
        "api",
        "-X",
        "PATCH",
        f"repos/{repo}/issues/comments/{comment_id}",
        "-f",
        f"body={new_body}",
    )
    print(f"Updated {agent_name}: status={status}, pr={pr_number}, preview={preview_url}, run={run_url}")


def cmd_summarize_pr(args: list[str]) -> None:
    """Generate a concise summary of a PR's changes using an LLM."""
    if len(args) < 1:
        print("Usage: summarize-pr <pr_number> [issue_number]", file=sys.stderr)
        sys.exit(1)

    pr_number = args[0]
    issue_number = args[1] if len(args) > 1 else ""

    raw_diff = gh("pr", "diff", pr_number, check=False)

    if not raw_diff.strip():
        print("")
        return

    # Compact the diff: keep file headers, hunk markers, and changed lines only.
    # Strip unchanged context lines to reduce size by ~50%.
    # Also exclude files with more than MAX_FILE_DIFF_LINES changed lines.
    filtered_chunks: list[str] = []
    excluded_files: list[str] = []
    current_file = ""
    current_chunk: list[str] = []
    changed_lines = 0

    for line in raw_diff.splitlines(keepends=True):
        if line.startswith("diff --git"):
            if current_file:
                if changed_lines <= MAX_FILE_DIFF_LINES:
                    filtered_chunks.append("".join(current_chunk))
                else:
                    excluded_files.append(f"{current_file} ({changed_lines} lines changed)")
            current_file = line.split(" b/")[-1].strip() if " b/" in line else ""
            current_chunk = [line]
            changed_lines = 0
        elif line.startswith("@@") or line.startswith("---") or line.startswith("+++"):
            current_chunk.append(line)
        elif line.startswith("+") or line.startswith("-"):
            current_chunk.append(line)
            changed_lines += 1
        # Skip unchanged context lines

    if current_file:
        if changed_lines <= MAX_FILE_DIFF_LINES:
            filtered_chunks.append("".join(current_chunk))
        else:
            excluded_files.append(f"{current_file} ({changed_lines} lines changed)")

    diff = "".join(filtered_chunks)

    # Prepend commit messages as a compact overview
    commits = gh(
        "pr",
        "view",
        pr_number,
        "--json",
        "commits",
        "--jq",
        '.commits[] | "- " + .messageHeadline',
        check=False,
    )
    if commits:
        diff = f"## Commits\n{commits}\n\n{diff}"

    # Fetch issue body if issue number provided
    issue_body = ""
    if issue_number:
        issue_body = gh("issue", "view", issue_number, "--json", "body", "--jq", ".body", check=False)

    # Read LLM config from lbm.toml
    config_path = os.environ.get("LBM_CONFIG_PATH", "lbm.toml")
    try:
        from config_parser import load_config
        cfg = load_config(config_path)
        llm = cfg.get("llm", {})
        provider = llm.get("provider", "anthropic")
        model = llm.get("summary_model", "claude-sonnet-4-6")
    except Exception:
        provider = "anthropic"
        model = "claude-sonnet-4-6"

    if provider == "portkey":
        api_key = os.environ.get("PORTKEY_API_KEY", "")
        host = "api.portkey.ai"
        headers = {
            "Content-Type": "application/json",
            "x-portkey-api-key": api_key,
        }
    else:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        host = "api.anthropic.com"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }

    if not api_key:
        print("")
        return

    prompt, was_truncated = build_summary_prompt(diff, issue_body)

    body = json.dumps(
        {
            "model": model,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }
    )

    try:
        import http.client

        conn = http.client.HTTPSConnection(host, timeout=60)
        conn.request(
            "POST",
            "/v1/messages",
            body=body.encode(),
            headers=headers,
        )
        resp = conn.getresponse()
        resp_body = resp.read().decode()
        if resp.status != 200:
            print(f"LLM summary failed: HTTP {resp.status} -- {resp_body}", file=sys.stderr)
            print("")
            return
        data = json.loads(resp_body)
        summary = data["content"][0]["text"]
        if was_truncated:
            summary += "\n\n> **Note:** The PR diff was truncated for review. Some changes may not be reflected above."
        if excluded_files:
            summary += "\n\n> **Large files excluded from review:** " + ", ".join(excluded_files)
        print(summary)
    except Exception as e:
        print(f"LLM summary failed: {e}", file=sys.stderr)
        print("")


def cmd_diagnostics(args: list[str]) -> None:
    """Print post-agent diagnostic info: git state, resolver output, branches."""
    agent_label = args[0] if args else ""

    print("--- Git status ---")
    print(subprocess.run(["git", "status"], capture_output=True, text=True).stdout)

    print("--- Recent commits ---")
    print(subprocess.run(["git", "log", "--oneline", "-5"], capture_output=True, text=True).stdout)

    print("--- Diff stats ---")
    diff = subprocess.run(["git", "diff", "--stat", "HEAD"], capture_output=True, text=True)
    print(diff.stdout or "(no uncommitted changes)")

    # Agent-specific: show branches matching this agent's prefix
    if agent_label:
        agents = load_agents()
        agent = label_to_agent(agents, agent_label)
        if agent:
            prefix = agent.branch_prefix.rstrip("/")
            result = subprocess.run(["git", "branch", "-a"], capture_output=True, text=True)
            matching = [line.strip() for line in result.stdout.splitlines() if prefix in line]
            if matching:
                print(f"--- Branches matching '{prefix}' ---")
                for b in matching:
                    print(f"  {b}")

    # OpenHands-specific: resolver output summary
    oh_output = "/tmp/oh-output/output.jsonl"
    oh_log = "/tmp/oh-resolve.log"

    if os.path.exists(oh_output):
        print("--- Resolver output ---")
        try:
            with open(oh_output) as f:
                for line in f:
                    data = json.loads(line)
                    patch = data.get("git_patch", "")
                    if patch:
                        print(f"git_patch: {len(patch)} chars, {patch.count(chr(10))} lines")
        except Exception as e:
            print(f"Could not parse output.jsonl: {e}")

    if os.path.exists(oh_log):
        print("--- Resolve log (last 20 lines) ---")
        with open(oh_log) as f:
            lines = f.readlines()
            for line in lines[-20:]:
                print(line, end="")


def cmd_generate_config(args: list[str]) -> None:
    """Generate flat config output from lbm.toml (for debugging/validation)."""
    from dataclasses import asdict

    check_only = "--check" in args
    config_path = args[0] if args and not args[0].startswith("--") else CONFIG_PATH

    config = load_lbm_config(config_path)
    generated_json = json.dumps(asdict(config), indent=2) + "\n"

    if check_only:
        print("Config is valid.")
        print(generated_json)
    else:
        print(generated_json)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

COMMANDS = {
    "lookup": cmd_lookup,
    "close-previous-prs": cmd_close_previous_prs,
    "post-agent-result": cmd_post_agent_result,
    "close-losing-prs": cmd_close_losing_prs,
    "dispatch-repair": cmd_dispatch_repair,
    "update-status": cmd_update_status,
    "summarize-pr": cmd_summarize_pr,
    "diagnostics": cmd_diagnostics,
    "generate-config": cmd_generate_config,
}


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: {sys.argv[0]} <command> [args...]", file=sys.stderr)
        print(f"Commands: {', '.join(COMMANDS)}", file=sys.stderr)
        sys.exit(1)

    command = sys.argv[1]
    COMMANDS[command](sys.argv[2:])


if __name__ == "__main__":
    main()

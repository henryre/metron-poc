# Ralph Loop: Outer Restart Loop for LBM Agents

When an agent exhausts its repair attempts and the PR still fails CI/deploy,
the ralph loop wipes the PR and restarts the agent from scratch. This sits
outside the existing repair loop — repairs are incremental fixes to an existing
PR; ralph restarts are full do-overs.

## Configuration

New field in `lbm.toml` under `[checks]`:

```toml
[checks]
required = ["CI"]
repair_from = ["CI"]
max_repair_attempts = 10
max_ralph_loops = 3        # max full wipe-and-restart cycles (0 = disabled)
```

Default is `0` (disabled) so existing users are unaffected.

### Typed config via dataclasses

Replace the raw dict returned by `load_lbm_config` with stdlib dataclasses.
No external dependencies (pydantic would require `pip install` in every
workflow, since scripts run as bare `python3` on GH Actions runners).

```python
@dataclass
class AgentConfig:
    label: str
    harness: str
    model_id: str
    model_label: str
    branch_prefix: str
    name: str          # "Agent A", "Agent B", ...
    mention: str

@dataclass
class ChecksConfig:
    required: list[str]
    repair_from: list[str]
    max_repair_attempts: int = 10
    max_ralph_loops: int = 0

@dataclass
class LLMConfig:
    provider: str = "anthropic"
    summary_model: str = "claude-sonnet-4-6"

@dataclass
class LBMConfig:
    agents: list[AgentConfig]
    checks: ChecksConfig
    llm: LLMConfig
```

`load_lbm_config()` returns an `LBMConfig` instance instead of a dict.
Existing code that does `config["max_repair_attempts"]` becomes
`config.checks.max_repair_attempts` — clearer, discoverable, and
type-checked by editors. Each dataclass has a `from_dict` classmethod
that handles defaults.

The existing `load_config()` / `load_agents()` convenience functions
remain but return the new types. Existing callers in workflows that
access dict keys will need updating — this is part of the migration.

## Counter Tracking

Ralph restarts are tracked via issue comments (same mechanism as repair
counting, but on the issue instead of the PR — since the PR gets deleted).

Marker format:

```
[ralph-restart N] Agent B — restarting after 10 failed repairs on PR #50.

Previous approach: Added a new Footer component with inline styles...
```

Counting filters issue comments matching `[ralph-restart` scoped to the agent
letter (e.g. "Agent B"). Each agent's ralph count is independent.

Repair count is per-PR (tracked via `[repair-attempt]` comments on the PR), so
a fresh PR from a ralph restart naturally resets the repair counter to 0.

## Flow

Today, when `repair_count >= max_repair_attempts`, `cmd_dispatch_repair()` posts
"manual intervention needed" and returns. The ralph loop replaces that exit path:

1. **Count ralph restarts** on the issue for this agent letter.
2. **If `ralph_count >= max_ralph_loops` or ralph is disabled (0):** post the
   existing "manual intervention needed" message. This is the terminal state.
3. **If under cap, execute restart:**
   a. Generate a 2-3 sentence LLM summary of what approach the PR took and why
      it kept failing. Uses the existing `[llm]` provider/model config and the
      PR diff + last CI errors as input.
   b. Close the PR with comment: `Closing for ralph restart (attempt N+1/max).`
   c. Delete the remote branch via GitHub API.
   d. Post `[ralph-restart N]` comment on the issue (includes the approach
      summary).
   e. Re-dispatch the agent via `gh workflow run lbm-agents.yml` with the same
      `issue_number` and `agent` inputs.

The dispatched agent starts completely fresh: new branch from main HEAD, new PR.
The approach summary is visible on the issue as a regular comment — the agent
sees it when reading issue context during startup, giving it enough information
to try a different approach without anchoring on the failed code.

## Pass/Fail Signal

The ralph loop uses the same pass/fail signals as repairs: CI check failure
and/or deploy failure, as configured in `[checks].repair_from`. No separate
criteria.

## Code Changes

All changes in `lbm-poc`. No target repo changes needed.

### Design constraint: clean top-level procedures

`agent_ops.py` is ~820 lines and growing. The `cmd_*` functions currently mix
orchestration logic with low-level `gh` calls and string parsing. As the ralph
loop adds another layer of decision-making, the top-level procedures must read
clearly and delegate to self-describing helpers.

**Principle:** Top-level `cmd_*` functions should read like a narrative — load
config, identify the agent, check counters, decide action, execute. All
mechanics (counting comments, closing PRs, calling LLMs, dispatching workflows)
live in reusable helpers with descriptive names.

**New abstractions** (somewhat general-purpose, usable beyond just ralph):

- `count_issue_comments(issue_num, marker, scope=None)` — count comments on an
  issue matching a `[marker]` tag, optionally scoped to a string (e.g. agent
  letter). Replaces the inline `gh pr view ... | select(contains(...))` pattern
  used for repair counting too.
- `close_and_cleanup_pr(pr_num, comment)` — close a PR, delete its remote
  branch. Reusable for ralph restarts, losing-PR cleanup, etc.
- `dispatch_agent(issue_num, agent_harness)` — re-dispatch an agent workflow
  via `gh workflow run`. Encapsulates the workflow filename and input mapping.
- `summarize_failed_attempt(pr_num, failure_context)` — generate an LLM
  summary of the PR's approach and failure. Builds on the existing LLM call
  infrastructure in `cmd_summarize_pr` (which should itself be refactored to
  use a shared `call_llm(prompt)` helper).
- `call_llm(prompt)` — shared LLM call using the `[llm]` config. Extracted
  from the ~60 lines of HTTP/provider logic currently inlined in
  `cmd_summarize_pr`.

**Refactored `cmd_dispatch_repair` reads like:**

```python
def cmd_dispatch_repair(args):
    pr_num, failure_context = parse_args(args)
    config = load_config()
    agent = identify_agent_from_pr(pr_num, config)
    issue_num = extract_issue_from_pr(pr_num)

    repair_count = count_pr_comments(pr_num, "repair-attempt")

    if repair_count < config.checks.max_repair_attempts:
        dispatch_repair_comment(pr_num, agent, failure_context)
        return

    # Repairs exhausted — try ralph restart
    ralph_count = count_issue_comments(issue_num, "ralph-restart", agent.name)

    if config.checks.max_ralph_loops > 0 and ralph_count < config.checks.max_ralph_loops:
        summary = summarize_failed_attempt(pr_num, failure_context, config.llm)
        close_and_cleanup_pr(pr_num, f"Closing for ralph restart ({ralph_count + 1}/{config.checks.max_ralph_loops}).")
        post_ralph_restart(issue_num, agent, ralph_count + 1, pr_num, summary)
        dispatch_agent(issue_num, agent.harness)
        return

    # Truly exhausted
    post_manual_intervention(issue_num, agent, pr_num, config.checks)
```

The existing repair-counting pattern (inline `gh pr view ... --jq ...`) should
also be migrated to `count_pr_comments(pr_num, "repair-attempt")` for
consistency, but that's a cleanup — not a blocker for ralph.

### `scripts/agent_ops.py`

- Extract `call_llm(prompt)` from `cmd_summarize_pr` — shared LLM call helper.
- Add helpers: `count_issue_comments`, `count_pr_comments`,
  `close_and_cleanup_pr`, `dispatch_agent`, `summarize_failed_attempt`,
  `post_ralph_restart`, `post_manual_intervention`.
- Refactor `cmd_dispatch_repair()` to use these helpers, with ralph loop logic
  as shown above.
- Refactor `cmd_summarize_pr()` to use `call_llm`.

### `scripts/config_parser.py`

Refactor to return `LBMConfig` dataclass (defined here or in a shared
`models.py`). The `from_dict` classmethods handle defaults and validation.
`max_ralph_loops` gets default `0` in `ChecksConfig`.

### `templates/lbm.toml.j2`

Add `max_ralph_loops = 0` under `[checks]` with a comment.

### `test/`

- `count_issue_comments` / `count_pr_comments`: marker matching, scoping.
- Ralph counter: scoped per agent letter.
- Max cap enforcement: ralph triggers at repair exhaustion when under cap.
- Disabled when `max_ralph_loops = 0`: falls through to manual intervention.
- `dispatch_agent` called with correct `issue_number` and `agent` inputs.
- `summarize_failed_attempt`: LLM prompt construction and summary extraction.
- `call_llm`: provider routing, error handling.

### No workflow changes

CI hooks workflow still calls `dispatch-repair` as today. The ralph logic is
entirely inside that function. The `gh workflow run` re-dispatch uses the
GitHub CLI, same as the existing dispatch mechanism.

## Lifecycle Example

Issue #49, Agent B (Codex), `max_repair_attempts=10`, `max_ralph_loops=3`:

```
Agent B creates PR #50 from fresh branch
  CI fails → repair 1/10 dispatched
  CI fails → repair 2/10 dispatched
  ...
  CI fails → repair 10/10 dispatched
  CI fails → repairs exhausted
    → ralph restart 1/3: close PR #50, delete branch, summarize failure
    → dispatch Agent B fresh

Agent B creates PR #51 from fresh branch
  CI fails → repair 1/10 dispatched
  CI passes → done!
```

If all 3 ralph restarts also exhaust repairs:
```
  → ralph restart 3/3 exhausted, repairs exhausted
  → "Agent B has failed after 3 restart cycles. Manual intervention needed."
```

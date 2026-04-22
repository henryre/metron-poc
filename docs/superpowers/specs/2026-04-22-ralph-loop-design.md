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

Default is `0` (disabled) so existing users are unaffected. Loaded by
`config_parser.py` alongside `max_repair_attempts`.

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

### `scripts/agent_ops.py`

Modify `cmd_dispatch_repair()`:
- After detecting repairs exhausted, insert ralph loop logic before the
  "manual intervention needed" fallback.
- New helper `count_ralph_restarts(issue_num, agent_letter)`: counts
  `[ralph-restart]` comments on the issue scoped to the agent letter.
- New helper `summarize_failed_attempt(pr_num, context)`: calls the LLM
  summary path with a prompt like "Summarize in 2-3 sentences what approach
  this PR took and why it kept failing." Uses PR diff + last CI errors as
  input.

### `scripts/config_parser.py`

Extract `checks.max_ralph_loops` with default `0`.

### `templates/lbm.toml.j2`

Add `max_ralph_loops = 0` under `[checks]` with a comment.

### `test/`

- Ralph counter parsing (scoped per agent letter).
- Max cap enforcement: ralph triggers at repair exhaustion when under cap.
- Disabled when `max_ralph_loops = 0`: falls through to "manual intervention".
- Re-dispatch called with correct `issue_number` and `agent` inputs.
- LLM summary generation for the approach description.

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

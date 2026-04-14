# Metron TODO

## Preflight Diagnostics

Add a diagnostic check that runs at the start of `_dispatch.yml` (before agent dispatch).
Checks:
- [ ] metron.toml exists and parses correctly
- [ ] Required secrets exist for configured harnesses (ANTHROPIC_API_KEY for claude, OPENAI_API_KEY for codex, GEMINI_API_KEY for openhands, PAT_TOKEN always)
- [ ] AGENTS.md exists if configured in metron.toml
- [ ] CI workflow referenced in [checks].required exists
- [ ] Agent labels exist on the repo (or auto-create them)
- [ ] ready-for-dev label exists

If any check fails, post a warning comment on the issue:
"⚠️ Metron preflight: missing OPENAI_API_KEY secret (required for codex harness). Agents may fail."

Then continue dispatching — don't block, just warn. Agents that can't run will fail on their own.

Implementation: add a `preflight` step in `_dispatch.yml` router job, before status table posting.
Use `gh secret list` to check secrets (only shows names, not values — sufficient).

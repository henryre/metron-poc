# LBM Hub — Design Spec

## Overview

LBM Hub is a SaaS web application that acts as a portal to GitHub repos using LBM. It provides a semantic and UX layer on top of LBM's in-repo infrastructure — reading and writing to repos, visualizing agent competition data, and enabling proposal-driven iteration planning.

LBM continues to be fully self-contained within repos. LBM Hub is optional and additive. Repos can be added/removed from LBM Hub at any time without impacting LBM behavior.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Framework | Next.js 15, App Router | Idiomatic Vercel deployment, RSC, API routes |
| Auth | NextAuth.js v5, GitHub provider | First-class Next.js integration, handles OAuth flow |
| Database | Vercel Postgres | Zero-config with Vercel, per-environment DBs |
| ORM | Drizzle + Drizzle Kit | TypeScript-first, SQL-like, lightweight, idiomatic migrations |
| Styling | Tailwind CSS v4 | Utility-first, pairs with Next.js idiomatically |
| Fonts | Inter (sans) + JetBrains Mono (mono) via `next/font` | Sans/mono pairing for UI + code/data distinction |
| Deployment | Vercel | Branch-based previews, `main`=prod, `staging` branch=staging |

All choices follow idiomatic patterns for their respective ecosystems. No complex overrides.

## Visual Design

**Palette**: Catppuccin Mocha — a terminal-inspired color scheme with a deep raisin base (#1e1e2e), blue accent (#89b4fa), and pastel syntax highlighting colors.

**Design language**:
- 4px border-radius (not rounded, not sharp)
- Subtle 1px borders using surface colors (#313244)
- Inter for UI text (headings, labels, nav), JetBrains Mono for data (stats, config, timestamps, metadata)
- Opacity-based hierarchy — leading items bright, trailing items fade
- Status lights: simple colored dots for iteration states
- Compact density — information-rich without clutter

**Status light colors** (4 states):
- Waiting (gray #585b70) — iteration tagged but agents not yet dispatched
- Working (blue #89b4fa) — agents actively competing
- Done (green #a6e3a1) — agents finished, awaiting merge decision
- Merged (lavender #cba6f7) — winning PR merged

## Navigation Pattern

Vercel-style repo context switching:

**Top-level** (no repo selected):
- Repos list (home/dashboard)
- Add a Repo
- User Settings

**Repo-scoped** (repo selected — sidebar switches):
- Overview (leaderboard, config, iterations table)
- Iterations (full list with filtering)
- Proposals (Phase 2)
- Agents (agent detail/config)
- Repo Settings

Repo selector is always visible (dropdown or breadcrumb in header). Switching repos changes the sidebar context.

## Data Model

### Phase 1 (MVP)

```
users
├── id (uuid, pk)
├── github_id (bigint, unique)
├── username (text)
├── display_name (text)
├── avatar_url (text)
├── access_token (text, encrypted)
├── created_at (timestamp)
└── updated_at (timestamp)

repos
├── id (uuid, pk)
├── github_repo_id (bigint, unique)
├── owner (text)
├── name (text)
├── lbm_config (jsonb — cached lbm.toml content)
├── lbm_config_fetched_at (timestamp)
├── onboarded_by (uuid, fk → users)
├── created_at (timestamp)
└── updated_at (timestamp)

repo_members
├── id (uuid, pk)
├── repo_id (uuid, fk → repos)
├── user_id (uuid, fk → users)
├── role (enum: read, write, admin)
├── synced_at (timestamp)
└── unique(repo_id, user_id)

iterations
├── id (uuid, pk)
├── repo_id (uuid, fk → repos)
├── github_issue_number (int)
├── github_issue_url (text)
├── title (text)
├── status (enum: waiting, working, done, merged)
├── winning_agent (text, nullable — agent label)
├── agent_count (int — how many agents participated)
├── created_at (timestamp)
└── updated_at (timestamp)

agent_results
├── id (uuid, pk)
├── repo_id (uuid, fk → repos)
├── iteration_id (uuid, fk → iterations)
├── agent_label (text — e.g. "agent:claude-opus-4-6")
├── model_id (text)
├── harness (text — claude, codex, openhands)
├── outcome (enum: win, loss, no_changes, error)
├── pr_number (int, nullable)
├── pr_url (text, nullable)
├── repair_attempts (int)
├── ralph_loops (int)
├── created_at (timestamp)
└── updated_at (timestamp)
```

### Phase 2 (Proposals & Iteration Planning)

```
proposals
├── id (uuid, pk)
├── repo_id (uuid, fk → repos)
├── author_id (uuid, fk → users)
├── title (text)
├── body (text)
├── status (enum: open, selected, archived)
├── created_at (timestamp)
└── updated_at (timestamp)

proposal_votes
├── id (uuid, pk)
├── proposal_id (uuid, fk → proposals)
├── user_id (uuid, fk → users)
├── vote (int — +1 or -1)
└── unique(proposal_id, user_id)

proposal_comments
├── id (uuid, pk)
├── proposal_id (uuid, fk → proposals)
├── user_id (uuid, fk → users)
├── body (text)
├── created_at (timestamp)
└── updated_at (timestamp)

iteration_proposals
├── iteration_id (uuid, fk → iterations)
├── proposal_id (uuid, fk → proposals)
└── unique(iteration_id, proposal_id)
```

Note: In Phase 2, iterations may be created from LBM Hub (selecting proposals → creating a GH Issue with the combined scope). The `iterations` table from Phase 1 also stores these, with the `github_issue_number` populated after the GH Issue is created.

## Pages

### Phase 1

| Route | Content | Access |
|---|---|---|
| `/` | Landing page (logged out), redirect to `/repos` (logged in) | Public/Auth |
| `/repos` | Grid of onboarded repos you have access to | Auth |
| `/repos/[owner]/[name]` | Repo overview — leaderboard, config, iterations | Auth + repo read |
| `/repos/[owner]/[name]/iterations` | Full iterations list with filtering/sorting | Auth + repo read |
| `/repos/[owner]/[name]/iterations/[id]` | Iteration detail — agent status, PRs, results | Auth + repo read |
| `/repos/[owner]/[name]/agents` | Agent list with per-agent stats | Auth + repo read |
| `/repos/[owner]/[name]/settings` | Repo settings, refresh config, remove from Hub | Auth + repo write |
| `/repos/[owner]/[name]/onboard` | Onboard wizard — verify lbm.toml, confirm | Auth + repo write |
| `/settings` | User settings, connected GitHub account | Auth |

### Phase 2 (adds)

| Route | Content | Access |
|---|---|---|
| `/repos/[owner]/[name]/proposals` | Proposals list, create new | Auth + repo read |
| `/repos/[owner]/[name]/proposals/[id]` | Proposal detail, vote, comment | Auth + repo read |
| `/repos/[owner]/[name]/iterations/new` | Create iteration from selected proposals | Auth + repo write |

## Repo Overview Page Layout

The primary page users land on when selecting a repo.

**Top section**: Repo name (large, Inter 800) + metadata line (mono — agent count, iterations count, runtime).

**Row 1** (two cards, side by side):
- **Leaderboard card** (smaller, ~40% width): Compact ranked list of agents. Each row: rank number (mono), agent name (sans), model ID (mono, muted), stacked win/loss bar, win rate % (sans, bold). Leading agent gets a subtle highlighted background + accent-colored bar.
- **Config card** (larger, ~60% width): Syntax-highlighted display of key lbm.toml fields — ready_label, runtime, max_repairs, max_ralph, agents list, deploy platform, required checks. Styled with Catppuccin syntax colors (blue keys, green strings, peach numbers).

**Row 2** (full-width iterations table):
- Table header: "Iterations" label + "View on GitHub ↗" outlink
- Columns: status light (dot), title + issue number (linked), status text, agent count, time ago
- Each row links to the iteration detail page. Issue number also links out to GitHub.

## GitHub Integration

**Auth flow**: NextAuth.js GitHub provider. Request scopes: `read:user`, `repo` (needed to check permissions and read repo contents). Access token stored encrypted in DB.

**Permission sync**: On login and periodically, check user's GitHub permissions for each onboarded repo via GitHub API. Cache in `repo_members` with TTL. Users only see repos they have GitHub access to.

**Data sync**:
- **lbm.toml**: Fetched from repo default branch on onboard. Refreshable from repo settings. Parsed and stored as JSONB.
- **Iterations**: Synced from GitHub Issues filtered by the repo's `ready_label`. Status derived from issue state + PR state.
- **Agent results**: Derived from PRs associated with iterations — branch prefix matching, labels, merge status.
- Sync can be triggered manually or run on a schedule (webhook integration is a Phase 3 enhancement).

## Phases

### Phase 1 — MVP
Auth + repo onboarding + repo overview (leaderboard, config, iterations table) + iteration detail + agent list + settings. Core value: see your LBM repos in one place with agent performance data and iteration status.

### Phase 2 — Proposals & Iteration Planning
Proposals CRUD, voting, commenting. Create iterations by selecting proposals, which generates a GitHub Issue with the combined scope. Repo-scoped proposal pages + cross-repo "my proposals" view.

### Phase 3 — Platform Features
- **LBM service account setup**: Help users configure a dedicated service account PAT for LBM in their repos, so LBM actions show as a consistent bot-like identity rather than a random user. LBM Hub could guide users through creating the service account and adding the PAT_TOKEN secret to their repo. (GitHub App approach is a future consideration but not in scope.)
- **Rich iteration view**: Structured display of an iteration showing per-agent status, PRs with diffs, repair attempt history, ralph loop restarts — all parsed from GitHub data but presented cleanly instead of scrolling through bot comments on the GH Issue.
- **Webhook-driven sync**: GitHub webhooks to update iteration/agent status in real-time instead of polling.
- **Admin dashboard**: User activity, repo activity, system health, management controls.
- **Analytics**: Historical win rate trends per agent, per repo. Cross-repo agent performance comparison.
- **Agent implementation reviews**: Per-iteration review system where users grade each agent's implementation (1-5 scale) with free-form fields for what the agent did well and what it did poorly. Submitted reviews are posted as comments on the corresponding GitHub Issue, keeping the feedback visible in the repo. Data model: `agent_reviews` table (iteration_id, agent_label, user_id, grade, did_well, did_poorly).
- **Notification system**: Email/in-app notifications for iteration completion, proposal activity.

## Staging/Prod Setup

Vercel's native environment model:
- `main` branch → Production deployment
- `staging` branch → Staging deployment (Vercel preview with persistent URL)
- Feature branches → Preview deployments
- Separate Vercel Postgres database per environment (created via Vercel dashboard, env vars auto-wired)
- Environment variables managed via Vercel dashboard, not committed

This is Vercel's standard pattern — no custom configuration needed.

## New Repo Setup

LBM Hub lives in its own repo (`lbm-hub`). To create:

```bash
npx create-next-app@latest lbm-hub --typescript --tailwind --eslint --app --src-dir
cd lbm-hub
npm install drizzle-orm @vercel/postgres next-auth@beta
npm install -D drizzle-kit
```

Then configure: NextAuth GitHub provider, Drizzle schema + connection, Tailwind with Catppuccin tokens, `next/font` for Inter + JetBrains Mono.

# Deploy Preview Plugin Design

## Summary

A pluggable preview deployment system for LBM that provides live, interactive preview URLs for agent-created PRs. The design supports two deployment models — **passive/webhook** (Vercel, Netlify) and **active/workflow** (Fly.io, Railway) — behind a unified contract. The first active implementation targets Fly.io with GHCR as the image registry.

## Goals

1. Every agent PR gets a live preview URL posted to the issue status table
2. Deploy failures trigger agent repair (same as CI failures)
3. Previews auto-clean on PR close/merge
4. LBM core stays platform-agnostic — platform logic lives in reusable workflows
5. The system works for any Dockerized app, not just DeepTutor

## Non-Goals

- Multi-environment promotion (staging → production)
- Preview auth/access control (previews are public URLs)
- Database/stateful-service provisioning (app must be self-contained in its container)

---

## Architecture

### Two Deployment Patterns

LBM supports two patterns depending on whether the deploy platform manages its own lifecycle or LBM orchestrates it:

| | Passive (Webhook) | Active (Workflow) |
|---|---|---|
| **Platforms** | Vercel, Netlify | Fly.io, Railway |
| **Who triggers deploy** | Platform (on push via GitHub App) | LBM workflow (after CI passes) |
| **How LBM learns URL** | `deployment_status` webhook event | Workflow step output |
| **How LBM learns failure** | `deployment_status` webhook event | Workflow step failure |
| **Cleanup** | Platform auto-deletes on PR close | LBM dispatches destroy workflow |
| **Image build** | Platform builds internally | GitHub Actions → GHCR |

### Unified Contract

LBM core cares about exactly 3 events regardless of platform:

1. **`preview-ready`** — A preview URL is live. Action: update status table, post implementation comment.
2. **`preview-failed`** — Deployment failed. Action: dispatch repair to agent with logs.
3. **`preview-cleanup`** — PR closed/merged. Action: tear down (if platform doesn't auto-clean).

Both patterns ultimately call the same `agent_ops.py` commands (`update-status`, `dispatch-repair`) to report results.

---

## Configuration

### `lbm.toml` — `[deploy]` Section

```toml
[deploy]
platform = "fly"              # vercel | netlify | fly | railway | none
preview_env = "Preview"       # GitHub environment name (for secrets + webhook matching)

# Active-platform-specific (ignored for passive platforms):
app_prefix = "deeptutor-pr"   # App/machine naming: {app_prefix}-{pr_number}
region = "iad"                # Deploy region
registry = "ghcr"             # Image registry: ghcr (only option for now)
```

### GitHub Environment: "Preview"

A GitHub Actions environment named to match `preview_env`. Contains:
- `FLY_API_TOKEN` — Fly.io API token
- `LLM_API_KEY` — shared LLM credentials for preview instances
- `EMBEDDING_API_KEY` — shared embedding credentials
- Any other runtime secrets the app needs

---

## Image Registry: GHCR

All active-platform deploys use GitHub Container Registry (`ghcr.io`):

- **Push**: GitHub Actions pushes using the built-in `GITHUB_TOKEN` (zero config)
- **Tag convention**: `ghcr.io/{owner}/{repo}:pr-{number}`
- **Pull**: Fly Machines pull from GHCR (public repos need no auth; private repos require a Fly registry secret configured once via `fly secrets set`)
- **Cleanup**: On PR close, delete the package version via GitHub API using `GITHUB_TOKEN` (has `packages:delete` scope in Actions)

This keeps the entire build pipeline within the GitHub ecosystem.

---

## Workflow Architecture

### Routing Layer: `_ci-hooks.yml` (Modified)

The existing CI hooks file gains two new jobs that route to active platform workflows:

```
CI passes on agent PR (workflow_run.success)
  → deploy-active job
  → reads [deploy].platform
  → if active platform: dispatches _deploy-{platform}.yml action=deploy
  → if passive platform: no-op (webhook handles it)

PR closed (pull_request.closed)
  → cleanup job
  → reads [deploy].platform
  → if active platform: dispatches _deploy-{platform}.yml action=destroy
  → if passive platform: no-op (platform auto-cleans)
```

Existing jobs stay untouched:
- `deploy-failure` — still catches `deployment_status` failures (Vercel/Netlify)
- `post-preview` — still catches `deployment_status` success (Vercel/Netlify)

### Active Platform Workflow: `_deploy-fly.yml`

Reusable workflow handling both deploy and destroy:

**Inputs:**
- `action`: `"deploy"` | `"destroy"`
- `pr_number`: PR number
- `branch`: head branch name
- `config-path`: path to lbm.toml

**Secrets:**
- `FLY_API_TOKEN`
- `PAT_TOKEN` (for GHCR + agent_ops)
- App runtime secrets (from Preview environment)

#### Deploy Action

```
1. Checkout PR branch
2. docker build -t ghcr.io/{owner}/{repo}:pr-{number} .
3. docker push ghcr.io/{owner}/{repo}:pr-{number}
4. fly apps create {app_prefix}-{number} --org {org} (if not exists)
5. fly deploy --image ghcr.io/{owner}/{repo}:pr-{number} \
     --region {region} \
     --env BACKEND_PORT=8001 \
     --env FRONTEND_PORT=3782 \
     --env LLM_API_KEY=*** \
     ...
6. Wait for health check (fly status --watch)
7. Extract URL: https://{app_prefix}-{number}.fly.dev
8. On success: python3 agent_ops.py update-status {issue} {agent} "preview" {pr} {url}
9. On failure: python3 agent_ops.py dispatch-repair {pr} "Deploy failed: {logs}"
```

#### Destroy Action

```
1. fly apps destroy {app_prefix}-{number} --yes
2. gh api --method DELETE /user/packages/container/{repo}/versions/{version_id}
   (delete GHCR image tag pr-{number})
```

---

## Fly.io Machine Configuration

### Dual-Port Routing

DeepTutor exposes two ports (frontend :3782, backend :8001). Fly exposes one HTTPS port per service. Solution: add a lightweight reverse proxy (Caddy) inside the container.

**Caddyfile** (added to DeepTutor repo):
```
:8080 {
    handle /api/* {
        reverse_proxy localhost:8001
    }
    handle {
        reverse_proxy localhost:3782
    }
}
```

**Supervisord addition:**
```ini
[program:proxy]
command=caddy run --config /app/Caddyfile
```

**Fly sees one port** (:8080) and routes all HTTPS traffic to it. Caddy splits `/api/*` to the FastAPI backend and everything else to Next.js.

### `fly.toml` (committed to target repo)

```toml
app = ""  # overridden per-deploy via --app flag

[build]
  image = ""  # overridden via --image flag

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = "stop"
  auto_start_machines = true
  min_machines_running = 0

[[vm]]
  size = "shared-cpu-2x"
  memory = "1gb"
```

**Auto-stop/auto-start**: Machines stop after 5 minutes of no traffic and restart on the next request (~2-3s wake time). At 3-10 concurrent previews, most machines will be stopped most of the time — cost stays minimal.

---

## Changes to DeepTutor Repo

| File | Change |
|---|---|
| `Caddyfile` | New — 6-line reverse proxy config |
| `Dockerfile` | Add: install caddy, copy Caddyfile, add caddy to supervisord |
| `fly.toml` | New — Fly service definition |
| `.github/workflows/lbm-ci-hooks.yml` | Add `deployment_status` + `pull_request` triggers calling LBM's `_ci-hooks.yml` |

The existing Dockerfile structure (multi-stage, supervisord, env injection) stays unchanged.

---

## Changes to LBM Core

| File | Change |
|---|---|
| `templates/lbm.toml.j2` | Add `app_prefix`, `region`, `registry` to `[deploy]` |
| `cli/main.py` | Update init questionnaire: add Fly option, prompt for app_prefix/region |
| `scripts/config_parser.py` | Add `get_deploy_config()` returning full deploy dict |
| `.github/workflows/_ci-hooks.yml` | Add `deploy-active` job + `cleanup` job |
| `.github/workflows/_deploy-fly.yml` | New — reusable Fly deploy/destroy workflow |
| `scripts/agent_ops.py` | No changes needed (update-status + dispatch-repair already work) |

### New config_parser function

```python
def get_deploy_config(config: dict) -> dict:
    """Return full deploy configuration with defaults."""
    deploy = config.get("deploy", {})
    return {
        "platform": deploy.get("platform", "none"),
        "preview_env": deploy.get("preview_env", "Preview"),
        "app_prefix": deploy.get("app_prefix", ""),
        "region": deploy.get("region", "iad"),
        "registry": deploy.get("registry", "ghcr"),
    }


def is_active_deploy_platform(config: dict) -> bool:
    """Return True if the platform requires LBM to orchestrate deploys."""
    return get_deploy_platform(config) in ("fly", "railway")
```

---

## Deploy Failure → Repair Flow

For active platforms, failure is detected inside `_deploy-fly.yml`:

```
fly deploy ... 2>&1 | tee /tmp/deploy.log
if [ $? -ne 0 ]; then
  LOGS=$(tail -50 /tmp/deploy.log)
  python3 agent_ops.py dispatch-repair "$PR_NUM" \
    "Deploy failed (CI passed but deploy did not). Likely causes: missing env vars, runtime errors during startup, port binding issues.

    Deploy logs:
    \`\`\`
    ${LOGS}
    \`\`\`"
fi
```

For passive platforms (Vercel), the existing `deploy-failure` job in `_ci-hooks.yml` handles this identically — it catches the `deployment_status` failure event and dispatches repair with Vercel logs.

Both paths end at the same `dispatch-repair` command. The agent experience is identical regardless of platform.

---

## Lifecycle Summary

```
Issue labeled "ready-for-dev"
  ↓
Agents dispatched → create PRs
  ↓
CI passes (lint, typecheck, build)
  ↓
_ci-hooks.yml:deploy-active triggers
  ↓
_deploy-fly.yml:deploy
  ├── Build image → push ghcr.io/{owner}/{repo}:pr-{n}
  ├── fly deploy --image ... --app {prefix}-{n}
  ├── Health check passes?
  │   ├── YES → update-status with preview URL
  │   └── NO → dispatch-repair with deploy logs
  ↓
Status table updated: [Preview](https://{prefix}-{n}.fly.dev)
Implementation comment posted on issue
  ↓
User reviews live preview, selects /merge agent X
  ↓
PR merged → pull_request.closed event
  ↓
_ci-hooks.yml:cleanup triggers
  ↓
_deploy-fly.yml:destroy
  ├── fly apps destroy {prefix}-{n}
  └── Delete ghcr.io image tag pr-{n}
```

---

## Cost Estimate (Fly.io)

| Component | Cost |
|---|---|
| Fly shared-cpu-2x + 1GB RAM | ~$0.01/hr when running |
| Auto-stopped machines | $0 (only disk: ~$0.15/mo per GB) |
| 5 concurrent previews, each active 2hr/day | ~$3/mo |
| GHCR storage | Free (public repos) |
| Bandwidth | Included in Fly free tier (up to 100GB/mo) |

---

## Future Platform Plugins

Adding a new platform (e.g., Railway) requires:
1. Create `_deploy-railway.yml` reusable workflow implementing deploy/destroy
2. Add `"railway"` to `is_active_deploy_platform()` list
3. Add to CLI init questionnaire
4. Document platform-specific config fields

No changes to LBM core logic, agent_ops, or the status table system.

"""Metron CLI — setup multi-agent dev infra for any repo."""

from pathlib import Path

import click
from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"

# Default agent configs per harness
DEFAULT_AGENTS = {
    "claude": {
        "harness": "claude",
        "model_id": "global.anthropic.claude-opus-4-6-v1",
        "model_label": "opus-4-6",
        "mention": "@claude",
    },
    "codex": {
        "harness": "codex",
        "model_id": "gpt-5.3-codex",
        "model_label": "gpt-5.3",
        "mention": "@codex",
    },
    "openhands": {
        "harness": "openhands",
        "model_id": "gemini/gemini-3.1-pro-preview",
        "model_label": "gemini-3.1-pro",
        "mention": "@openhands-agent",
    },
}

RUNTIME_DEFAULTS = {
    "node": {"install": "npm ci", "lint": "npm run lint", "typecheck": "npx tsc --noEmit", "build": "npm run build"},
    "python": {"install": "pip install -e '.[dev]'", "lint": "ruff check .", "typecheck": "", "build": ""},
    "go": {"install": "", "lint": "golangci-lint run", "typecheck": "", "build": "go build ./..."},
    "rust": {"install": "", "lint": "cargo clippy", "typecheck": "", "build": "cargo build"},
    "custom": {"install": "", "lint": "", "typecheck": "", "build": ""},
}

LLM_DEFAULTS = {
    "portkey": {"summary_model": "@bedrock/global.anthropic.claude-sonnet-4-6"},
    "anthropic": {"summary_model": "claude-sonnet-4-6"},
    "openai": {"summary_model": "gpt-4o"},
}


@click.group()
def cli():
    """Metron — multi-agent dev infra for competing AI implementations."""
    pass


@cli.command()
@click.option("--metron-repo", default="henryre/metron-poc", help="Central metron repo")
@click.option("--metron-ref", default="v1", help="Version ref to pin")
def init(metron_repo, metron_ref):
    """Initialize metron in the current repository."""
    click.echo("Metron Setup\n")

    # Prompts
    runtime = click.prompt("Runtime", type=click.Choice(["node", "python", "go", "rust", "custom"]), default="node")
    deploy_platform = click.prompt(
        "Deploy platform", type=click.Choice(["vercel", "netlify", "cloudflare", "none"]), default="none"
    )
    database_orm = click.prompt("Database ORM", type=click.Choice(["prisma", "drizzle", "none"]), default="none")

    available_agents = list(DEFAULT_AGENTS.keys())
    click.echo(f"\nAvailable agents: {', '.join(available_agents)}")
    agent_choices = click.prompt("Which agents? (comma-separated)", default="claude,codex")
    selected_agents = [a.strip() for a in agent_choices.split(",") if a.strip() in available_agents]

    llm_provider = click.prompt(
        "LLM provider (for PR summaries)", type=click.Choice(["portkey", "anthropic", "openai"]), default="portkey"
    )

    # Build template context
    rt = RUNTIME_DEFAULTS.get(runtime, RUNTIME_DEFAULTS["custom"])
    harnesses = {name: {"mention": DEFAULT_AGENTS[name]["mention"]} for name in selected_agents}
    agents = [DEFAULT_AGENTS[name] for name in selected_agents]

    context = {
        "metron_repo": metron_repo,
        "metron_ref": metron_ref,
        "runtime": runtime,
        "install_cmd": rt["install"],
        "lint_cmd": rt["lint"],
        "typecheck_cmd": rt["typecheck"],
        "build_cmd": rt["build"],
        "deploy_platform": deploy_platform,
        "database_orm": database_orm,
        "llm_provider": llm_provider,
        "summary_model": LLM_DEFAULTS.get(llm_provider, LLM_DEFAULTS["portkey"])["summary_model"],
        "harnesses": harnesses,
        "agents": agents,
        "guidance_file": "AGENTS.md",
        "required_checks": '["CI"]',
    }

    # Render templates
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), keep_trailing_newline=True)

    workflows_dir = Path(".github/workflows")
    workflows_dir.mkdir(parents=True, exist_ok=True)

    for template_name in ["metron-dispatch.yml", "metron-comments.yml", "metron-agents.yml", "metron-ci-hooks.yml"]:
        template = env.get_template(f"{template_name}.j2")
        output = template.render(**context)
        output_path = workflows_dir / template_name
        output_path.write_text(output)
        click.echo(f"  Created {output_path}")

    # Render metron.toml
    template = env.get_template("metron.toml.j2")
    output = template.render(**context)
    Path("metron.toml").write_text(output)
    click.echo("  Created metron.toml")

    # Render AGENTS.md only if it doesn't exist
    if not Path("AGENTS.md").exists():
        template = env.get_template("AGENTS.md.j2")
        output = template.render(**context)
        Path("AGENTS.md").write_text(output)
        click.echo("  Created AGENTS.md")
    else:
        click.echo("  AGENTS.md already exists, skipping")

    # Print setup instructions
    click.echo("\n--- Setup Instructions ---")
    click.echo("Add these GitHub repo secrets:")
    for name in selected_agents:
        if name == "claude":
            click.echo("  ANTHROPIC_API_KEY (or PORTKEY_API_KEY + PORTKEY_BEDROCK_SLUG)")
        elif name == "codex":
            click.echo("  OPENAI_API_KEY")
        elif name == "openhands":
            click.echo("  GEMINI_API_KEY")
    click.echo("  PAT_TOKEN (GitHub PAT with repo scope)")
    if llm_provider == "portkey":
        click.echo("  PORTKEY_API_KEY (for PR summaries)")
    click.echo("\nCustomize AGENTS.md with your codebase-specific guidance.")
    click.echo("Create an issue, add the 'ready-for-dev' label, and agents will start.")


if __name__ == "__main__":
    cli()

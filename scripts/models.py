"""Typed dataclass config models for lbm.toml configuration.

Provides AgentConfig, ChecksConfig, LLMConfig, and LBMConfig.
LBMConfig.from_parsed_toml resolves agents from [harnesses] and [[agents]]
sections, deriving labels, branch prefixes, and name letters.
"""

from __future__ import annotations

from dataclasses import dataclass, field

AGENT_NAME_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass(frozen=True)
class AgentConfig:
    label: str
    harness: str
    model_id: str
    model_label: str
    branch_prefix: str
    name: str
    mention: str

    @classmethod
    def from_dict(cls, d: dict) -> AgentConfig:
        return cls(
            label=d["label"],
            harness=d["harness"],
            model_id=d["model_id"],
            model_label=d["model_label"],
            branch_prefix=d["branch_prefix"],
            name=d["name"],
            mention=d["mention"],
        )


@dataclass(frozen=True)
class ChecksConfig:
    required: list[str] = field(default_factory=list)
    repair_from: list[str] = field(default_factory=list)
    max_repair_attempts: int = 10
    max_ralph_loops: int = 0

    @classmethod
    def from_dict(cls, d: dict) -> ChecksConfig:
        return cls(
            required=d.get("required", []),
            repair_from=d.get("repair_from", []),
            max_repair_attempts=d.get("max_repair_attempts", 10),
            max_ralph_loops=d.get("max_ralph_loops", 0),
        )


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "anthropic"
    summary_model: str = "claude-sonnet-4-6"

    @classmethod
    def from_dict(cls, d: dict) -> LLMConfig:
        return cls(
            provider=d.get("provider", "anthropic"),
            summary_model=d.get("summary_model", "claude-sonnet-4-6"),
        )


@dataclass
class LBMConfig:
    agents: list[AgentConfig]
    checks: ChecksConfig
    llm: LLMConfig

    @classmethod
    def from_parsed_toml(cls, raw: dict) -> LBMConfig:
        """Build LBMConfig from a raw parsed TOML dict.

        Resolves agents from [harnesses] and [[agents]] sections, deriving
        default label, branch_prefix, and name letter for each agent.
        Validates no duplicate branch prefixes and that all harnesses are defined.
        """
        harnesses = raw.get("harnesses", {})
        agents_raw = raw.get("agents", [])

        agents: list[AgentConfig] = []
        seen_prefixes: set[str] = set()

        for i, entry in enumerate(agents_raw):
            harness = entry["harness"]
            model_id = entry["model_id"]
            model_label = entry["model_label"]

            if harness not in harnesses:
                raise ValueError(
                    f"Harness '{harness}' not defined in [harnesses]. "
                    f"Available: {list(harnesses.keys())}"
                )

            default_label = f"agent:{harness}-{model_label}"
            default_prefix = f"{harness}-{model_label}/"

            label = entry.get("override_label", default_label)
            branch_prefix = entry.get("override_branch_prefix", default_prefix)

            if branch_prefix in seen_prefixes:
                raise ValueError(
                    f"Duplicate branch_prefix '{branch_prefix}' -- "
                    "each agent entry must have a unique prefix"
                )
            seen_prefixes.add(branch_prefix)

            name_letter = AGENT_NAME_LETTERS[i] if i < len(AGENT_NAME_LETTERS) else str(i + 1)
            name = f"Agent {name_letter}"
            mention = harnesses[harness].get("mention", "")

            agents.append(
                AgentConfig(
                    label=label,
                    harness=harness,
                    model_id=model_id,
                    model_label=model_label,
                    branch_prefix=branch_prefix,
                    name=name,
                    mention=mention,
                )
            )

        checks = ChecksConfig.from_dict(raw.get("checks", {}))
        llm = LLMConfig.from_dict(raw.get("llm", {}))

        return cls(agents=agents, checks=checks, llm=llm)

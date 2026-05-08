# Agent Loop Control

Local-first safety control plane for AI coding agents.

Agent Loop Control helps teams run agents such as Claude Code, Codex CLI, Codex App, and future MCP-based tools with fewer approval prompts while preserving local auditability, policy enforcement, and continuous improvement of Skills, agents, and permissions.

## Goal

Make local AI agents safe enough for autonomous work and accountable enough for enterprise use.

The project focuses on:

- Reducing approval fatigue through policy-based autonomy.
- Recording local agent actions in a tamper-evident ledger.
- Tracking file provenance from prompt to tool call to diff.
- Supporting Claude Code and Codex CLI without relying on provider-side logs.
- Turning execution history into recommendations for Skills, agents, hooks, and policy improvements.

## Why This Exists

Agent tools can already edit files, run commands, call MCP servers, and interact with cloud resources. Current safety models often fall into two weak patterns:

- Ask for approval on almost everything, which creates approval fatigue.
- Allow broad autonomy without enough evidence, which creates operational risk.

Agent Loop Control aims for the middle path:

```text
policy-defined autonomy + local audit evidence + improvement loop
```

## Core Loop

```text
Intent -> Plan -> Risk Classify -> Execute -> Verify -> Audit -> Review -> Optimize
```

Low-risk actions run automatically. High-risk actions ask for human review. Denied actions are blocked. Every decision and result is recorded locally.

## Initial MVP

- `agent-policy.yaml` for allow / ask / deny rules.
- Claude Code hook collector.
- Codex CLI session JSONL importer.
- Hash-chained local ledger.
- Git diff snapshotting.
- Timeline and provenance views.
- Analyzer for approval fatigue, repeated failures, risky actions, and Skill improvement candidates.

## Repository Map

- [docs/project-brief.md](docs/project-brief.md): product brief and positioning.
- [docs/development-instructions.md](docs/development-instructions.md): instructions for GitHub-based development.
- [docs/architecture.md](docs/architecture.md): system architecture.
- [docs/roadmap.md](docs/roadmap.md): staged implementation plan.
- [examples/agent-policy.yaml](examples/agent-policy.yaml): sample policy.
- [examples/collector/claude-settings.json](examples/collector/claude-settings.json): sample Claude Code hooks config.
- [schemas/agent-ledger-event.schema.json](schemas/agent-ledger-event.schema.json): ledger event schema.
- [schemas/agent-policy.schema.json](schemas/agent-policy.schema.json): policy file schema.

## Non-Goals

- Capturing hidden model reasoning.
- Requiring Bedrock, Anthropic, or OpenAI provider-side logs.
- Bypassing agent approval systems.
- Replacing SIEM, EDR, or cloud audit systems.

## License

Apache-2.0. See [LICENSE](LICENSE).


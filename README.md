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

Low-risk actions can be allowed by policy. High-risk actions can be routed to human
review. Denied actions are recorded as policy denials for the surrounding agent
workflow to enforce. Every captured decision and result is recorded locally.

## Initial MVP

- `agent-policy.yaml` for allow / ask / deny rules.
- Claude Code hook collector.
- Codex CLI session JSONL importer.
- Hash-chained local ledger.
- Git diff snapshotting.
- Timeline and provenance views.
- Analyzer for approval fatigue, repeated failures, risky actions, and Skill improvement candidates.

## Installation

The project is a Python CLI package. Python 3.11 or newer is required.

For local development or first-time evaluation, clone the repository and run the CLI
through `uv`:

```bash
git clone https://github.com/takibi-lab/agent-loop-control.git
cd agent-loop-control
uv sync
uv run agent-loop --help
```

To install the `agent-loop` command on your PATH from a local checkout:

```bash
uv tool install .
agent-loop --version
```

To install directly from GitHub:

```bash
uv tool install git+https://github.com/takibi-lab/agent-loop-control.git
agent-loop --version
```

If you do not use `uv`, install with any standard Python package tool that supports
`pyproject.toml`, for example:

```bash
python -m pip install .
```

## Quick Start

Create a local config directory, copy the sample policy, and validate it:

```bash
mkdir -p ~/.agent-loop
cp examples/agent-policy.yaml ~/.agent-loop/agent-policy.yaml
agent-loop policy check ~/.agent-loop/agent-policy.yaml
```

If you are working from a checkout without installing the command, replace
`agent-loop` with `uv run agent-loop` in the examples below.

Capture a sample Claude Code hook event into a local ledger:

```bash
agent-loop hook collect \
  --ledger ~/.agent-loop/ledger.jsonl \
  --policy-file ~/.agent-loop/agent-policy.yaml \
  < examples/collector/claude-hook-input.json
```

Verify and inspect the ledger:

```bash
agent-loop verify ~/.agent-loop/ledger.jsonl
agent-loop timeline ~/.agent-loop/ledger.jsonl
agent-loop search ~/.agent-loop/ledger.jsonl --decision allow
agent-loop search ~/.agent-loop/ledger.jsonl --file-path .env
agent-loop analyze ~/.agent-loop/ledger.jsonl
```

Capture the current Git repository state and staged/unstaged diff hash:

```bash
agent-loop snapshot --ledger ~/.agent-loop/ledger.jsonl --repo .
```

Import a Codex CLI session JSONL file:

```bash
agent-loop import ~/.codex/sessions/<session-file>.jsonl \
  --ledger ~/.agent-loop/ledger.jsonl \
  --agent codex-cli
```

## Claude Code Hooks

The sample Claude Code hook configuration is in
[`examples/collector/claude-settings.json`](examples/collector/claude-settings.json).
Merge its `hooks` object into your Claude Code settings file and make sure the
`agent-loop` command is available on the PATH used by Claude Code.

The sample hook commands write to `~/.agent-loop/ledger.jsonl` and classify
pre-tool events with `~/.agent-loop/agent-policy.yaml`:

```json
{
  "type": "command",
  "command": "agent-loop hook collect --ledger ~/.agent-loop/ledger.jsonl --policy-file ~/.agent-loop/agent-policy.yaml"
}
```

For a project-local setup, change the ledger and policy paths to files inside the
repository, for example:

```json
{
  "type": "command",
  "command": "agent-loop hook collect --ledger .agent-loop/ledger.jsonl --policy-file .agent-loop/agent-policy.yaml"
}
```

The MVP hook collector records policy classifications and redacted hook inputs in
the ledger. It does not replace Claude Code's own approval system or provider-side
controls.

## CLI Reference

Common commands:

```bash
agent-loop policy check [agent-policy.yaml]
agent-loop policy classify --tool Bash --command "git status" --policy-file agent-policy.yaml
agent-loop hook collect --ledger agent-ledger.jsonl --policy-file agent-policy.yaml
agent-loop import <codex-session.jsonl> --ledger agent-ledger.jsonl --agent codex-cli
agent-loop snapshot --ledger agent-ledger.jsonl --repo .
agent-loop verify agent-ledger.jsonl
agent-loop timeline agent-ledger.jsonl --limit 50
agent-loop search agent-ledger.jsonl --type tool.pre --decision deny
agent-loop analyze agent-ledger.jsonl
```

## Policy Semantics

Rules in `agent-policy.yaml` are deterministic and explainable. When one rule contains
multiple matcher groups such as `tools`, `commands`, and `paths`, those groups use OR
semantics: any matching group matches the rule. Use separate rule IDs when a workflow
needs a different rationale or risk label for each condition.

## MVP Trust Boundaries

- Ledger writes use POSIX `fcntl` file locking. Windows support is best-effort in the
  MVP and does not provide the same locking guarantee.
- Hook bypasses are outside the evidence boundary. Actions not captured by a collector
  are not present in the ledger.
- Provider-side logs and hidden model reasoning are not captured.
- Redaction is best-effort and depends on policy-provided regular expressions. A weak
  pattern can miss secrets, and a pathological pattern can slow hook execution.
- Claude Code `tool.input_full` is persisted only after configured redaction has run.
- If `redaction.enabled` is set to `false`, full hook inputs may be written to the
  local ledger without masking. Use this only for ledgers that cannot contain secrets.

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

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
- Codex CLI and Claude Code session transcript importer.
- Single hash-chained local ledger with repository context on each event.
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

Capture a sample Claude Code hook event into the global local ledger:

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

`verify` always validates the full JSONL hash chain. Repository options on read
commands are filters for display and reporting; they do not create or validate a
separate per-repository chain.

Filter views to one repository while keeping the single global ledger:

```bash
agent-loop timeline ~/.agent-loop/ledger.jsonl --repo .
agent-loop timeline ~/.agent-loop/ledger.jsonl --repo-root /path/to/repo
agent-loop search ~/.agent-loop/ledger.jsonl --repo . --decision deny
agent-loop search ~/.agent-loop/ledger.jsonl --repo-root /path/to/repo --file-path pyproject.toml
agent-loop analyze ~/.agent-loop/ledger.jsonl --repo .
agent-loop analyze ~/.agent-loop/ledger.jsonl --group-by repo
```

Capture the current Git repository state and staged/unstaged diff hash:

```bash
agent-loop snapshot --ledger ~/.agent-loop/ledger.jsonl --repo .
```

Import a session transcript. The format (Codex CLI / Codex Desktop / Claude Code)
is auto-detected; use `--format` to override:

```bash
agent-loop import ~/.codex/sessions/<session-file>.jsonl \
  --ledger ~/.agent-loop/ledger.jsonl \
  --agent codex-desktop \
  --cwd /path/to/repo
```

Claude Code transcripts live under `~/.claude/projects/<project>/`. Importing the
main `<session-id>.jsonl` also pulls in any sub-agent transcripts found under
`<session-id>/subagents/` and attributes them to the parent session:

```bash
agent-loop import ~/.claude/projects/<project>/<session-id>.jsonl \
  --ledger ~/.agent-loop/ledger.jsonl
```

Pass `--policy-file` to classify imported `tool.pre` events against a policy, so
`agent-loop analyze` can report approval fatigue for imported history as well as
for live hook events:

```bash
agent-loop import ~/.codex/sessions/<session-file>.jsonl \
  --ledger ~/.agent-loop/ledger.jsonl \
  --policy-file ~/.agent-loop/agent-policy.yaml
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

Keep the ledger path global. A project may keep its policy in the repository if
that is useful, but writing ledger files under the project directory is discouraged:
it splits the tamper-evident chain and increases the chance of accidentally adding
local audit data to Git. Repository separation is handled by `session.cwd` and the
optional `repo` fields stored on each event, then by read-time filters such as
`--repo .` and `--repo-root /path/to/repo`.

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
agent-loop import <session.jsonl> --ledger agent-ledger.jsonl --policy-file agent-policy.yaml
agent-loop snapshot --ledger agent-ledger.jsonl --repo .
agent-loop verify agent-ledger.jsonl
agent-loop timeline agent-ledger.jsonl --limit 50 --repo .
agent-loop search agent-ledger.jsonl --type tool.pre --decision deny --repo-root /path/to/repo
agent-loop analyze agent-ledger.jsonl --repo .
agent-loop analyze agent-ledger.jsonl --group-by repo
```

Prefer `~/.agent-loop/ledger.jsonl` for real use. Short local names such as
`agent-ledger.jsonl` are convenient for examples, tests, and disposable demos.

## Policy Semantics

Rules in `agent-policy.yaml` are deterministic and explainable. When one rule contains
multiple matcher groups such as `tools`, `commands`, and `paths`, those groups use OR
semantics: any matching group matches the rule. Use separate rule IDs when a workflow
needs a different rationale or risk label for each condition.

## MVP Trust Boundaries

- Ledger writes use POSIX `fcntl` file locking. Windows support is best-effort in the
  MVP and does not provide the same locking guarantee.
- The canonical deployment model is one local JSONL ledger, normally
  `~/.agent-loop/ledger.jsonl`. Per-repository ledger files are supported only as
  ad hoc inputs and weaken cross-repository tamper evidence.
- Repository filters on `timeline`, `search`, and `analyze` narrow the events shown
  after loading the ledger. They are not a substitute for `agent-loop verify`, which
  checks the complete hash chain.
- `repo.root` and `session.cwd` may contain absolute local paths. If you enable path
  anonymization redaction for shared reports, prefer `repo.remote` filters because
  exact root-path filtering becomes less precise.
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

# Architecture

## Overview

Agent Loop Control is a local control plane around coding agents.

```text
Agent Runtime
  Claude Code / Codex CLI / Codex App / future MCP tools
        |
        v
Collectors
  hooks / JSONL importers / wrappers
        |
        v
Normalizer
  common event model
        |
        v
Policy Engine --------> allow / ask / deny
        |
        v
Ledger
  append-only JSONL + hash chain
        |
        v
Analyzers
  approvals / risk / provenance / skill improvement
        |
        v
UI and Reports
  timeline / search / analyze / recommendations / export
```

## Components

### Collectors

Collectors capture raw activity from agent tools and convert it into normalized events.

Initial collectors:

- Claude Code hook collector.
- Codex CLI JSONL importer.
- Codex hook collector, when available.

Optional future collectors:

- Terminal recorder adapter.
- GitHub agent session importer.
- MCP gateway collector.

### Normalizer

The normalizer maps source-specific records to the common ledger schema.

Examples:

- Claude Code `PreToolUse` with `tool_name: Bash` becomes `tool.pre`.
- Claude Code `PostToolUse` becomes `tool.post`.
- Codex session JSONL tool calls become `tool.pre` / `tool.post` when enough information exists.

### Policy Engine

The policy engine classifies tool calls and file operations.

Decision values:

- `allow`
- `ask`
- `deny`

The engine should be deterministic and explainable. Every decision must include the matched rule ID and rationale.

### Ledger

The ledger is a single append-only JSONL file, normally
`~/.agent-loop/ledger.jsonl`. Agent Loop Control keeps one physical hash chain
across repositories and separates repositories logically with context fields on
each event. This preserves cross-repository tamper evidence while still allowing
repo-scoped views.

Each event includes:

- Event identity.
- Source and session.
- Session working directory, when known.
- Repository context, when resolved.
- Tool/action information.
- Policy decision where relevant.
- Diff snapshot references where relevant.
- `prev_hash`.
- `hash`.

The hash chain makes edits detectable. `agent-loop verify` validates the complete
chain for the ledger file; repository filters are applied only by read-side views
and reports after the chain has been read.

Repository context is resolved from the event working directory where possible:

- `session.cwd` records the collector or imported session working directory.
- `repo.root` records the normalized Git worktree root.
- `repo.remote` records the origin remote when available.
- `repo.branch` records the current branch when available.

For non-Git directories, `repo` may be absent and `session.cwd` remains the
fallback identity. Project-local ledger files are not the recommended operating
model because they split the chain and can be accidentally committed.

Read-side repository filters:

```bash
agent-loop timeline ~/.agent-loop/ledger.jsonl --repo .
agent-loop timeline ~/.agent-loop/ledger.jsonl --repo-root /path/to/repo
agent-loop search ~/.agent-loop/ledger.jsonl --repo . --decision allow
agent-loop analyze ~/.agent-loop/ledger.jsonl --repo .
agent-loop analyze ~/.agent-loop/ledger.jsonl --group-by repo
```

### Diff Snapshotter

The diff snapshotter captures Git state around meaningful events.

Useful snapshots:

- Before high-risk command.
- After file write.
- Before approval request.
- After verification.
- At session end.

### Analyzers

Analyzers turn evidence into operational improvements.

Initial analyzers:

- Approval fatigue: noisy approval prompts and repeated low-risk approvals.
- Risky actions: blocked or high-risk actions.
- Repeated failures: loops, repeated failing commands, repeated edits.
- File provenance: why and how a file changed.
- Skill improvement: candidate improvements for Skills, AGENTS.md, CLAUDE.md, and policy.

## Security Model

Agent Loop Control should be treated as an evidence and control layer, not a perfect sandbox.

Security assumptions:

- The local machine may contain secrets.
- Provider logs may be unavailable.
- Hooks can be misconfigured.
- Agents can make mistakes.
- Shell commands can be dangerous.

Mitigations:

- Local-only by default.
- Deny sensitive paths.
- Redact secrets before persistence.
- Hash-chain ledger.
- Policy-as-code.
- Explicit blind spot reporting.

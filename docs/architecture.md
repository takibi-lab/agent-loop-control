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
  timeline / search / recommendations / export
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

The ledger is append-only JSONL. Each event includes:

- Event identity.
- Source and session.
- Tool/action information.
- Policy decision where relevant.
- Diff snapshot references where relevant.
- `prev_hash`.
- `hash`.

The hash chain makes edits detectable.

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


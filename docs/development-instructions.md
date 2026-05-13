# GitHub Development Instructions

Use this file as the initial issue, project README supplement, or onboarding prompt for agents working on this repository.

## Mission

Build a local-first control plane that lets developers and companies run AI coding agents safely with minimal approval work, while preserving evidence for audit and continuously improving agent behavior.

## Initial Scope

Start with local evidence and control. Do not depend on Bedrock, Anthropic, OpenAI, or GitHub provider-side logs.

Priority order:

1. Ledger schema and append-only writer.
2. Policy parser and action classifier.
3. Claude Code hook collector.
4. Codex CLI JSONL importer.
5. Git diff snapshotter.
6. Ledger verifier.
7. CLI timeline/search.
8. Approval fatigue and Skill improvement analyzers.

## Expected User Flow

```text
agent-loop init
agent-loop policy check examples/agent-policy.yaml
agent-loop hook install claude-code
agent-loop import codex ~/.codex/sessions
agent-loop verify
agent-loop timeline
agent-loop analyze approvals
agent-loop recommend skills
```

## Core Requirements

- Store ledger events as JSONL.
- Each event must include `prev_hash` and `hash`.
- Hashes must cover canonicalized event content.
- The system must work without network access.
- Secrets must be redacted before persistence where possible.
- Raw local logs should remain local unless the user explicitly exports them.
- Dangerous operations must be classifiable before execution when hooks provide pre-tool events.

## Policy Requirements

The policy format should support:

- Allow rules.
- Ask rules.
- Deny rules.
- File path patterns.
- Command prefix patterns.
- Tool names.
- Risk labels.
- Human-readable rationale.

Policy decisions:

- `allow`: run without prompting.
- `ask`: request human approval and record the reason.
- `deny`: block and record the reason.

## Ledger Event Types

Initial event types:

- `session.start`
- `session.end`
- `prompt.submitted`
- `plan.proposed`
- `policy.decision`
- `approval.requested`
- `approval.resolved`
- `tool.pre`
- `tool.post`
- `tool.error`
- `file.read`
- `file.write`
- `git.diff_snapshot`
- `verify.result`
- `recommendation.created`

## Claude Code Integration

Use Claude Code hooks:

- `UserPromptSubmit`
- `PreToolUse`
- `PostToolUse`
- `PostToolUseFailure`
- `PermissionRequest`
- `PermissionDenied`
- `SessionStart`
- `SessionEnd`

The hook collector should read JSON from stdin and append normalized events to the ledger.

## Codex Integration

Use two modes:

1. Import existing Codex CLI or Codex Desktop session JSONL files.
2. Add Codex hooks when available and enabled.

Codex support should degrade gracefully. If some events cannot be captured, record a blind spot declaration.

## Blind Spot Declaration

The tool must explicitly report what it cannot prove.

Examples:

- Hidden model reasoning is not captured.
- Provider-side request/response logs are unavailable.
- Some terminal output may be missing if the agent bypassed hooks.
- Provider token/cost numbers may be estimates unless exported by the tool.

## Recommended GitHub Milestones

### Milestone 0: Project Foundation

- README.
- License.
- Event schema.
- Example policy.
- CLI command outline.

### Milestone 1: Local Ledger

- Append-only JSONL writer.
- Hash-chain verifier.
- Redaction helper.
- Basic tests.

### Milestone 2: Claude Code MVP

- Hook collector.
- Policy decision support.
- Command/file event normalization.
- Install instructions.

### Milestone 3: Codex MVP

- Session JSONL importer.
- Codex hook support where available.
- Blind spot report.

### Milestone 4: Analysis

- Approval fatigue report.
- Risky action report.
- Repeated failure report.
- File provenance report.

### Milestone 5: Optimization Loop

- Generate policy improvement suggestions.
- Generate Skill / AGENTS.md / CLAUDE.md improvement suggestions.
- Emit reviewable patches or PR-ready diffs.

## Agent Instructions

When using an AI agent to develop this repository:

- Keep changes small and reviewable.
- Prefer local tests over network-dependent tests.
- Do not add telemetry or cloud export by default.
- Do not store secrets in test fixtures.
- When adding a collector, include sample input and normalized output.
- When adding a policy feature, include allow / ask / deny test cases.
- When adding an analyzer, include a clear explanation of false positives and blind spots.

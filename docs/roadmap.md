# Roadmap

## Phase 0: Repository Foundation

- [x] Pick license.
- [x] Define event schema.
- [x] Define policy schema.
- [x] Add examples.
- [x] Add contributor instructions.

## Phase 1: Ledger MVP

- [x] Implement append-only JSONL writer.
- [x] Implement canonical JSON hashing.
- [x] Implement hash-chain verification.
- [x] Add unit tests.
- [ ] Add sample ledger and verifier output.

## Phase 2: Policy MVP

- [x] Parse `agent-policy.yaml`.
- [x] Match command prefixes.
- [x] Match file path patterns.
- [x] Match tool names.
- [x] Return allow / ask / deny decisions with rationale.
- [x] Add policy tests.

## Phase 3: Claude Code Collector

- [x] Build hook command that reads JSON from stdin.
- [x] Normalize `PreToolUse`.
- [x] Normalize `PostToolUse`.
- [x] Normalize permission events.
- [ ] Add installer for `.claude/settings.json`. （サンプルのみ。インストーラは未実装）
- [x] Add safe sample config.
- [x] Import Claude Code session transcripts (tool_use / tool_result blocks).
- [x] Import sub-agent transcripts under `subagents/` and attribute them.

## Phase 4: Codex CLI Collector

- [x] Import Codex session JSONL.
- [x] Detect tool calls and command outputs where possible.
- [x] Normalize into ledger events.
- [x] Add blind spot report.
- [x] Auto-detect Codex vs Claude Code transcript format on import.
- [ ] Add optional Codex hooks support.

## Phase 5: Developer CLI

- [ ] `agent-loop init`
- [x] `agent-loop verify`
- [x] `agent-loop timeline`
- [x] `agent-loop search`
- [x] `agent-loop policy check`
- [x] `agent-loop analyze approvals`

## Phase 6: Optimization Loop

- [x] Approval fatigue analyzer.
- [x] Repeated failure analyzer.
- [ ] Skill improvement recommender.
- [x] Policy improvement recommender.
- [ ] PR-ready patch generation.

## Phase 7: Enterprise Readiness

- [ ] Tamper-evident export bundle.
- [ ] S3/Object Lock export option.
- [ ] SIEM-friendly JSON export.
- [ ] Managed policy mode.
- [ ] Admin-enforced deny rule guidance.


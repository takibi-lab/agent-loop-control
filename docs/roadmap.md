# Roadmap

## Phase 0: Repository Foundation

- [ ] Pick license.
- [ ] Define event schema.
- [ ] Define policy schema.
- [ ] Add examples.
- [ ] Add contributor instructions.

## Phase 1: Ledger MVP

- [ ] Implement append-only JSONL writer.
- [ ] Implement canonical JSON hashing.
- [ ] Implement hash-chain verification.
- [ ] Add unit tests.
- [ ] Add sample ledger and verifier output.

## Phase 2: Policy MVP

- [ ] Parse `agent-policy.yaml`.
- [ ] Match command prefixes.
- [ ] Match file path patterns.
- [ ] Match tool names.
- [ ] Return allow / ask / deny decisions with rationale.
- [ ] Add policy tests.

## Phase 3: Claude Code Collector

- [ ] Build hook command that reads JSON from stdin.
- [ ] Normalize `PreToolUse`.
- [ ] Normalize `PostToolUse`.
- [ ] Normalize permission events.
- [ ] Add installer for `.claude/settings.json`.
- [ ] Add safe sample config.

## Phase 4: Codex CLI Collector

- [ ] Import Codex session JSONL.
- [ ] Detect tool calls and command outputs where possible.
- [ ] Normalize into ledger events.
- [ ] Add blind spot report.
- [ ] Add optional Codex hooks support.

## Phase 5: Developer CLI

- [ ] `agent-loop init`
- [ ] `agent-loop verify`
- [ ] `agent-loop timeline`
- [ ] `agent-loop search`
- [ ] `agent-loop policy check`
- [ ] `agent-loop analyze approvals`

## Phase 6: Optimization Loop

- [ ] Approval fatigue analyzer.
- [ ] Repeated failure analyzer.
- [ ] Skill improvement recommender.
- [ ] Policy improvement recommender.
- [ ] PR-ready patch generation.

## Phase 7: Enterprise Readiness

- [ ] Tamper-evident export bundle.
- [ ] S3/Object Lock export option.
- [ ] SIEM-friendly JSON export.
- [ ] Managed policy mode.
- [ ] Admin-enforced deny rule guidance.


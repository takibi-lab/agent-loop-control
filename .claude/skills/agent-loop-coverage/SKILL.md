---
name: agent-loop-coverage
description: >-
  Runs the agent-loop importer coverage E2E check for the agent-loop-control
  repo: builds a throwaway ledger from real local Codex and Claude Code session
  transcripts, verifies the hash chain, and reports blind_spot.declared events
  by agent and record type, flagging any record type the importer silently
  drops. Use this skill whenever someone touches the importer (importer.py,
  claude_importer.py), asks to run the agent-loop E2E test, asks whether the
  importer still works or regressed, mentions blind spots / importer coverage /
  unhandled record types, or wants to validate import before opening a PR —
  even if they do not say "coverage" explicitly.
---

# agent-loop importer coverage check

This skill validates the agent-loop importer end to end against the real Codex
and Claude Code transcripts on this machine. It exists because importer changes
are easy to regress silently: a new transcript record type simply becomes a
`blind_spot.declared` event instead of failing loudly. This check makes that
visible and turns it into a pass/fail signal.

It applies only to the **agent-loop-control** repository — run it from that repo
root so the `agent_loop` package is importable.

## When to run it

Run it after any change to `src/agent_loop/importer.py` or
`src/agent_loop/claude_importer.py`, before opening or updating a PR that
touches import, or whenever someone wants to know if the importer still covers
real sessions. The regression workflow below catches newly-dropped record types.

## How to run it

The work is done by the bundled script. Run it from the repo root via `uv` so
the project environment is active:

```bash
uv run python .claude/skills/agent-loop-coverage/scripts/coverage_check.py
```

Useful flags:

- `--policy-file PATH` — classify imported `tool.pre` events against a policy.
  Defaults to `examples/agent-policy.yaml` when that file is present.
- `--codex-limit N` / `--claude-limit N` — cap how many sessions are swept, for
  a faster smoke check.
- `--write-baseline PATH` — save this run's coverage summary as JSON.
- `--baseline PATH` — diff against a saved summary; a record type unhandled now
  but absent from the baseline is reported as a regression.
- `--keep-ledger PATH` — keep the built ledger so `agent-loop analyze PATH` can
  be run on it for the full approval-fatigue report.

The script exits non-zero when the hash chain is invalid, a session fails to
import, or a new unhandled record type appears versus a baseline. That makes it
usable as a gate.

## Regression workflow

To check whether an importer change regressed coverage, capture a baseline on
the unchanged code first, then compare after the change:

```bash
# before the importer change (e.g. on the base commit)
uv run python .claude/skills/agent-loop-coverage/scripts/coverage_check.py \
  --write-baseline /tmp/coverage-before.json

# after the change
uv run python .claude/skills/agent-loop-coverage/scripts/coverage_check.py \
  --baseline /tmp/coverage-before.json
```

## Reading the report

The report has four parts:

- **Header** — sessions imported, ledger event count, hash chain result, policy
  decision count, and any per-session import failures.
- **BLIND SPOTS BY AGENT** — blind-spot count and rate per agent. A healthy
  importer keeps these low; a spike means a record type stopped being handled.
- **UNHANDLED RECORD TYPES** — every distinct `Unsupported ... record type`
  cause, with counts. These are records the importer recognized but has no
  handler for. Empty is the goal.
- **REGRESSION CHECK** — only with `--baseline`: record types newly unhandled
  (a regression) or newly resolved since the baseline.

When the report surfaces a new unhandled record type, investigate it before
deciding what to do: locate a real example in `~/.codex/sessions` or
`~/.claude/projects`, inspect the record's structure, and decide whether it
carries agent activity (normalize it to a ledger event), is pure transcript
metadata (add it to the importer's ignore set), or is genuinely unknown (leave
it as an explicit blind spot). Mirror the existing patterns in
`importer.py` / `claude_importer.py` — `_IGNORED_*` sets, the tool/output
branches, and subtype-named blind spots.

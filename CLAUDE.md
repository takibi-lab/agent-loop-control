# CLAUDE.md

Guidance for Claude Code (and other AI agents) working in this repository.

## Project

`agent-loop-control` is a local-first safety control plane for AI coding agents.
It records agent actions in a hash-chained JSONL ledger, classifies them against
a policy, and analyzes the history for approval fatigue and improvement
candidates. See `README.md` and `docs/` for the full picture.

The package lives under `src/agent_loop/`. Python 3.11+ is required and the
project is managed with `uv`.

## Build, test, lint

```bash
uv sync                       # install dependencies
uv run agent-loop --help      # run the CLI
uv run pytest -q              # run the test suite (keep it green)
uv run ruff check src tests   # lint (ruff selects F and I)
```

## Importer coverage E2E

Any change to `src/agent_loop/importer.py` or `src/agent_loop/claude_importer.py`
must be validated against real local transcripts before opening a PR:

```bash
uv run python .claude/skills/agent-loop-coverage/scripts/coverage_check.py
```

The check builds a throwaway ledger from local Codex and Claude Code sessions,
verifies the hash chain, and reports `blind_spot.declared` events by record
type. A new unhandled record type is a regression.

## Conventions

- Keep changes small and reviewable; match the surrounding code style, type
  annotations, and docstring density.
- Prefer local, network-free tests. Do not store secrets in fixtures.
- When adding a collector, include sample input and normalized output.
- When adding a policy feature, include allow / ask / deny test cases.
- When adding an analyzer, document its false positives and blind spots.
- Do not change the `event_type` enum in `schemas/` without updating the schema.

## Tool selection

This repository's own analyzer flags shell commands that duplicate a dedicated
tool — practice what the tool measures:

- Use `Glob` / `Grep` / `Read` to find and read files. Reach for `Bash` with
  `find`, `ls`, `cat`, `grep`, `head`, `tail`, or `sed` only when no dedicated
  tool fits (e.g. piping into another command).
- Avoid `cd` in compound `Bash` commands; it can trigger a permission prompt.
  Pass absolute paths or use a tool's `path` argument instead.
- Reserve `Bash` for what genuinely needs a shell: `git`, `uv`, `gh`, build
  steps, and running the CLI.

Lower-noise tool use means fewer approval prompts and a cleaner ledger — the
outcome this project exists to enable.

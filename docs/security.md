# Security Controls

## Secret Detection

This repository uses Gitleaks in three layers:

1. `.gitleaks.toml` extends the default Gitleaks rules.
2. `.github/workflows/gitleaks.yml` runs on pull requests and pushes to `main`.
3. `.pre-commit-config.yaml` lets contributors run the same scan locally.

## Ignored Local State

The `.gitignore` excludes:

- Credential files.
- Database files and backups.
- Local AI agent state such as `.claude/`, `.codex/`, `.agent/`, and `.agents/`.
- Legacy or scratch local audit directories such as `.agent-ledger/` and
  `.agent-audit/`.

The recommended ledger location is outside repositories, normally
`~/.agent-loop/ledger.jsonl`. Keeping one global JSONL ledger preserves a single
hash chain across repositories and reduces accidental commit risk. Repo-local
ledger files should be treated as disposable test data or legacy state, not as the
normal audit record.

## Ledger Verification

`agent-loop verify` validates the full hash chain in the ledger file. Repo filters
on commands such as `timeline`, `search`, and `analyze` narrow views and reports
only; they do not verify a smaller per-repository chain.

## Branch Protection Policy

The intended GitHub rule for `main` is:

- No direct pushes to `main`.
- Pull requests are required.
- At least one approval is required.
- CODEOWNER review is required.
- Stale approvals are dismissed after new commits.
- The latest reviewable push must be approved by someone other than the pusher.
- Force pushes and branch deletion are disabled.

`CODEOWNERS` currently assigns all files to `@takibi-lab`.

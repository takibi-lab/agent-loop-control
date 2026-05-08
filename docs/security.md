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
- Local audit ledgers such as `.agent-ledger/` and `.agent-audit/`.

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


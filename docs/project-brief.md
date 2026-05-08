# Project Brief

## Working Name

Agent Loop Control

## One-Line Description

Local-first safety, audit, and optimization layer for autonomous coding agents.

## Problem

AI coding agents are becoming capable enough to work autonomously, but real users face two problems:

1. Approval fatigue: too many prompts make humans approve without careful review.
2. Missing evidence: when agents run locally, teams often cannot reliably reconstruct what happened, why it happened, and which approval or policy allowed it.

This is especially hard in environments where provider-side logs, such as Bedrock model invocation logs, are unavailable to the user.

## Product Goal

Create a local and enterprise-usable system that:

- Runs agents safely with minimal manual approval.
- Records actions, decisions, diffs, and verification results locally.
- Uses policy-as-code to classify agent actions as allow / ask / deny.
- Supports Claude Code and Codex CLI first.
- Uses historical execution data to improve Skills, agents, hooks, MCP permissions, and policies.

## Target Users

- Individual developers using Claude Code or Codex CLI.
- Small teams adopting autonomous coding agents.
- Enterprise platform/security teams that need evidence, reviewability, and controlled autonomy.
- AI operations teams designing reusable Skills and agent workflows.

## Differentiation

Existing tools tend to focus on one of these areas:

- Session search and replay.
- LLM app observability.
- Compliance logging.
- Terminal recording.

Agent Loop Control should combine:

- Local-first audit ledger.
- Policy-based autonomy.
- Approval fatigue reduction.
- Diff-centric provenance.
- Agentic loop optimization.

## Design Principles

- Local-first by default.
- Provider-log independent.
- Policy as code.
- Least privilege.
- Tamper-evident records.
- Human approval only where it has real security value.
- Optimization proposals should be reviewable before they change agent behavior.

## Success Criteria

MVP success means a user can:

- Configure a policy once.
- Run Claude Code or Codex CLI with fewer interruptions.
- Search what commands ran and what files changed.
- Verify that the ledger was not edited after the fact.
- See which approvals were high-value versus noisy.
- Generate a PR or patch suggesting improvements to agent policy or Skills.


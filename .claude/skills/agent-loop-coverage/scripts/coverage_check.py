#!/usr/bin/env python3
"""Importer coverage E2E check for agent-loop-control.

Builds a throwaway ledger from real local Codex and Claude Code session
transcripts, verifies the hash chain, and reports blind-spot coverage by
agent and by record type. Intended as a regression check after importer
changes: run it before and after a change (saving a baseline), and confirm
no new record types started being silently dropped.

Run from the repo root via the project environment so that `agent_loop` is
importable:

    uv run python .claude/skills/agent-loop-coverage/scripts/coverage_check.py

Exit code is non-zero when the hash chain is invalid, when a session fails to
import, or when a baseline is supplied and a new unhandled record type appears.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys
import tempfile
from pathlib import Path


def discover_sessions(codex_limit: int | None, claude_limit: int | None) -> tuple[list[str], list[str]]:
    """Find local Codex and Claude Code session transcripts."""
    codex = sorted(glob.glob(os.path.expanduser("~/.codex/sessions/**/*.jsonl"), recursive=True))
    claude = sorted(glob.glob(os.path.expanduser("~/.claude/projects/*/*.jsonl")))
    if codex_limit is not None:
        codex = codex[:codex_limit]
    if claude_limit is not None:
        claude = claude[:claude_limit]
    return codex, claude


def build_ledger(sessions: list[str], ledger_path: str, policy_file: str | None) -> tuple[int, list[tuple[str, str]]]:
    """Import every session into one ledger; return (imported, failures)."""
    from agent_loop.importer import import_session

    imported = 0
    failed: list[tuple[str, str]] = []
    for src in sessions:
        try:
            import_session(src, ledger_path=ledger_path, policy_path=policy_file)
            imported += 1
        except Exception as exc:  # noqa: BLE001 - report the failure, keep sweeping
            failed.append((src, repr(exc)))
    return imported, failed


def summarize(ledger_path: str) -> dict:
    """Tally event types, per-agent blind spots, and blind-spot reasons."""
    event_types: collections.Counter = collections.Counter()
    agent_total: collections.Counter = collections.Counter()
    agent_blind: collections.Counter = collections.Counter()
    reasons: collections.Counter = collections.Counter()
    policy_decisions = 0

    for line in Path(ledger_path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        event = json.loads(line)
        etype = event.get("event_type")
        agent = (event.get("source") or {}).get("agent") or "unknown"
        event_types[etype] += 1
        agent_total[agent] += 1
        if isinstance(event.get("policy"), dict) and event["policy"].get("decision"):
            policy_decisions += 1
        if etype == "blind_spot.declared":
            agent_blind[agent] += 1
            spots = event.get("blind_spots") or []
            if spots:
                reasons[str(spots[0])] += 1

    # The first blind-spot string names the specific cause; an "Unsupported ..."
    # cause means the importer recognized the record but has no handler for it.
    unhandled = {r: c for r, c in reasons.items() if r.startswith("Unsupported")}
    return {
        "event_types": dict(event_types),
        "agent_total": dict(agent_total),
        "agent_blind": dict(agent_blind),
        "unhandled_types": unhandled,
        "policy_decisions": policy_decisions,
        "total_events": sum(event_types.values()),
    }


def render_report(summary: dict, imported: int, codex_n: int, claude_n: int,
                   failures: list, chain_ok: bool, baseline: dict | None) -> tuple[str, bool]:
    """Build the human-readable report; return (text, regression_detected)."""
    lines = ["=" * 60, "AGENT-LOOP IMPORTER COVERAGE CHECK", "=" * 60]
    lines.append(f"Sessions imported:  {imported}  (codex: {codex_n}, claude-code: {claude_n})")
    lines.append(f"Ledger events:      {summary['total_events']}")
    lines.append(f"Hash chain:         {'OK' if chain_ok else 'FAILED'}")
    lines.append(f"Policy decisions:   {summary['policy_decisions']}")
    if failures:
        lines.append(f"Import failures:    {len(failures)}")
        for src, err in failures[:5]:
            lines.append(f"  - {os.path.basename(src)}: {err}")

    lines.append("")
    lines.append("BLIND SPOTS BY AGENT")
    for agent in sorted(summary["agent_total"]):
        total = summary["agent_total"][agent]
        blind = summary["agent_blind"].get(agent, 0)
        pct = (100 * blind / total) if total else 0.0
        lines.append(f"  {agent:14} {blind:5} / {total:6}  ({pct:.2f}%)")

    lines.append("")
    unhandled = summary["unhandled_types"]
    lines.append(f"UNHANDLED RECORD TYPES ({len(unhandled)} distinct)")
    if unhandled:
        for reason, count in sorted(unhandled.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {count:5}x  {reason}")
    else:
        lines.append("  (none — every record type is handled or intentionally ignored)")

    regression = not chain_ok or bool(failures)
    if baseline is not None:
        lines.append("")
        lines.append("REGRESSION CHECK vs baseline")
        base_unhandled = baseline.get("unhandled_types", {})
        new_types = sorted(set(unhandled) - set(base_unhandled))
        gone_types = sorted(set(base_unhandled) - set(unhandled))
        if new_types:
            regression = True
            lines.append("  NEW unhandled record types (importer regression):")
            for reason in new_types:
                lines.append(f"    + {reason}  ({unhandled[reason]}x)")
        if gone_types:
            lines.append("  Resolved since baseline:")
            for reason in gone_types:
                lines.append(f"    - {reason}")
        if not new_types and not gone_types:
            lines.append("  No change in unhandled record types.")

    lines.append("")
    lines.append("RESULT: " + ("REGRESSION DETECTED" if regression else "OK"))
    return "\n".join(lines), regression


def main() -> int:
    parser = argparse.ArgumentParser(description="agent-loop importer coverage E2E check")
    parser.add_argument("--policy-file", default=None,
                        help="Policy YAML for classifying imported tool.pre events "
                             "(defaults to examples/agent-policy.yaml when present).")
    parser.add_argument("--codex-limit", type=int, default=None, help="Cap on Codex sessions.")
    parser.add_argument("--claude-limit", type=int, default=None, help="Cap on Claude Code sessions.")
    parser.add_argument("--baseline", default=None,
                        help="Path to a prior coverage JSON; new unhandled types vs it count as a regression.")
    parser.add_argument("--write-baseline", default=None,
                        help="Write this run's coverage summary as JSON to this path.")
    parser.add_argument("--keep-ledger", default=None,
                        help="Keep the built ledger at this path (e.g. to run `agent-loop analyze` on it).")
    args = parser.parse_args()

    try:
        from agent_loop.verifier import verify_ledger
    except ImportError:
        print("ERROR: `agent_loop` is not importable. Run from the agent-loop-control "
              "repo root via `uv run python ...`.", file=sys.stderr)
        return 2

    policy_file = args.policy_file
    if policy_file is None and Path("examples/agent-policy.yaml").is_file():
        policy_file = "examples/agent-policy.yaml"

    codex, claude = discover_sessions(args.codex_limit, args.claude_limit)
    sessions = codex + claude
    if not sessions:
        print("No local Codex or Claude Code sessions found under ~/.codex or ~/.claude.",
              file=sys.stderr)
        return 2

    ledger_path = args.keep_ledger or os.path.join(tempfile.mkdtemp(), "coverage-ledger.jsonl")
    imported, failures = build_ledger(sessions, ledger_path, policy_file)
    chain_ok = bool(verify_ledger(ledger_path).get("valid")) if Path(ledger_path).exists() else False
    summary = summarize(ledger_path) if Path(ledger_path).exists() else {
        "event_types": {}, "agent_total": {}, "agent_blind": {},
        "unhandled_types": {}, "policy_decisions": 0, "total_events": 0,
    }

    baseline = None
    if args.baseline and Path(args.baseline).is_file():
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))

    report, regression = render_report(
        summary, imported, len(codex), len(claude), failures, chain_ok, baseline
    )
    print(report)

    if args.write_baseline:
        Path(args.write_baseline).write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                             encoding="utf-8")
        print(f"\nBaseline written to {args.write_baseline}")
    if args.keep_ledger:
        print(f"Ledger kept at {ledger_path} — run `agent-loop analyze {ledger_path}` for the full report.")

    return 1 if regression else 0


if __name__ == "__main__":
    raise SystemExit(main())

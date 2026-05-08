"""Command-line entry point for agent-loop."""

from __future__ import annotations

import argparse
import json
import sys

from .analyze import approval_report
from .collectors.claude import collect_stdin
from .diff_snapshot import snapshot
from .importers.codex import import_jsonl
from .policy import classify, load_policy
from .verifier import verify_ledger
from .views import search, timeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-loop")
    sub = parser.add_subparsers(dest="command")

    verify = sub.add_parser("verify")
    verify.add_argument("ledger")

    policy = sub.add_parser("policy")
    policy_sub = policy.add_subparsers(dest="policy_command")
    check = policy_sub.add_parser("check")
    check.add_argument("--policy", default="examples/agent-policy.yaml")
    check.add_argument("--tool")
    check.add_argument("--command", dest="action_command")
    check.add_argument("--path", action="append", default=[])

    timeline_cmd = sub.add_parser("timeline")
    timeline_cmd.add_argument("ledger")

    search_cmd = sub.add_parser("search")
    search_cmd.add_argument("ledger")
    search_cmd.add_argument("--event-type")
    search_cmd.add_argument("--policy-decision")
    search_cmd.add_argument("--command", dest="action_command")
    search_cmd.add_argument("--path")

    analyze = sub.add_parser("analyze")
    analyze_sub = analyze.add_subparsers(dest="analyze_command")
    approvals = analyze_sub.add_parser("approvals")
    approvals.add_argument("ledger")

    collect = sub.add_parser("collect")
    collect_sub = collect.add_subparsers(dest="collector")
    claude = collect_sub.add_parser("claude-hook")
    claude.add_argument("--ledger", required=True)
    claude.add_argument("--policy")

    codex = sub.add_parser("import-codex")
    codex.add_argument("session_jsonl")
    codex.add_argument("--ledger")

    diff = sub.add_parser("diff-snapshot")
    diff.add_argument("--repo", default=".")
    diff.add_argument("--ledger")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "verify":
        result = verify_ledger(args.ledger)
        if result.valid:
            print(f"OK: verified {result.checked} event(s)")
            return 0
        print(f"FAILED: {result.reason}")
        if result.line:
            print(f"line: {result.line}")
        if result.event_id:
            print(f"event_id: {result.event_id}")
        return 1

    if args.command == "policy" and args.policy_command == "check":
        decision = classify(load_policy(args.policy), tool=args.tool, command=args.action_command, paths=args.path)
        print(json.dumps(decision.as_event_policy(), sort_keys=True))
        return 0

    if args.command == "timeline":
        print("\n".join(timeline(args.ledger)))
        return 0

    if args.command == "search":
        print("\n".join(search(args.ledger, args.event_type, args.policy_decision, args.action_command, args.path)))
        return 0

    if args.command == "analyze" and args.analyze_command == "approvals":
        print("\n".join(approval_report(args.ledger)))
        return 0

    if args.command == "collect" and args.collector == "claude-hook":
        print(json.dumps(collect_stdin(args.ledger, args.policy), sort_keys=True))
        return 0

    if args.command == "import-codex":
        events = import_jsonl(args.session_jsonl, args.ledger)
        print(json.dumps(events, sort_keys=True))
        return 0

    if args.command == "diff-snapshot":
        print(json.dumps(snapshot(args.repo, args.ledger), sort_keys=True))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

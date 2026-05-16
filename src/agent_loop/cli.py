import click

from agent_loop import __version__


def _repo_filter_from_options(repo, repo_root):
    from agent_loop.repo_context import build_repo_filter

    try:
        return build_repo_filter(repo=repo, repo_root=repo_root)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc


@click.group()
@click.version_option(version=__version__, package_name="agent-loop-control")
def main():
    """Local-first safety control plane for AI coding agents."""


@main.command()
@click.argument("ledger", default="agent-ledger.jsonl", required=False)
@click.option("--repo", default=None, help="Show how many verified events match this repo path or remote.")
@click.option("--repo-root", default=None, help="Show how many verified events match this repo root path.")
def verify(ledger, repo, repo_root):
    """Verify hash-chain integrity of a ledger JSONL file."""
    from agent_loop.ledger_reader import filter_events, load_events
    from agent_loop.verifier import verify_ledger

    result = verify_ledger(ledger, fail_fast=False)
    if result["valid"]:
        repo_filter = _repo_filter_from_options(repo, repo_root)
        if repo_filter:
            matched = filter_events(load_events(ledger), repo_filter=repo_filter)
            click.echo(
                f"OK: {result['event_count']} events verified; "
                f"{len(matched)} events match repo filter"
            )
        else:
            click.echo(f"OK: {result['event_count']} events verified")
    else:
        click.echo("FAIL: ledger integrity check failed", err=True)
        for error in result.get("errors") or [result["reason"]]:
            click.echo(f"- {error}", err=True)
        raise SystemExit(1)


@main.group()
def policy():
    """Policy management commands."""


@policy.command("check")
@click.argument("policy_file", default="agent-policy.yaml", required=False)
def policy_check(policy_file):
    """Validate and display a policy YAML file."""
    from agent_loop.policy import (
        PolicyValidationError,
        load_policy,
        load_redaction_patterns,
    )

    try:
        pol = load_policy(policy_file)
        patterns = load_redaction_patterns(pol)
    except PolicyValidationError as exc:
        click.echo(f"FAIL: policy '{policy_file}' is invalid", err=True)
        for error in exc.errors:
            click.echo(f"- {error}", err=True)
        raise SystemExit(1) from exc

    click.echo(f"OK: policy '{pol['name']}' loaded")
    click.echo(f"Rules: {len(pol['rules'])}")
    click.echo(f"Redaction patterns: {len(patterns)}")
    click.echo(f"Default decision: {pol['defaults']['decision']}")


@policy.command("classify")
@click.option("--tool", default=None, help="Tool name to classify.")
@click.option("--command", default=None, help="Command string to classify.")
@click.option("--path", default=None, help="File path to classify.")
@click.option("--policy-file", default="agent-policy.yaml", help="Policy file path.")
def policy_classify(tool, command, path, policy_file):
    """Classify an action against a policy and print the decision."""
    from agent_loop.policy import classify_action, load_policy

    if not any([tool, command, path]):
        raise click.UsageError("Provide at least one of --tool, --command, or --path.")

    pol = load_policy(policy_file)
    result = classify_action(pol, tool=tool, command=command, path=path)
    click.echo(f"decision: {result['decision']}")
    click.echo(f"risk:     {result['risk']}")
    click.echo(f"rule_id:  {result['rule_id']}")
    click.echo(f"rationale: {result['rationale']}")


@main.command()
@click.argument("ledger", default="agent-ledger.jsonl", required=False)
@click.option("--limit", default=50, show_default=True, help="Maximum events to show.")
@click.option("--repo", default=None, help="Filter by repo path or normalized remote.")
@click.option("--repo-root", default=None, help="Filter by repo root path.")
def timeline(ledger, limit, repo, repo_root):
    """Show ordered event summaries from a ledger JSONL file."""
    from agent_loop.timeline import print_timeline

    print_timeline(ledger, limit=limit, repo_filter=_repo_filter_from_options(repo, repo_root))


@main.command()
@click.argument("ledger", default="agent-ledger.jsonl", required=False)
@click.option("--type", "event_type", default=None, help="Filter by event type.")
@click.option("--decision", default=None, help="Filter by policy decision.")
@click.option("--command", default=None, help="Filter by command text substring.")
@click.option("--file-path", default=None, help="Filter by file path substring.")
@click.option("--repo", default=None, help="Filter by repo path or normalized remote.")
@click.option("--repo-root", default=None, help="Filter by repo root path.")
def search(ledger, event_type, decision, command, file_path, repo, repo_root):
    """Search ledger events by type, decision, command, or file path."""
    from agent_loop.timeline import print_search

    print_search(
        ledger,
        event_type=event_type,
        decision=decision,
        command=command,
        file_path=file_path,
        repo_filter=_repo_filter_from_options(repo, repo_root),
    )


@main.command()
@click.argument("ledger", default="agent-ledger.jsonl", required=False)
@click.option("--repo", default=None, help="Filter by repo path or normalized remote.")
@click.option("--repo-root", default=None, help="Filter by repo root path.")
@click.option("--group-by", type=click.Choice(["repo"]), default=None, help="Group the analysis.")
def analyze(ledger, repo, repo_root, group_by):
    """Analyze approval fatigue and suggest policy improvements."""
    from agent_loop.analyzer import analyze_approvals

    report = analyze_approvals(
        ledger,
        repo_filter=_repo_filter_from_options(repo, repo_root),
        group_by=group_by,
    )
    click.echo(report)


@main.group()
def hook():
    """Claude Code hook integration commands."""


@hook.command("collect")
@click.option("--ledger", default="agent-ledger.jsonl", help="Ledger file path.")
@click.option("--policy-file", default=None, help="Optional policy file for decisions.")
def hook_collect(ledger, policy_file):
    """Read a Claude Code hook event from stdin and append to ledger."""
    import sys

    from agent_loop.collector import collect_hook_event

    data = sys.stdin.read()
    collect_hook_event(data, ledger_path=ledger, policy_path=policy_file)


@main.command("import")
@click.argument("source_file")
@click.option("--ledger", default="agent-ledger.jsonl", help="Ledger file path.")
@click.option("--agent", default=None, help="Source agent identifier (defaults to the detected format).")
@click.option("--cwd", default=None, help="Fallback working directory for records without cwd.")
@click.option(
    "--format",
    "session_format",
    type=click.Choice(["auto", "codex", "claude-code"]),
    default="auto",
    show_default=True,
    help="Session transcript format. 'auto' detects Codex vs Claude Code.",
)
@click.option(
    "--policy-file",
    default=None,
    help="Optional policy file used to classify imported tool.pre events.",
)
def import_session(source_file, ledger, agent, cwd, session_format, policy_file):
    """Import a Codex CLI or Claude Code session transcript into the ledger."""
    from agent_loop.importer import import_session as run_import

    count = run_import(
        source_file,
        ledger_path=ledger,
        agent=agent,
        cwd=cwd,
        session_format=session_format,
        policy_path=policy_file,
    )
    click.echo(f"Imported {count} events from {source_file}")


@main.command("snapshot")
@click.option("--ledger", default="agent-ledger.jsonl", help="Ledger file path.")
@click.option("--repo", default=".", help="Repository root directory.")
def snapshot(ledger, repo):
    """Capture a Git diff snapshot and append to ledger."""
    from agent_loop.snapshotter import take_snapshot

    event_id = take_snapshot(ledger_path=ledger, repo_root=repo)
    click.echo(f"Snapshot recorded: {event_id}")

import click


@click.group()
@click.version_option(package_name="agent-loop-control")
def main():
    """Local-first safety control plane for AI coding agents."""


@main.command()
@click.argument("ledger", default="agent-ledger.jsonl", required=False)
def verify(ledger):
    """Verify hash-chain integrity of a ledger JSONL file."""
    from agent_loop.verifier import verify_ledger

    result = verify_ledger(ledger)
    if result["valid"]:
        click.echo(f"OK: {result['event_count']} events verified")
    else:
        click.echo(f"FAIL: {result['reason']}", err=True)
        raise SystemExit(1)


@main.group()
def policy():
    """Policy management commands."""


@policy.command("check")
@click.argument("policy_file", default="agent-policy.yaml", required=False)
def policy_check(policy_file):
    """Validate and display a policy YAML file."""
    from agent_loop.policy import load_policy

    pol = load_policy(policy_file)
    click.echo(f"OK: policy '{pol['name']}' loaded with {len(pol['rules'])} rules")
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
def timeline(ledger, limit):
    """Show ordered event summaries from a ledger JSONL file."""
    from agent_loop.timeline import print_timeline

    print_timeline(ledger, limit=limit)


@main.command()
@click.argument("ledger", default="agent-ledger.jsonl", required=False)
@click.option("--type", "event_type", default=None, help="Filter by event type.")
@click.option("--decision", default=None, help="Filter by policy decision.")
@click.option("--command", default=None, help="Filter by command text substring.")
@click.option("--file-path", default=None, help="Filter by file path substring.")
def search(ledger, event_type, decision, command, file_path):
    """Search ledger events by type, decision, command, or file path."""
    from agent_loop.timeline import print_search

    print_search(
        ledger,
        event_type=event_type,
        decision=decision,
        command=command,
        file_path=file_path,
    )


@main.command()
@click.argument("ledger", default="agent-ledger.jsonl", required=False)
def analyze(ledger):
    """Analyze approval fatigue and suggest policy improvements."""
    from agent_loop.analyzer import analyze_approvals

    report = analyze_approvals(ledger)
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
@click.option("--agent", default="codex-cli", help="Source agent identifier.")
def import_session(source_file, ledger, agent):
    """Import a Codex CLI session JSONL file into the ledger."""
    from agent_loop.importer import import_codex_session

    count = import_codex_session(source_file, ledger_path=ledger, agent=agent)
    click.echo(f"Imported {count} events from {source_file}")


@main.command("snapshot")
@click.option("--ledger", default="agent-ledger.jsonl", help="Ledger file path.")
@click.option("--repo", default=".", help="Repository root directory.")
def snapshot(ledger, repo):
    """Capture a Git diff snapshot and append to ledger."""
    from agent_loop.snapshotter import take_snapshot

    event_id = take_snapshot(ledger_path=ledger, repo_root=repo)
    click.echo(f"Snapshot recorded: {event_id}")

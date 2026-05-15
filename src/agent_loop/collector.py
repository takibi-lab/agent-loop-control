"""Claude Code hook collector.

Reads hook JSON from stdin, normalizes to ledger events, applies policy decisions,
redacts sensitive values, and appends to the ledger.
"""

import json
from pathlib import Path
from typing import Any

from agent_loop.ledger import append_event, build_event
from agent_loop.repo_context import normalize_path, resolve_repo_context

_HOOK_TO_EVENT_TYPE = {
    "UserPromptSubmit": "prompt.submitted",
    "PreToolUse": "tool.pre",
    "PostToolUse": "tool.post",
    "PostToolUseFailure": "tool.error",
    "PermissionRequest": "approval.requested",
    "PermissionDenied": "approval.resolved",
    "SessionStart": "session.start",
    "SessionEnd": "session.end",
}

_BLIND_SPOTS = [
    "Hidden model reasoning is not captured.",
    "Provider-side request/response logs are unavailable.",
    "Some terminal output may be missing if the agent bypassed hooks.",
]

_PATH_KEYS = {"file_path", "path", "paths", "target_file", "target_path", "notebook_path"}
_COMMAND_KEYS = {"command", "commands", "args", "argv"}
_DECISION_PRECEDENCE = {"deny": 0, "ask": 1, "allow": 2}


def _stringify_command(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [str(part) for part in value if part is not None]
        return " ".join(parts) if parts else None
    return str(value) if value is not None else None


def _collect_policy_values(value: Any, *, keys: set[str], join_lists: bool = False) -> list[str]:
    values: list[str] = []

    def walk(item: Any, key: str | None = None) -> None:
        if isinstance(item, dict):
            for child_key, child_value in item.items():
                walk(child_value, str(child_key))
            return
        if isinstance(item, list):
            if key in keys:
                if join_lists:
                    text = _stringify_command(item)
                    if text:
                        values.append(text)
                else:
                    for child in item:
                        if isinstance(child, dict | list):
                            walk(child, key)
                        elif child is not None:
                            values.append(str(child))
            else:
                for child in item:
                    walk(child, key)
            return
        if key in keys and item is not None:
            values.append(str(item))

    walk(value)
    return list(dict.fromkeys(values))


def _classify_event(policy: dict, event: dict) -> dict[str, Any]:
    from agent_loop.policy import classify_action

    tool = event.get("tool", {}) if isinstance(event.get("tool"), dict) else {}
    tool_name = tool.get("name") if isinstance(tool, dict) else None
    tool_input = tool.get("input_full") if isinstance(tool, dict) else None

    commands = []
    if isinstance(tool, dict):
        commands.extend(
            cmd
            for cmd in [
                _stringify_command(tool.get("command")),
                _stringify_command(tool.get("input_summary")),
            ]
            if cmd
        )
    commands.extend(_collect_policy_values(tool_input, keys=_COMMAND_KEYS, join_lists=True))

    paths = _collect_policy_values(tool_input, keys=_PATH_KEYS)

    candidates: list[dict[str, Any]] = []
    for command in commands or [None]:
        for path in paths or [None]:
            candidates.append(classify_action(policy, tool=tool_name, command=command, path=path))

    return min(candidates, key=lambda result: _DECISION_PRECEDENCE.get(result["decision"], 1))


def _normalize_hook(hook_data: dict) -> dict[str, Any] | None:
    """Normalize a Claude Code hook payload to a ledger event dict (without hashes)."""
    hook_type = hook_data.get("hook_type") or hook_data.get("hookType") or hook_data.get("type")
    event_type = _HOOK_TO_EVENT_TYPE.get(hook_type)

    session_id = hook_data.get("session_id") or hook_data.get("sessionId")
    cwd = hook_data.get("cwd")

    extra: dict[str, Any] = {}
    if cwd:
        repo = resolve_repo_context(cwd)
        if repo is not None:
            extra["repo"] = repo
        cwd = normalize_path(cwd)

    if event_type in ("tool.pre", "tool.post", "tool.error"):
        tool_data: dict[str, Any] = {}
        tool_name = (
            hook_data.get("tool_name")
            or hook_data.get("toolName")
            or hook_data.get("tool", {}).get("name")
        )
        if tool_name:
            tool_data["name"] = tool_name

        tool_input = hook_data.get("tool_input") or hook_data.get("toolInput")
        if tool_input:
            if isinstance(tool_input, dict):
                tool_data["input_full"] = tool_input
                cmd = _stringify_command(tool_input.get("command"))
                if cmd:
                    tool_data["command"] = cmd
                    tool_data["input_summary"] = cmd[:200]
                else:
                    tool_data["input_summary"] = json.dumps(tool_input, ensure_ascii=False)[:200]
            else:
                tool_data["input_summary"] = str(tool_input)[:200]

        if event_type == "tool.post":
            tool_data["success"] = True
            exit_code = hook_data.get("exit_code") or hook_data.get("exitCode")
            if exit_code is not None:
                tool_data["exit_code"] = exit_code
        elif event_type == "tool.error":
            tool_data["success"] = False

        if tool_data:
            extra["tool"] = tool_data

    elif event_type == "prompt.submitted":
        prompt = hook_data.get("prompt") or hook_data.get("message") or ""
        if prompt:
            extra["prompt"] = prompt

    elif event_type == "approval.requested":
        extra["approval"] = {"status": "requested", "reason": hook_data.get("reason", "")}
    elif event_type == "approval.resolved":
        extra["approval"] = {
            "status": "denied",
            "reason": hook_data.get("reason", ""),
        }

    if event_type is None:
        event_type = "blind_spot.declared"
        extra["blind_spots"] = [
            f"Unsupported hook type: {hook_type!r}",
            *_BLIND_SPOTS,
        ]

    return build_event(
        event_type,
        "claude-code",
        session_id=session_id,
        cwd=cwd,
        extra=extra,
    )


def collect_hook_event(
    raw_json: str,
    *,
    ledger_path: str | Path = "agent-ledger.jsonl",
    policy_path: str | Path | None = None,
) -> dict[str, Any]:
    """Parse raw hook JSON, optionally apply policy, redact, and append to ledger."""
    try:
        hook_data = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        event = build_event(
            "blind_spot.declared",
            "claude-code",
            extra={"blind_spots": [f"Malformed hook JSON: {exc}", *_BLIND_SPOTS]},
        )
        return append_event(ledger_path, event)

    event = _normalize_hook(hook_data)

    if policy_path:
        from agent_loop.policy import (
            load_policy,
            load_redaction_patterns,
            redact_event,
        )

        policy = load_policy(policy_path)
        patterns = load_redaction_patterns(policy)

        decision = _classify_event(policy, event)
        event["policy"] = {
            "decision": decision["decision"],
            "risk": decision["risk"],
            "rule_id": decision["rule_id"],
            "rationale": decision["rationale"],
        }

        if patterns:
            event = redact_event(event, patterns)

    return append_event(ledger_path, event)

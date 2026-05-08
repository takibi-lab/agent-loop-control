"""Claude Code hook collector.

Reads hook JSON from stdin, normalizes to ledger events, applies policy decisions,
redacts sensitive values, and appends to the ledger.
"""

import json
from pathlib import Path
from typing import Any

from agent_loop.ledger import append_event, build_event

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


def _normalize_hook(hook_data: dict) -> dict[str, Any] | None:
    """Normalize a Claude Code hook payload to a ledger event dict (without hashes)."""
    hook_type = hook_data.get("hook_type") or hook_data.get("hookType") or hook_data.get("type")
    event_type = _HOOK_TO_EVENT_TYPE.get(hook_type)

    session_id = hook_data.get("session_id") or hook_data.get("sessionId")
    cwd = hook_data.get("cwd")

    extra: dict[str, Any] = {}

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
                cmd = tool_input.get("command")
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
            classify_action,
            load_policy,
            load_redaction_patterns,
            redact_event,
        )

        policy = load_policy(policy_path)
        patterns = load_redaction_patterns(policy)

        tool_name = event.get("tool", {}).get("name") if isinstance(event.get("tool"), dict) else None
        command = event.get("tool", {}).get("command") if isinstance(event.get("tool"), dict) else None
        tool_input = event.get("tool", {}).get("input_full") if isinstance(event.get("tool"), dict) else None
        path = tool_input.get("file_path") if isinstance(tool_input, dict) else None

        decision = classify_action(policy, tool=tool_name, command=command, path=path)
        event["policy"] = {
            "decision": decision["decision"],
            "risk": decision["risk"],
            "rule_id": decision["rule_id"],
            "rationale": decision["rationale"],
        }

        if patterns:
            event = redact_event(event, patterns)

    return append_event(ledger_path, event)

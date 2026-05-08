"""Claude Code hook collector."""

from __future__ import annotations

import json
import sys
from typing import Any, Dict

from ..ledger import append_event
from ..policy import classify, load_policy
from ..redaction import redact_event


EVENT_MAP = {
    "UserPromptSubmit": "prompt.submitted",
    "PreToolUse": "tool.pre",
    "PostToolUse": "tool.post",
    "PostToolUseFailure": "tool.error",
    "PermissionRequest": "approval.requested",
    "PermissionDenied": "approval.resolved",
    "SessionStart": "session.start",
    "SessionEnd": "session.end",
}


def normalize_hook(payload: Dict[str, Any], policy: Dict[str, Any] | None = None) -> Dict[str, Any]:
    hook_event = payload.get("hook_event_name") or payload.get("event") or payload.get("type") or "unknown"
    event_type = EVENT_MAP.get(hook_event, "blind_spot.declared")
    tool_name = payload.get("tool_name") or payload.get("tool", {}).get("name")
    tool_input = payload.get("tool_input") or payload.get("input") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    paths = _paths_from_input(tool_input)
    event: Dict[str, Any] = {
        "source": {"agent": "claude-code", "collector": "claude-hook"},
        "session": {"session_id": payload.get("session_id"), "cwd": payload.get("cwd")},
        "event_type": event_type,
    }
    if tool_name or command:
        event["tool"] = {"name": tool_name or "unknown"}
        if command:
            event["tool"]["command"] = command
    if paths:
        event["files"] = [{"path": path, "operation": "unknown"} for path in paths]
    if event_type == "approval.requested":
        event["approval"] = {"status": "requested", "reason": payload.get("reason")}
    if hook_event == "PermissionDenied":
        event["approval"] = {"status": "denied", "reason": payload.get("reason")}
    if event_type == "blind_spot.declared":
        event["blind_spots"] = [f"Unsupported Claude hook event: {hook_event}"]
    if policy:
        event["policy"] = classify(policy, tool=tool_name, command=command, paths=paths).as_event_policy()
    return event


def collect_stdin(ledger_path: str, policy_path: str | None = None) -> Dict[str, Any]:
    payload = json.load(sys.stdin)
    policy = load_policy(policy_path) if policy_path else None
    event = normalize_hook(payload, policy)
    if policy:
        event = redact_event(event, policy)
    return append_event(ledger_path, event)


def _paths_from_input(tool_input: Any) -> list[str]:
    if not isinstance(tool_input, dict):
        return []
    candidates = []
    for key in ("file_path", "path", "paths"):
        value = tool_input.get(key)
        if isinstance(value, str):
            candidates.append(value)
        elif isinstance(value, list):
            candidates.extend(str(item) for item in value)
    return candidates

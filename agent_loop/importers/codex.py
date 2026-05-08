"""Codex CLI session JSONL importer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ..ledger import append_event


def normalize_record(record: Dict[str, Any]) -> Dict[str, Any]:
    record_type = record.get("type") or record.get("event_type") or record.get("kind")
    tool_name = record.get("tool_name") or (record.get("tool") or {}).get("name")
    command = record.get("command") or (record.get("arguments") or {}).get("cmd")
    event: Dict[str, Any] = {
        "source": {"agent": "codex-cli", "collector": "codex-session-importer"},
        "session": {"session_id": record.get("session_id")},
    }
    if record_type in {"tool_call", "tool.pre", "function_call"} and (tool_name or command):
        event["event_type"] = "tool.pre"
        event["tool"] = {"name": tool_name or "shell"}
        if command:
            event["tool"]["command"] = command
    elif record_type in {"tool_result", "tool.post", "function_call_output"} and (tool_name or command or "exit_code" in record):
        event["event_type"] = "tool.post"
        event["tool"] = {"name": tool_name or "shell", "success": record.get("success", record.get("exit_code", 0) == 0)}
        if command:
            event["tool"]["command"] = command
        if "exit_code" in record:
            event["tool"]["exit_code"] = record["exit_code"]
    elif record_type in {"tool_error", "tool.error"}:
        event["event_type"] = "tool.error"
        event["tool"] = {"name": tool_name or "unknown"}
    else:
        event["event_type"] = "blind_spot.declared"
        event["blind_spots"] = [f"Unsupported or incomplete Codex session record: {record_type or 'unknown'}"]
    return event


def import_jsonl(input_path: str | Path, ledger_path: str | Path | None = None) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    with Path(input_path).open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                event = normalize_record(record)
            except json.JSONDecodeError:
                event = {
                    "source": {"agent": "codex-cli", "collector": "codex-session-importer"},
                    "event_type": "blind_spot.declared",
                    "blind_spots": [f"Malformed JSONL at line {line_number}"],
                }
            output.append(append_event(ledger_path, event) if ledger_path else event)
    return output

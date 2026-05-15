"""Codex CLI session JSONL importer.

Reads Codex session JSONL files and normalizes records to ledger events.
Emits blind_spot.declared events for unsupported or incomplete records.
"""

import json
from pathlib import Path
from typing import Any

from agent_loop.ledger import append_event, build_event
from agent_loop.repo_context import normalize_path, resolve_repo_context

_BLIND_SPOTS = [
    "Hidden model reasoning is not captured.",
    "Codex session format may omit tool boundaries or output content.",
    "Provider-side request/response logs are unavailable.",
]


def _record_cwd(record: dict, fallback_cwd: str | Path | None) -> str | None:
    cwd = record.get("cwd") or record.get("working_dir") or record.get("workingDirectory")
    if cwd is None:
        cwd = fallback_cwd
    return normalize_path(cwd) if cwd else None


def _repo_extra(cwd: str | None) -> dict[str, Any]:
    if not cwd:
        return {}
    repo = resolve_repo_context(cwd)
    return {"repo": repo} if repo is not None else {}


def _normalize_codex_record(
    record: dict,
    agent: str,
    *,
    fallback_cwd: str | Path | None = None,
) -> dict[str, Any] | None:
    """Normalize one Codex session record to a ledger event dict."""
    rtype = record.get("type") or record.get("role")

    session_id = record.get("session_id") or record.get("id")
    cwd = _record_cwd(record, fallback_cwd)

    if rtype == "function_call" or (rtype == "tool" and record.get("call")):
        tool_data: dict[str, Any] = {}
        name = record.get("name") or record.get("function") or record.get("tool")
        if name:
            tool_data["name"] = name
        args = record.get("arguments") or record.get("input") or record.get("call", {}).get("arguments")
        if isinstance(args, dict):
            cmd = args.get("command")
            if cmd:
                tool_data["command"] = cmd
                tool_data["input_summary"] = cmd[:200]
            else:
                tool_data["input_summary"] = json.dumps(args)[:200]
        elif args:
            tool_data["input_summary"] = str(args)[:200]

        return build_event(
            "tool.pre",
            agent,
            session_id=session_id,
            cwd=cwd,
            extra={"tool": tool_data, **_repo_extra(cwd)},
        )

    if rtype == "function_call_output" or rtype == "tool_result":
        tool_data = {}
        name = record.get("name") or record.get("function") or record.get("tool")
        if name:
            tool_data["name"] = name
        exit_code = record.get("exit_code") or record.get("exitCode")
        if exit_code is not None:
            tool_data["exit_code"] = exit_code
            tool_data["success"] = exit_code == 0
        else:
            tool_data["success"] = not record.get("error")

        if record.get("error"):
            return build_event(
                "tool.error",
                agent,
                session_id=session_id,
                cwd=cwd,
                extra={"tool": tool_data, **_repo_extra(cwd)},
            )
        return build_event(
            "tool.post",
            agent,
            session_id=session_id,
            cwd=cwd,
            extra={"tool": tool_data, **_repo_extra(cwd)},
        )

    if rtype in ("user", "assistant", "system"):
        content = record.get("content", "")
        if isinstance(content, list):
            text_parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            content = " ".join(text_parts)
        if rtype == "user" and content:
            return build_event(
                "prompt.submitted",
                agent,
                session_id=session_id,
                cwd=cwd,
                extra={"prompt": str(content)[:500], **_repo_extra(cwd)},
            )
        if rtype == "assistant" and content:
            return build_event(
                "recommendation.created",
                agent,
                session_id=session_id,
                cwd=cwd,
                extra={"message": str(content)[:500], **_repo_extra(cwd)},
            )
        return None

    return build_event(
        "blind_spot.declared",
        agent,
        session_id=session_id,
        cwd=cwd,
        extra={
            "blind_spots": [
                f"Unsupported Codex record type: {rtype!r}",
                *_BLIND_SPOTS,
            ],
            **_repo_extra(cwd),
        },
    )


def import_codex_session(
    source_path: str | Path,
    *,
    ledger_path: str | Path = "agent-ledger.jsonl",
    agent: str = "codex-cli",
    cwd: str | Path | None = None,
) -> int:
    """Import a Codex session JSONL file into the ledger. Returns count of appended events."""
    p = Path(source_path)
    count = 0

    with p.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                record = json.loads(raw)
            except json.JSONDecodeError as exc:
                event = build_event(
                    "blind_spot.declared",
                    agent,
                    cwd=normalize_path(cwd) if cwd else None,
                    extra={
                        "blind_spots": [f"Line {lineno}: malformed JSON: {exc}", *_BLIND_SPOTS],
                        **_repo_extra(normalize_path(cwd) if cwd else None),
                    },
                )
                append_event(ledger_path, event)
                count += 1
                continue

            event = _normalize_codex_record(record, agent, fallback_cwd=cwd)
            if event is not None:
                append_event(ledger_path, event)
                count += 1

    return count

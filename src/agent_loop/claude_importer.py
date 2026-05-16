"""Claude Code session transcript importer.

Reads Claude Code session JSONL transcripts and normalizes records to ledger
events. Unlike Codex JSONL, tool calls are nested as ``tool_use`` blocks inside
``assistant`` message content, and tool results are nested as ``tool_result``
blocks inside ``user`` message content. Sub-agent activity lives in separate
files under ``<session-id>/subagents/``.

Emits blind_spot.declared events for record types that carry no agent activity.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_loop.collector import apply_policy_to_event
from agent_loop.ledger import append_event, build_event
from agent_loop.repo_context import normalize_path, resolve_repo_context

_BLIND_SPOTS = [
    "Hidden model reasoning (thinking blocks) is not captured.",
    "Provider-side request/response logs are unavailable.",
    "This record type carries transcript metadata, not agent tool activity.",
]

# Keys that reliably appear in Claude Code transcripts but never in Codex JSONL.
_CLAUDE_MARKER_KEYS = {"parentUuid", "isSidechain", "sessionId", "uuid", "leafUuid", "gitBranch"}

# Transcript bookkeeping records that carry no agent tool activity (session
# titles, file backup snapshots, prompt pointers, queue plumbing, system
# notices, PR links). They are skipped silently, like Codex telemetry records,
# so they do not inflate blind-spot counts in the analyzer's import-visibility
# report. Record types with real agent activity are normalized instead:
# `attachment` and `permission-mode` are handled in _normalize_claude_record,
# and any record type that is neither normalized nor listed here falls through
# to a blind_spot.declared event.
_IGNORED_CLAUDE_TYPES = {
    "agent-name",
    "ai-title",
    "custom-title",
    "file-history-snapshot",
    "last-prompt",
    "pr-link",
    "queue-operation",
    "queued-command",
    "summary",
    "system",
}

# `attachment` records inject context (skill lists, reminders, file content,
# tool-list deltas). These subtypes carry no agent decision and are skipped;
# `hook_permission_decision` is normalized to an approval event, and any
# unknown subtype is still declared as a blind spot.
_IGNORED_ATTACHMENT_SUBTYPES = {
    "agent_listing_delta",
    "command_permissions",
    "compact_file_reference",
    "date_change",
    "deferred_tools_delta",
    "edited_text_file",
    "file",
    "goal_status",
    "hook_success",
    "invoked_skills",
    "mcp_instructions_delta",
    "plan_file_reference",
    "plan_mode",
    "plan_mode_exit",
    "queued_command",
    "skill_listing",
    "task_reminder",
    "todo_reminder",
}

# Tools whose input names a file; used to populate the event `files` array.
_PATH_TOOL_OPERATIONS = {
    "Read": "read",
    "Edit": "edit",
    "MultiEdit": "edit",
    "Write": "write",
    "NotebookEdit": "edit",
}


@dataclass
class _ClaudeContext:
    session_id: str | None = None
    cwd: str | None = None
    repo_cache: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    # tool_use id -> remembered tool metadata, used to label the matching result.
    tool_calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Last seen permission mode, so only real transitions become events.
    last_permission_mode: str | None = None


def _repo_extra(cwd: str | None, repo_cache: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    if not cwd:
        return {}
    if cwd not in repo_cache:
        repo_cache[cwd] = resolve_repo_context(cwd)
    repo = repo_cache[cwd]
    return {"repo": repo} if repo is not None else {}


def _truncate(value: Any, limit: int = 200) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text[:limit]


def _block_text(content: Any) -> str:
    """Join text from a content value that is a string or a list of blocks."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
            parts.append(str(block["text"]))
    return "\n".join(parts)


def is_claude_session(source_path: str | Path) -> bool:
    """Return True when the JSONL file looks like a Claude Code transcript."""
    p = Path(source_path)
    try:
        with p.open("r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f):
                if lineno >= 40:
                    break
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict) and _CLAUDE_MARKER_KEYS & record.keys():
                    return True
    except OSError:
        return False
    return False


def _files_for_tool(name: Any, tool_input: Any) -> list[dict[str, str]]:
    """Return a `files` array entry when a tool input names a file path."""
    if not isinstance(tool_input, dict):
        return []
    operation = _PATH_TOOL_OPERATIONS.get(str(name))
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if operation and path:
        return [{"path": str(path), "operation": operation}]
    return []


def _tool_use_event(
    block: dict[str, Any],
    agent: str,
    *,
    session_id: str | None,
    cwd: str | None,
    repo_extra: dict[str, Any],
    context: _ClaudeContext,
) -> dict[str, Any]:
    tool_input = block.get("input")
    tool_data: dict[str, Any] = {}

    name = block.get("name")
    if name:
        tool_data["name"] = name

    call_id = block.get("id")
    if call_id:
        tool_data["call_id"] = str(call_id)

    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if isinstance(command, str) and command:
        tool_data["command"] = command
        tool_data["input_summary"] = command[:200]
    elif tool_input:
        tool_data["input_summary"] = _truncate(tool_input)
    if isinstance(tool_input, dict):
        tool_data["input_full"] = tool_input

    if call_id:
        context.tool_calls[str(call_id)] = {"name": name} if name else {}

    extra: dict[str, Any] = {"tool": tool_data, **repo_extra}
    files = _files_for_tool(name, tool_input)
    if files:
        extra["files"] = files

    return build_event(
        "tool.pre",
        agent,
        session_id=session_id,
        cwd=cwd,
        extra=extra,
    )


def _tool_result_event(
    block: dict[str, Any],
    agent: str,
    *,
    session_id: str | None,
    cwd: str | None,
    repo_extra: dict[str, Any],
    context: _ClaudeContext,
) -> dict[str, Any]:
    call_id = block.get("tool_use_id")
    remembered = context.tool_calls.get(str(call_id), {}) if call_id else {}

    tool_data: dict[str, Any] = {}
    name = remembered.get("name")
    if name:
        tool_data["name"] = name
    if call_id:
        tool_data["call_id"] = str(call_id)

    is_error = bool(block.get("is_error"))
    tool_data["success"] = not is_error

    if is_error:
        error_text = _block_text(block.get("content"))
        if error_text:
            tool_data["error"] = error_text[:200]

    return build_event(
        "tool.error" if is_error else "tool.post",
        agent,
        session_id=session_id,
        cwd=cwd,
        extra={"tool": tool_data, **repo_extra},
    )


def _attachment_events(
    record: dict[str, Any],
    agent: str,
    *,
    session_id: str | None,
    cwd: str | None,
    repo_extra: dict[str, Any],
) -> list[dict[str, Any]]:
    """Normalize an `attachment` record to zero or one ledger event."""
    attachment = record.get("attachment")
    subtype = attachment.get("type") if isinstance(attachment, dict) else None

    if subtype == "hook_permission_decision":
        decision = attachment.get("decision")
        approval: dict[str, Any] = {
            "status": "approved" if decision == "allow" else "denied",
            "reviewer": "claude-code-hook",
        }
        request_id = attachment.get("toolUseID")
        if request_id:
            approval["request_id"] = str(request_id)
        return [
            build_event(
                "approval.resolved",
                agent,
                session_id=session_id,
                cwd=cwd,
                extra={"approval": approval, **repo_extra},
            )
        ]

    if subtype in _IGNORED_ATTACHMENT_SUBTYPES:
        return []

    return [
        build_event(
            "blind_spot.declared",
            agent,
            session_id=session_id,
            cwd=cwd,
            extra={
                "blind_spots": [
                    f"Unsupported Claude Code attachment subtype: {subtype!r}",
                    *_BLIND_SPOTS,
                ],
                **repo_extra,
            },
        )
    ]


def _permission_mode_events(
    record: dict[str, Any],
    agent: str,
    context: _ClaudeContext,
    *,
    session_id: str | None,
    cwd: str | None,
    repo_extra: dict[str, Any],
) -> list[dict[str, Any]]:
    """Normalize a `permission-mode` record, emitting only on a real change."""
    mode = record.get("permissionMode")
    if not mode or mode == context.last_permission_mode:
        return []

    previous = context.last_permission_mode
    context.last_permission_mode = str(mode)
    policy: dict[str, Any] = {"mode": str(mode)}
    if previous:
        policy["previous_mode"] = previous
    return [
        build_event(
            "policy.mode_changed",
            agent,
            session_id=session_id,
            cwd=cwd,
            extra={"policy": policy, **repo_extra},
        )
    ]


def _normalize_claude_record(
    record: dict[str, Any],
    agent: str,
    context: _ClaudeContext,
    *,
    sub_agent: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Normalize one Claude Code transcript record to zero or more ledger events."""
    rtype = record.get("type")
    if rtype in _IGNORED_CLAUDE_TYPES:
        return []
    session_id = record.get("sessionId") or context.session_id
    cwd = normalize_path(record["cwd"]) if record.get("cwd") else context.cwd
    repo_extra = _repo_extra(cwd, context.repo_cache)

    message = record.get("message")
    content = message.get("content") if isinstance(message, dict) else None

    events: list[dict[str, Any]] = []

    if rtype == "assistant":
        if isinstance(content, list):
            text = _block_text(content).strip()
            if text:
                events.append(
                    build_event(
                        "recommendation.created",
                        agent,
                        session_id=session_id,
                        cwd=cwd,
                        extra={"message": text[:500], **repo_extra},
                    )
                )
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    events.append(
                        _tool_use_event(
                            block,
                            agent,
                            session_id=session_id,
                            cwd=cwd,
                            repo_extra=repo_extra,
                            context=context,
                        )
                    )
        return _attribute(events, sub_agent)

    if rtype == "user":
        # Meta records (slash-command caveats, hook plumbing) are not prompts.
        if record.get("isMeta"):
            return []

        tool_results = (
            [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
            if isinstance(content, list)
            else []
        )
        if tool_results:
            for block in tool_results:
                events.append(
                    _tool_result_event(
                        block,
                        agent,
                        session_id=session_id,
                        cwd=cwd,
                        repo_extra=repo_extra,
                        context=context,
                    )
                )
            return _attribute(events, sub_agent)

        # A genuine prompt is plain user text, never a tool_result carrier.
        text = _block_text(content).strip()
        if text:
            events.append(
                build_event(
                    "prompt.submitted",
                    agent,
                    session_id=session_id,
                    cwd=cwd,
                    extra={"prompt": text[:500], **repo_extra},
                )
            )
        return _attribute(events, sub_agent)

    if rtype == "attachment":
        return _attribute(
            _attachment_events(record, agent, session_id=session_id, cwd=cwd, repo_extra=repo_extra),
            sub_agent,
        )

    if rtype == "permission-mode":
        return _attribute(
            _permission_mode_events(
                record, agent, context, session_id=session_id, cwd=cwd, repo_extra=repo_extra
            ),
            sub_agent,
        )

    # Any remaining record type is not yet normalized and is recorded as an
    # explicit blind spot. Pure bookkeeping types are filtered earlier via
    # _IGNORED_CLAUDE_TYPES.
    events.append(
        build_event(
            "blind_spot.declared",
            agent,
            session_id=session_id,
            cwd=cwd,
            extra={
                "blind_spots": [
                    f"Unsupported Claude Code record type: {rtype!r}",
                    *_BLIND_SPOTS,
                ],
                **repo_extra,
            },
        )
    )
    return _attribute(events, sub_agent)


def _attribute(events: list[dict[str, Any]], sub_agent: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Tag sub-agent events so they link back to their parent session."""
    if sub_agent:
        for event in events:
            event["sub_agent"] = dict(sub_agent)
            event.setdefault("session", {})["agent_id"] = sub_agent["agent_id"]
    return events


def _import_claude_file(
    source_path: Path,
    ledger_path: str | Path,
    agent: str,
    context: _ClaudeContext,
    *,
    sub_agent: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> int:
    count = 0
    with source_path.open("r", encoding="utf-8") as f:
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
                    session_id=context.session_id,
                    cwd=context.cwd,
                    extra={
                        "blind_spots": [f"Line {lineno}: malformed JSON: {exc}", *_BLIND_SPOTS],
                        **_repo_extra(context.cwd, context.repo_cache),
                    },
                )
                append_event(ledger_path, _attribute([event], sub_agent)[0])
                count += 1
                continue

            if not isinstance(record, dict):
                continue

            # Track session id and cwd so later records without them inherit context.
            if sub_agent is None:
                if record.get("sessionId") and context.session_id is None:
                    context.session_id = str(record["sessionId"])
                if record.get("cwd"):
                    context.cwd = normalize_path(record["cwd"])

            for event in _normalize_claude_record(record, agent, context, sub_agent=sub_agent):
                apply_policy_to_event(event, policy)
                append_event(ledger_path, event)
                count += 1

    return count


def _subagent_metadata(sub_file: Path, parent_session_id: str | None) -> dict[str, Any]:
    """Build sub-agent attribution metadata from the transcript and meta sidecar."""
    agent_id = sub_file.stem.removeprefix("agent-")
    sub_agent: dict[str, Any] = {"agent_id": agent_id}
    if parent_session_id:
        sub_agent["parent_session_id"] = parent_session_id

    meta_path = sub_file.parent / f"{sub_file.stem}.meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}
        if isinstance(meta, dict):
            if meta.get("agentType"):
                sub_agent["type"] = str(meta["agentType"])
            if meta.get("description"):
                sub_agent["description"] = str(meta["description"])
    return sub_agent


def import_claude_session(
    source_path: str | Path,
    *,
    ledger_path: str | Path = "agent-ledger.jsonl",
    agent: str = "claude-code",
    cwd: str | Path | None = None,
    include_subagents: bool = True,
    policy_path: str | Path | None = None,
) -> int:
    """Import a Claude Code session transcript into the ledger.

    Recurses into ``<session-id>/subagents/*.jsonl`` siblings when present and
    attributes those events back to the parent session. When `policy_path` is
    given, each imported `tool.pre` event is classified against that policy.
    Returns the count of appended events.
    """
    from agent_loop.policy import load_policy

    p = Path(source_path)
    context = _ClaudeContext(cwd=normalize_path(cwd) if cwd else None)
    policy = load_policy(policy_path) if policy_path else None

    count = _import_claude_file(p, ledger_path, agent, context, policy=policy)

    if include_subagents:
        sub_dir = p.parent / p.stem / "subagents"
        if sub_dir.is_dir():
            for sub_file in sorted(sub_dir.glob("*.jsonl")):
                sub_agent = _subagent_metadata(sub_file, context.session_id)
                count += _import_claude_file(
                    sub_file,
                    ledger_path,
                    agent,
                    context,
                    sub_agent=sub_agent,
                    policy=policy,
                )

    return count

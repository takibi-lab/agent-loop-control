"""Codex session JSONL importer.

Reads Codex session JSONL files and normalizes records to ledger events.
Emits blind_spot.declared events for unsupported or incomplete records.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_loop.collector import apply_policy_to_event
from agent_loop.ledger import append_event, build_event
from agent_loop.repo_context import normalize_path, resolve_repo_context
from agent_loop.tool_kind import set_shell, set_structured

_BLIND_SPOTS = [
    "Hidden model reasoning is not captured.",
    "Codex session format may omit tool boundaries or output content.",
    "Provider-side request/response logs are unavailable.",
]

_WRAPPER_TYPES = {"event_msg", "response_item", "session_meta", "turn_context"}
_IGNORED_CODEX_TYPES = {
    "agent_message",
    "compacted",
    "context_compacted",
    "reasoning",
    "task_complete",
    "task_started",
    "thread_name_updated",
    "token_count",
    "turn_aborted",
}
_DEFAULT_TOOL_NAMES = {
    "image_generation_call": "image_generation",
    "image_generation_end": "image_generation",
    "patch_apply_end": "apply_patch",
    "web_search_call": "web_search",
    "web_search_end": "web_search",
    "exec_command_end": "exec_command",
    "view_image_tool_call": "view_image",
}

# Codex record types that represent the model invoking a tool.
_TOOL_CALL_TYPES = {
    "function_call",
    "custom_tool_call",
    "image_generation_call",
    "web_search_call",
    "view_image_tool_call",
}

# Codex emits an `event_msg`/`exec_command_end` payload with the real exit code
# for every shell call, in addition to the model-facing `function_call_output`.
# Both share a `call_id`; `_scan_exec_end_call_ids` collects every
# `exec_command_end` call_id up front so the paired `function_call_output` is
# always dropped in favor of the richer record, regardless of transcript order.
_TOOL_OUTPUT_TYPES = {
    "function_call_output",
    "custom_tool_call_output",
    "exec_command_end",
    "image_generation_end",
    "mcp_tool_call_end",
    "patch_apply_end",
    "tool_result",
    "web_search_end",
}


@dataclass
class _ImportContext:
    session_id: str | None = None
    cwd: str | None = None
    repo_cache: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    tool_calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    output_call_ids: set[str] = field(default_factory=set)
    # call_ids that have an exec_command_end record anywhere in the transcript.
    exec_end_call_ids: set[str] = field(default_factory=set)


def _record_cwd(record: dict, fallback_cwd: str | Path | None) -> str | None:
    cwd = record.get("cwd") or record.get("working_dir") or record.get("workingDirectory")
    if cwd is None:
        cwd = fallback_cwd
    return normalize_path(cwd) if cwd else None


def _repo_extra(cwd: str | None, repo_cache: dict[str, dict[str, Any] | None] | None = None) -> dict[str, Any]:
    if not cwd:
        return {}
    if repo_cache is not None:
        if cwd not in repo_cache:
            repo_cache[cwd] = resolve_repo_context(cwd)
        repo = repo_cache[cwd]
    else:
        repo = resolve_repo_context(cwd)
    return {"repo": repo} if repo is not None else {}


def _unwrap_codex_record(record: dict[str, Any]) -> dict[str, Any]:
    payload = record.get("payload")
    if record.get("type") in _WRAPPER_TYPES and isinstance(payload, dict):
        unwrapped = dict(payload)
        unwrapped["_codex_wrapper_type"] = record.get("type")
        return unwrapped
    return record


def _load_json_maybe(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _truncate(value: Any, limit: int = 200) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text[:limit]


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    text_parts = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"input_text", "output_text", "text"} and item.get("text"):
            text_parts.append(str(item["text"]))
    return " ".join(text_parts)


def _extract_tool_command(arguments: Any) -> str | None:
    if not isinstance(arguments, dict):
        return None
    command = arguments.get("command") or arguments.get("cmd")
    return str(command) if command else None


def _tool_call_data(record: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    rtype = record.get("type")
    args = _load_json_maybe(record.get("arguments") or record.get("input") or record.get("action"))
    cwd = _record_cwd(record, None)
    if cwd is None and isinstance(args, dict) and args.get("workdir"):
        cwd = normalize_path(args["workdir"])

    tool_data: dict[str, Any] = {}
    name = record.get("name") or record.get("function") or record.get("tool") or _DEFAULT_TOOL_NAMES.get(str(rtype))
    if name:
        tool_data["name"] = name

    call_id = record.get("call_id") or record.get("id")
    if call_id:
        tool_data["call_id"] = str(call_id)

    command = _extract_tool_command(args)
    input_full = args if isinstance(args, dict) else None
    if command:
        set_shell(tool_data, command, input_full=input_full)
    elif args:
        set_structured(tool_data, input_summary=_truncate(args), input_full=input_full)

    return tool_data, cwd


def _tool_output_data(record: dict[str, Any], tool_calls: dict[str, dict[str, Any]]) -> dict[str, Any]:
    call_id = record.get("call_id") or record.get("id")
    tool_data = dict(tool_calls.get(str(call_id), {})) if call_id else {}
    if call_id:
        tool_data["call_id"] = str(call_id)

    name = record.get("name") or record.get("function") or record.get("tool")
    invocation = record.get("invocation")
    if name is None and isinstance(invocation, dict):
        server = invocation.get("server")
        tool = invocation.get("tool")
        if server and tool:
            name = f"{server}.{tool}"
        elif tool:
            name = tool
    if name is None:
        name = _DEFAULT_TOOL_NAMES.get(str(record.get("type")))
    if name:
        tool_data["name"] = name

    output = _load_json_maybe(record.get("output"))
    metadata = output.get("metadata") if isinstance(output, dict) else None
    exit_code = record.get("exit_code") if "exit_code" in record else record.get("exitCode")
    if exit_code is None and isinstance(metadata, dict):
        exit_code = metadata.get("exit_code")
    if exit_code is not None:
        tool_data["exit_code"] = exit_code

    status = record.get("status")
    if status is None and isinstance(output, dict):
        status = output.get("status")
    status_value = status if isinstance(status, str) else None
    explicit_success = record.get("success")
    result = record.get("result")
    if explicit_success is None and isinstance(result, dict):
        explicit_success = "Ok" in result and "Err" not in result
    timed_out = output.get("timed_out") if isinstance(output, dict) else None
    has_error = (
        bool(record.get("error"))
        or status_value in {"error", "failed"}
        or timed_out is True
        or explicit_success is False
    )
    if exit_code is not None:
        tool_data["success"] = exit_code == 0 and not has_error
    else:
        tool_data["success"] = not has_error
    return tool_data


def _update_context_from_metadata(record: dict[str, Any], context: _ImportContext) -> bool:
    wrapper_type = record.get("_codex_wrapper_type")
    if wrapper_type not in {"session_meta", "turn_context"}:
        return False

    if wrapper_type == "session_meta" and record.get("id"):
        context.session_id = str(record["id"])

    cwd = _record_cwd(record, context.cwd)
    if cwd:
        context.cwd = cwd
    return True


def _normalize_codex_record(
    record: dict,
    agent: str,
    *,
    fallback_cwd: str | Path | None = None,
    fallback_session_id: str | None = None,
    repo_cache: dict[str, dict[str, Any] | None] | None = None,
    tool_calls: dict[str, dict[str, Any]] | None = None,
    output_call_ids: set[str] | None = None,
    exec_end_call_ids: set[str] | None = None,
) -> dict[str, Any] | None:
    """Normalize one Codex session record to a ledger event dict."""
    record = _unwrap_codex_record(record)
    rtype = record.get("type") or record.get("role")
    role = record.get("role")
    wrapper_type = record.get("_codex_wrapper_type")
    tool_calls = tool_calls if tool_calls is not None else {}
    output_call_ids = output_call_ids if output_call_ids is not None else set()
    exec_end_call_ids = exec_end_call_ids if exec_end_call_ids is not None else set()

    if wrapper_type in {"session_meta", "turn_context"} or rtype in _IGNORED_CODEX_TYPES:
        return None

    session_id = record.get("session_id") or fallback_session_id
    cwd = _record_cwd(record, fallback_cwd)

    if rtype in _TOOL_CALL_TYPES or (rtype == "tool" and record.get("call")):
        if rtype == "tool" and record.get("call"):
            record = {**record, **record.get("call", {})}
        tool_data, tool_cwd = _tool_call_data(record)
        if tool_cwd:
            cwd = tool_cwd
        call_id = tool_data.get("call_id")
        if isinstance(call_id, str):
            # Cache only the identifying / classifying fields so tool.post
            # events stay lean: ``input_summary`` and ``input_full`` belong to
            # the pre side (the call's input), while ``name`` / ``kind`` /
            # ``command`` / ``call_id`` describe the call itself.
            _post_skip = {"input_summary", "input_full"}
            tool_calls[call_id] = {k: v for k, v in tool_data.items() if k not in _post_skip}

        return build_event(
            "tool.pre",
            agent,
            session_id=session_id,
            cwd=cwd,
            extra={"tool": tool_data, **_repo_extra(cwd, repo_cache)},
        )

    if rtype in _TOOL_OUTPUT_TYPES:
        call_id = record.get("call_id") or record.get("id")
        cid = str(call_id) if call_id is not None else None
        # Codex emits both `exec_command_end` (real exit code) and the
        # model-facing `function_call_output` for one shell `call_id`. Drop the
        # `function_call_output` whenever an `exec_command_end` exists for the
        # same call_id, regardless of which record appears first, so the richer
        # record always wins and the shell call is not double-counted.
        if rtype == "function_call_output" and cid is not None and cid in exec_end_call_ids:
            return None
        # Guard against the same output record repeating for one call_id.
        if cid is not None:
            if cid in output_call_ids:
                return None
            output_call_ids.add(cid)

        tool_data = _tool_output_data(record, tool_calls)

        if tool_data.get("success") is False:
            return build_event(
                "tool.error",
                agent,
                session_id=session_id,
                cwd=cwd,
                extra={"tool": tool_data, **_repo_extra(cwd, repo_cache)},
            )
        return build_event(
            "tool.post",
            agent,
            session_id=session_id,
            cwd=cwd,
            extra={"tool": tool_data, **_repo_extra(cwd, repo_cache)},
        )

    if rtype in {"message", "user", "assistant", "system", "developer", "user_message"}:
        message_role = role or (rtype if rtype in {"user", "assistant", "system", "developer"} else None)
        content = _extract_text(record.get("content"))
        if not content and record.get("message"):
            content = str(record["message"])
        if not content and record.get("text_elements"):
            content = _extract_text(record["text_elements"])

        if (message_role == "user" or rtype == "user_message") and content:
            return build_event(
                "prompt.submitted",
                agent,
                session_id=session_id,
                cwd=cwd,
                extra={"prompt": content[:500], **_repo_extra(cwd, repo_cache)},
            )
        if message_role == "assistant" and content:
            return build_event(
                "recommendation.created",
                agent,
                session_id=session_id,
                cwd=cwd,
                extra={"message": content[:500], **_repo_extra(cwd, repo_cache)},
            )
        return None

    if rtype == "item_completed":
        # Newer Codex transcripts wrap completed thread items here. A Plan item
        # carries the agent's planning text; map it to a recommendation. Other
        # item subtypes are declared as blind spots that name the subtype.
        item = record.get("item")
        item_type = item.get("type") if isinstance(item, dict) else None
        if item_type == "Plan":
            text = item.get("text") if isinstance(item, dict) else None
            if not text:
                return None
            return build_event(
                "recommendation.created",
                agent,
                session_id=session_id,
                cwd=cwd,
                extra={"message": str(text)[:500], **_repo_extra(cwd, repo_cache)},
            )
        return build_event(
            "blind_spot.declared",
            agent,
            session_id=session_id,
            cwd=cwd,
            extra={
                "blind_spots": [
                    f"Unsupported Codex item_completed item type: {item_type!r}",
                    *_BLIND_SPOTS,
                ],
                **_repo_extra(cwd, repo_cache),
            },
        )

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
            **_repo_extra(cwd, repo_cache),
        },
    )


def import_session(
    source_path: str | Path,
    *,
    ledger_path: str | Path = "agent-ledger.jsonl",
    agent: str | None = None,
    cwd: str | Path | None = None,
    session_format: str = "auto",
    policy_path: str | Path | None = None,
) -> int:
    """Import an agent session transcript, auto-detecting Codex vs Claude Code.

    `session_format` may be "auto", "codex", or "claude-code". When `policy_path`
    is given, imported `tool.pre` events are classified against that policy.
    Returns the count of appended events.
    """
    from agent_loop.claude_importer import import_claude_session, is_claude_session

    if session_format == "auto":
        session_format = "claude-code" if is_claude_session(source_path) else "codex"

    if session_format == "claude-code":
        return import_claude_session(
            source_path,
            ledger_path=ledger_path,
            agent=agent or "claude-code",
            cwd=cwd,
            policy_path=policy_path,
        )
    return import_codex_session(
        source_path,
        ledger_path=ledger_path,
        agent=agent or "codex-cli",
        cwd=cwd,
        policy_path=policy_path,
    )


def _scan_exec_end_call_ids(lines: Iterable[str]) -> set[str]:
    """Collect every call_id that has an `exec_command_end` record.

    Codex emits both `exec_command_end` and `function_call_output` for one
    shell `call_id`. Pre-scanning the whole transcript lets the importer always
    prefer the richer `exec_command_end`, no matter which record comes first.
    """
    call_ids: set[str] = set()
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(record, dict):
            continue
        record = _unwrap_codex_record(record)
        if record.get("type") != "exec_command_end":
            continue
        call_id = record.get("call_id") or record.get("id")
        if call_id is not None:
            call_ids.add(str(call_id))
    return call_ids


def import_codex_session(
    source_path: str | Path,
    *,
    ledger_path: str | Path = "agent-ledger.jsonl",
    agent: str = "codex-cli",
    cwd: str | Path | None = None,
    policy_path: str | Path | None = None,
) -> int:
    """Import a Codex session JSONL file into the ledger. Returns count of appended events.

    When `policy_path` is given, each imported `tool.pre` event is classified
    against that policy and carries the resulting decision.
    """
    from agent_loop.policy import load_policy

    p = Path(source_path)
    count = 0
    context = _ImportContext(cwd=normalize_path(cwd) if cwd else None)
    policy = load_policy(policy_path) if policy_path else None

    with p.open("r", encoding="utf-8") as f:
        context.exec_end_call_ids = _scan_exec_end_call_ids(f)

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
                    session_id=context.session_id,
                    cwd=context.cwd,
                    extra={
                        "blind_spots": [f"Line {lineno}: malformed JSON: {exc}", *_BLIND_SPOTS],
                        **_repo_extra(context.cwd, context.repo_cache),
                    },
                )
                append_event(ledger_path, event)
                count += 1
                continue

            unwrapped = _unwrap_codex_record(record)
            if _update_context_from_metadata(unwrapped, context):
                continue

            event = _normalize_codex_record(
                unwrapped,
                agent,
                fallback_cwd=context.cwd,
                fallback_session_id=context.session_id,
                repo_cache=context.repo_cache,
                tool_calls=context.tool_calls,
                output_call_ids=context.output_call_ids,
                exec_end_call_ids=context.exec_end_call_ids,
            )
            if event is not None:
                apply_policy_to_event(event, policy)
                append_event(ledger_path, event)
                count += 1

    return count

"""Single source of truth for ``tool.kind`` handling.

``kind`` was introduced after PR #25 / PR #28 to disambiguate shell commands
from structured tool input. Before that, every reader of the ``tool`` block
re-derived the distinction from ``command`` vs ``input_summary``/``input_full``
and the same confusion bug-checked twice (analyzer mis-grouped ``apply_patch``
JSON as ``cmd:*** Begin``; timeline rendered Write input as ``cmd={...}``).

Importers and the hook collector now set ``kind`` at ingest time, and all
readers route through this module instead of touching ``command`` directly.
The :func:`derive_kind` heuristic absorbs legacy ledgers that pre-date the
field so we never need a ``command or input_summary`` fallback again.
"""

from typing import Any

SHELL = "shell"
STRUCTURED = "structured"


def derive_kind(tool: dict[str, Any]) -> str | None:
    """Return ``tool.kind``, inferring it for legacy records.

    Honors an explicit ``kind`` when present. Otherwise: a string ``command``
    means :data:`SHELL`, the *presence* of any structured payload key
    (``input_full`` or ``input_summary``) means :data:`STRUCTURED`, and a tool
    block with neither returns ``None`` so callers can treat it as unknown.

    The structured branch uses ``in`` rather than truthiness so an explicitly
    empty payload (``input_full={}`` or ``input_summary=""``) is still
    classified — the field was set deliberately by an importer, just with no
    data, and falling through to ``None`` would silently demote it to unknown.
    """
    if not isinstance(tool, dict):
        return None
    explicit = tool.get("kind")
    if explicit in (SHELL, STRUCTURED):
        return explicit
    command = tool.get("command")
    if isinstance(command, str) and command:
        return SHELL
    if "input_full" in tool or "input_summary" in tool:
        return STRUCTURED
    return None


def is_shell(tool: dict[str, Any]) -> bool:
    """Return True when the tool record represents a shell command."""
    return derive_kind(tool) == SHELL


def is_structured(tool: dict[str, Any]) -> bool:
    """Return True when the tool record carries structured input."""
    return derive_kind(tool) == STRUCTURED


def shell_command(tool: dict[str, Any]) -> str:
    """Return the shell command string when tool is shell-kind, else ``""``.

    Replaces ad-hoc ``tool.get("command") or ""`` reads in analyzer / timeline.
    Returns an empty string for structured tools so callers can keep their
    ``if cmd:`` truthiness checks.
    """
    if not is_shell(tool):
        return ""
    command = tool.get("command")
    return command if isinstance(command, str) else ""


def search_haystack(tool: dict[str, Any]) -> str:
    """Return the text the ``--command`` search predicate should match against.

    For shell tools that is the command itself. For structured tools we fall
    back to ``input_summary`` so searches like ``--command "Begin Patch"`` still
    hit a patch body — this is the same trade-off documented in
    ``timeline.print_search``: search is allowed to match raw tool input, while
    *display* must not render it as ``cmd=``.
    """
    if not isinstance(tool, dict):
        return ""
    cmd = shell_command(tool)
    if cmd:
        return cmd
    summary = tool.get("input_summary")
    return summary if isinstance(summary, str) else ""


def set_shell(
    tool_data: dict[str, Any],
    command: str,
    *,
    input_full: dict[str, Any] | None = None,
) -> None:
    """Stamp ``tool_data`` as a shell tool: command + truncated summary + kind.

    ``input_full`` is set when callers have a structured args dict to preserve
    (used by Claude Code / hook payloads); session importers without one can
    omit it. Importers must still set ``name`` / ``call_id`` themselves.
    """
    tool_data["command"] = command
    tool_data["input_summary"] = command[:200]
    tool_data["kind"] = SHELL
    if input_full is not None:
        tool_data["input_full"] = input_full


def set_structured(
    tool_data: dict[str, Any],
    *,
    input_summary: str,
    input_full: dict[str, Any] | None = None,
) -> None:
    """Stamp ``tool_data`` as a structured tool: summary + optional full + kind.

    ``input_summary`` is caller-truncated because each importer has a different
    truncation rule (``_truncate`` for session importers,
    ``json.dumps(..., ensure_ascii=False)[:200]`` for the hook collector).
    """
    tool_data["input_summary"] = input_summary
    tool_data["kind"] = STRUCTURED
    if input_full is not None:
        tool_data["input_full"] = input_full

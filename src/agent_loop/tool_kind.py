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
    means :data:`SHELL`, any structured payload (``input_full`` or
    ``input_summary``) means :data:`STRUCTURED`, and a tool block with neither
    returns ``None`` so callers can treat it as unknown.
    """
    if not isinstance(tool, dict):
        return None
    explicit = tool.get("kind")
    if explicit in (SHELL, STRUCTURED):
        return explicit
    command = tool.get("command")
    if isinstance(command, str) and command:
        return SHELL
    if tool.get("input_full") or tool.get("input_summary"):
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
    if is_shell(tool):
        command = tool.get("command")
        return command if isinstance(command, str) else ""
    summary = tool.get("input_summary")
    return summary if isinstance(summary, str) else ""

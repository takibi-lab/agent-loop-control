"""Tests for the ``tool_kind`` helper.

The helper is the single backwards-compat layer between new ledgers (which
record ``tool.kind`` explicitly) and pre-#31 ledgers (which encoded the
distinction implicitly via ``command`` vs ``input_summary``/``input_full``).
These tests pin down both the heuristic and the priority of the explicit
field over it.
"""

import pytest

from agent_loop.tool_kind import (
    SHELL,
    STRUCTURED,
    derive_kind,
    is_shell,
    is_structured,
    search_haystack,
    shell_command,
)


@pytest.mark.parametrize(
    "tool, expected",
    [
        ({"kind": "shell", "command": "ls"}, SHELL),
        ({"kind": "structured", "input_summary": "{...}"}, STRUCTURED),
        ({"command": "git status"}, SHELL),
        ({"input_summary": "{\"file_path\": \"x\"}"}, STRUCTURED),
        ({"input_full": {"file_path": "x"}}, STRUCTURED),
        # Field presence (not truthiness) must drive the heuristic — an importer
        # that deliberately recorded an empty structured payload should still
        # land in STRUCTURED, not the unknown bucket.
        ({"input_full": {}}, STRUCTURED),
        ({"input_summary": ""}, STRUCTURED),
        ({"name": "Bash"}, None),
        ({}, None),
        ({"command": ""}, None),
    ],
)
def test_derive_kind_backfills_legacy_records(tool, expected):
    assert derive_kind(tool) == expected


def test_explicit_kind_wins_over_heuristic():
    # A bogus combination — explicit ``kind`` must still be honored so importers
    # remain the single source of truth.
    assert derive_kind({"kind": "structured", "command": "ls"}) == STRUCTURED


def test_is_shell_and_is_structured_are_mutually_exclusive():
    shell_tool = {"command": "git status"}
    structured_tool = {"input_full": {"file_path": "x"}}
    assert is_shell(shell_tool) and not is_structured(shell_tool)
    assert is_structured(structured_tool) and not is_shell(structured_tool)


def test_shell_command_returns_empty_for_structured_tool():
    # PR #25 / #31 invariant: structured input never surfaces as a shell command.
    assert shell_command({"input_summary": "*** Begin Patch"}) == ""


def test_shell_command_returns_command_string_for_shell_tool():
    assert shell_command({"command": "git status --short"}) == "git status --short"


def test_search_haystack_falls_back_to_input_summary_for_structured():
    # ``--command "Begin Patch"`` should still match a patch body even though
    # display will not render it as ``cmd=``.
    tool = {"kind": "structured", "input_summary": "*** Begin Patch"}
    assert "Begin Patch" in search_haystack(tool)


def test_search_haystack_uses_command_for_shell_tool():
    assert search_haystack({"command": "ls -la"}) == "ls -la"

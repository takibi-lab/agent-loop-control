#!/usr/bin/env python3
"""Check public docs for local machine path leaks."""

from __future__ import annotations

import re
import sys
from pathlib import Path

LOCAL_USER_HOME = re.compile(r"/Users/(?!<)[A-Za-z0-9._-]+/")
DEFAULT_PATHS = [Path("README.md"), *Path("docs").glob("*.md")]
NEWLINE = "\n"


def _iter_paths(args: list[str]) -> list[Path]:
    if args:
        return [Path(arg) for arg in args if Path(arg).suffix == ".md"]
    return DEFAULT_PATHS


def find_local_user_home_paths(paths: list[Path]) -> list[str]:
    offenders: list[str] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for match in LOCAL_USER_HOME.finditer(text):
            lineno = text[: match.start()].count(NEWLINE) + 1
            offenders.append(f"{path}:{lineno}: {match.group(0)}")
    return offenders


def main(argv: list[str] | None = None) -> int:
    paths = _iter_paths(list(argv or []))
    offenders = find_local_user_home_paths(paths)
    if offenders:
        print("Local user home paths found in public docs:", file=sys.stderr)
        for offender in offenders:
            print(f"- {offender}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

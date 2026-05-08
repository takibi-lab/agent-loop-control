"""Append-only JSONL ledger writer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .events import complete_event


class LedgerError(ValueError):
    pass


def read_events(path: str | Path) -> List[Dict[str, Any]]:
    ledger_path = Path(path)
    if not ledger_path.exists():
        return []
    events: List[Dict[str, Any]] = []
    with ledger_path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise LedgerError(f"invalid JSONL at line {line_number}: {exc.msg}") from exc
    return events


def append_event(path: str | Path, event: Dict[str, Any]) -> Dict[str, Any]:
    ledger_path = Path(path)
    events = read_events(ledger_path)
    prev_hash = events[-1].get("hash") if events else None
    complete = complete_event(event, prev_hash)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(complete, sort_keys=True, ensure_ascii=False) + "\n")
    return complete

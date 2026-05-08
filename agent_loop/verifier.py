"""Hash-chain ledger verifier."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .events import event_hash
from .ledger import LedgerError, read_events


@dataclass
class VerifyResult:
    valid: bool
    checked: int
    line: Optional[int] = None
    event_id: Optional[str] = None
    reason: Optional[str] = None


def verify_ledger(path: str | Path) -> VerifyResult:
    try:
        events = read_events(path)
    except LedgerError as exc:
        return VerifyResult(False, 0, reason=str(exc))

    previous_hash = None
    for idx, event in enumerate(events, start=1):
        if event.get("prev_hash") != previous_hash:
            return VerifyResult(False, idx, idx, event.get("event_id"), "prev_hash does not match previous event")
        expected = event_hash(event)
        if event.get("hash") != expected:
            return VerifyResult(False, idx, idx, event.get("event_id"), "event hash does not match canonical content")
        previous_hash = event.get("hash")
    return VerifyResult(True, len(events))

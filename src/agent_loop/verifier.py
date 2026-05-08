"""Hash-chain ledger verifier."""

import json
from pathlib import Path

from agent_loop.ledger import _canonical_bytes, _sha256


def verify_ledger(path: str | Path) -> dict:
    """Verify the hash chain of a JSONL ledger file.

    Returns a dict with keys: valid (bool), event_count (int), reason (str|None).
    """
    p = Path(path)
    if not p.exists():
        return {"valid": False, "event_count": 0, "reason": f"File not found: {path}"}

    events = []
    with p.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as exc:
                return {
                    "valid": False,
                    "event_count": len(events),
                    "reason": f"Line {lineno}: invalid JSON: {exc}",
                }
            events.append((lineno, event))

    if not events:
        return {"valid": True, "event_count": 0, "reason": None}

    prev_hash = None
    for lineno, event in events:
        event_id = event.get("event_id", f"(line {lineno})")

        stored_hash = event.get("hash")
        if not stored_hash:
            return {
                "valid": False,
                "event_count": len(events),
                "reason": f"Line {lineno} event={event_id}: missing 'hash' field",
            }

        expected_prev = event.get("prev_hash")
        if expected_prev != prev_hash:
            return {
                "valid": False,
                "event_count": len(events),
                "reason": (
                    f"Line {lineno} event={event_id}: "
                    f"prev_hash mismatch (expected {prev_hash!r}, got {expected_prev!r})"
                ),
            }

        computed = _sha256(_canonical_bytes(event))
        if computed != stored_hash:
            return {
                "valid": False,
                "event_count": len(events),
                "reason": (
                    f"Line {lineno} event={event_id}: "
                    f"hash mismatch (stored={stored_hash!r}, computed={computed!r})"
                ),
            }

        prev_hash = stored_hash

    return {"valid": True, "event_count": len(events), "reason": None}

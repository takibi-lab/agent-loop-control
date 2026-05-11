"""Hash-chain ledger verifier."""

import json
from pathlib import Path

from agent_loop.ledger import _canonical_bytes, _sha256


def _invalid(errors: list[str], event_count: int) -> dict:
    reason = errors[0] if errors else None
    if reason and len(errors) > 1:
        reason = f"{reason} (+{len(errors) - 1} more)"
    return {
        "valid": False,
        "event_count": event_count,
        "reason": reason,
        "errors": errors,
    }


def verify_ledger(path: str | Path, *, fail_fast: bool = True) -> dict:
    """Verify the hash chain of a JSONL ledger file.

    Returns valid, event_count, reason, and errors.
    """
    p = Path(path)
    if not p.exists():
        return _invalid([f"File not found: {path}"], 0)

    events = []
    errors: list[str] = []
    with p.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError as exc:
                errors.append(f"Line {lineno}: invalid JSON: {exc}")
                if fail_fast:
                    return _invalid(errors, len(events))
                continue
            events.append((lineno, event))

    if not events:
        if errors:
            return _invalid(errors, 0)
        return {"valid": True, "event_count": 0, "reason": None, "errors": []}

    prev_hash = None
    for lineno, event in events:
        event_id = event.get("event_id", f"(line {lineno})")

        stored_hash = event.get("hash")
        if not stored_hash:
            errors.append(f"Line {lineno} event={event_id}: missing 'hash' field")
            if fail_fast:
                return _invalid(errors, len(events))
            prev_hash = None
            continue

        expected_prev = event.get("prev_hash")
        if expected_prev != prev_hash:
            errors.append(
                f"Line {lineno} event={event_id}: "
                f"prev_hash mismatch (expected {prev_hash!r}, got {expected_prev!r})"
            )
            if fail_fast:
                return _invalid(errors, len(events))

        computed = _sha256(_canonical_bytes(event))
        if computed != stored_hash:
            errors.append(
                f"Line {lineno} event={event_id}: "
                f"hash mismatch (stored={stored_hash!r}, computed={computed!r})"
            )
            if fail_fast:
                return _invalid(errors, len(events))

        prev_hash = stored_hash

    if errors:
        return _invalid(errors, len(events))
    return {"valid": True, "event_count": len(events), "reason": None, "errors": []}

"""Append-only JSONL ledger writer with hash-chain support."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _canonical_bytes(event: dict) -> bytes:
    """Return canonical JSON bytes of event excluding the 'hash' field."""
    payload = {k: v for k, v in event.items() if k != "hash"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_last_hash(path: Path) -> str | None:
    """Return the hash of the last event in the ledger, or None if empty."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    last_hash = None
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
                last_hash = event.get("hash")
            except json.JSONDecodeError:
                pass
    return last_hash


def new_event_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def append_event(path: str | Path, event: dict[str, Any]) -> dict[str, Any]:
    """Append one event to the ledger. Fills prev_hash and hash in-place."""
    p = Path(path)
    prev_hash = _read_last_hash(p)

    event = dict(event)
    event["prev_hash"] = prev_hash
    event["hash"] = _sha256(_canonical_bytes(event))

    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    return event


def build_event(
    event_type: str,
    source_agent: str,
    *,
    session_id: str | None = None,
    cwd: str | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    """Build a base ledger event dict (without hash fields)."""
    ev: dict[str, Any] = {
        "schema_version": 1,
        "event_id": new_event_id(),
        "ts": now_iso(),
        "source": {"agent": source_agent, "collector": "agent-loop"},
        "event_type": event_type,
    }
    if session_id or cwd:
        ev["session"] = {}
        if session_id:
            ev["session"]["session_id"] = session_id
        if cwd:
            ev["session"]["cwd"] = cwd
    if extra:
        ev.update(extra)
    return ev

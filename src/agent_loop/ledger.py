"""Append-only JSONL ledger writer with hash-chain support."""

import hashlib
import json
import os
import sys
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from warnings import warn

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows only.
    fcntl = None


class LedgerAppendError(ValueError):
    """Raised when appending would extend an invalid ledger."""


_LAST_HASH_CACHE: dict[Path, tuple[int, str | None]] = {}
_PATH_LOCKS: dict[Path, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


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


def _thread_lock_for(path: Path) -> threading.Lock:
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(path, threading.Lock())


def _last_nonempty_line(f) -> bytes | None:
    f.seek(0, os.SEEK_END)
    pos = f.tell()
    if pos == 0:
        return None

    buffer = b""
    block_size = 8192
    while pos > 0:
        read_size = min(block_size, pos)
        pos -= read_size
        f.seek(pos)
        buffer = f.read(read_size) + buffer
        lines = buffer.split(b"\n")
        candidates = lines if pos == 0 else lines[1:]
        for line in reversed(candidates):
            if line.strip():
                return line
    return None


def _read_last_hash_locked(f, path: Path) -> str | None:
    """Return the last event hash from a locked ledger file."""
    f.seek(0, os.SEEK_END)
    size = f.tell()
    cached = _LAST_HASH_CACHE.get(path)
    if cached and cached[0] == size:
        return cached[1]

    raw = _last_nonempty_line(f)
    if raw is None:
        _LAST_HASH_CACHE[path] = (size, None)
        return None

    try:
        event = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LedgerAppendError(f"Cannot append to malformed ledger: {exc}") from exc

    if not isinstance(event, dict):
        raise LedgerAppendError("Cannot append to malformed ledger: last JSONL value is not an object")

    last_hash = event.get("hash")
    if not isinstance(last_hash, str) or not last_hash:
        raise LedgerAppendError("Cannot append to malformed ledger: last event is missing 'hash'")

    _LAST_HASH_CACHE[path] = (size, last_hash)
    return last_hash


def new_event_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def append_event(path: str | Path, event: dict[str, Any]) -> dict[str, Any]:
    """Append one event to the ledger. Fills prev_hash and hash in-place."""
    p = Path(path)
    cache_path = p.resolve(strict=False)
    event = dict(event)

    with _thread_lock_for(cache_path):
        with p.open("a+b") as f:
            if fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            elif sys.platform == "win32":  # pragma: no cover - exercised on Windows only.
                warn(
                    "fcntl is unavailable; ledger appends use best-effort locking on Windows",
                    RuntimeWarning,
                    stacklevel=2,
                )

            try:
                prev_hash = _read_last_hash_locked(f, cache_path)
                event["prev_hash"] = prev_hash
                event["hash"] = _sha256(_canonical_bytes(event))

                encoded = (json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8")
                f.seek(0, os.SEEK_END)
                f.write(encoded)
                f.flush()
                os.fsync(f.fileno())
                _LAST_HASH_CACHE[cache_path] = (f.tell(), event["hash"])
            finally:
                if fcntl is not None:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

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

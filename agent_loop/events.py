"""Ledger event helpers."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from hashlib import sha256
from typing import Any, Dict


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(event: Dict[str, Any]) -> str:
    body = {k: v for k, v in event.items() if k != "hash"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def event_hash(event: Dict[str, Any]) -> str:
    return sha256(canonical_json(event).encode("utf-8")).hexdigest()


def complete_event(event: Dict[str, Any], prev_hash: str | None) -> Dict[str, Any]:
    complete = dict(event)
    complete.setdefault("schema_version", 1)
    complete.setdefault("event_id", str(uuid.uuid4()))
    complete.setdefault("ts", now_iso())
    complete.setdefault("source", {"agent": "agent-loop"})
    complete["prev_hash"] = prev_hash
    complete.pop("hash", None)
    complete["hash"] = event_hash(complete)
    return complete

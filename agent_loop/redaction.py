"""Regex redaction before ledger persistence."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def redact_event(event: Dict[str, Any], policy: Dict[str, Any]) -> Dict[str, Any]:
    redaction = policy.get("redaction", {})
    if not redaction.get("enabled", False):
        result = dict(event)
        result["redaction"] = {"applied": False, "patterns": []}
        return result
    patterns = redaction.get("patterns", [])
    matched: List[str] = []
    redacted = _redact_value(event, patterns, matched)
    redacted["redaction"] = {"applied": bool(matched), "patterns": sorted(set(matched))}
    return redacted


def _redact_value(value: Any, patterns: List[Dict[str, str]], matched: List[str]) -> Any:
    if isinstance(value, dict):
        return {k: _redact_value(v, patterns, matched) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_value(item, patterns, matched) for item in value]
    if not isinstance(value, str):
        return value

    result = value
    for pattern in patterns:
        name = pattern.get("name", "unnamed")
        regex = pattern.get("regex", "")
        replacement = _python_replacement(pattern.get("replacement", "[REDACTED]"))
        try:
            compiled = re.compile(regex)
        except re.error:
            continue
        result, count = compiled.subn(replacement, result)
        if count:
            matched.append(name)
    return result


def _python_replacement(replacement: str) -> str:
    return re.sub(r"\$(\d+)", r"\\\1", replacement)

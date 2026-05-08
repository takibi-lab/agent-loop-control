"""Small YAML loader with a no-dependency fallback for the sample policy format."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


def load_yaml(text: str) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception:
        return _parse_subset(text)
    loaded = yaml.safe_load(text)
    return loaded or {}


def load_yaml_file(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return load_yaml(fh.read())


def _parse_subset(text: str) -> Dict[str, Any]:
    root: Dict[str, Any] = {}
    stack: List[Tuple[int, Any]] = [(-1, root)]
    prepared = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if line.strip():
            prepared.append(line)

    for index, line in enumerate(prepared):
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if content.startswith("- "):
            item_text = content[2:]
            if not isinstance(parent, list):
                raise ValueError(f"list item without list parent: {line}")
            if ": " in item_text or item_text.endswith(":"):
                key, value = _split_key_value(item_text)
                item: Dict[str, Any] = {key: value}
                parent.append(item)
                stack.append((indent, item))
            else:
                parent.append(_scalar(item_text))
            continue

        key, value = _split_key_value(content)
        if value is not None:
            parent[key] = value
            continue

        next_container = _next_container(prepared, index, indent)
        if isinstance(parent, dict):
            parent[key] = next_container
        stack.append((indent, next_container))

    _fix_containers(root)
    return root


def _next_container(lines: List[str], index: int, indent: int) -> Any:
    for candidate in lines[index + 1 :]:
        candidate_indent = len(candidate) - len(candidate.lstrip(" "))
        if candidate_indent <= indent:
            return {}
        return [] if candidate.strip().startswith("- ") else {}
    return {}


def _split_key_value(content: str) -> Tuple[str, Any]:
    if ":" not in content:
        raise ValueError(f"expected key/value pair: {content}")
    key, rest = content.split(":", 1)
    rest = rest.strip()
    if rest == "":
        return key.strip(), None
    return key.strip(), _scalar(rest)


def _scalar(value: str) -> Any:
    value = value.strip()
    if value in {"true", "false"}:
        return value == "true"
    if value in {"null", "~"}:
        return None
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        return value


def _fix_containers(value: Any) -> Any:
    if isinstance(value, dict):
        for key, child in list(value.items()):
            if isinstance(child, list) and child and all(isinstance(i, dict) for i in child):
                value[key] = [_fix_containers(i) for i in child]
            elif isinstance(child, list):
                value[key] = [_fix_containers(i) for i in child]
            elif isinstance(child, dict):
                value[key] = _fix_containers(child)
    return value

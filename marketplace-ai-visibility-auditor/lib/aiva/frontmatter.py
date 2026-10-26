"""Minimal YAML-frontmatter reader for SKILL.md files.

Only the subset the Agent Skills spec uses is supported: a flat mapping of
scalars, one level of nested mapping (for ``metadata``), multi-line plain
scalars (continuation lines indented under the key) and ``|`` / ``>`` block
scalars. That keeps the marketplace dependency-free while still letting it
validate itself.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

DELIMITER = re.compile(r"^---\s*$")
KEY_LINE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_.-]+):(?P<rest>.*)$")


def split(text: str) -> Tuple[Optional[str], str]:
    """Return ``(frontmatter_text, body)``; frontmatter is ``None`` if absent."""
    lines = (text or "").splitlines()
    if not lines or not DELIMITER.match(lines[0]):
        return None, text or ""
    for index in range(1, len(lines)):
        if DELIMITER.match(lines[index]):
            return "\n".join(lines[1:index]), "\n".join(lines[index + 1:])
    return None, text or ""


def _clean_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def parse_mapping(text: str) -> Dict[str, Any]:
    """Parse the supported YAML subset into a dict."""
    result: Dict[str, Any] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        match = KEY_LINE.match(line)
        if not match or match.group("indent"):
            index += 1
            continue
        key = match.group("key")
        rest = match.group("rest").strip()
        index += 1

        if rest in ("|", ">", "|-", ">-", "|+", ">+"):
            block: List[str] = []
            while index < len(lines) and (not lines[index].strip() or
                                          lines[index].startswith((" ", "\t"))):
                block.append(lines[index].strip())
                index += 1
            joiner = "\n" if rest.startswith("|") else " "
            result[key] = joiner.join(part for part in block).strip()
            continue

        if rest == "":
            # Either a nested mapping, a list, or an empty value.
            nested: Dict[str, str] = {}
            items: List[str] = []
            while index < len(lines) and (not lines[index].strip() or
                                          lines[index].startswith((" ", "\t"))):
                child = lines[index].strip()
                index += 1
                if not child:
                    continue
                if child.startswith("- "):
                    items.append(_clean_scalar(child[2:]))
                    continue
                child_match = KEY_LINE.match(child)
                if child_match:
                    nested[child_match.group("key")] = _clean_scalar(child_match.group("rest"))
            if items:
                result[key] = items
            elif nested:
                result[key] = nested
            else:
                result[key] = ""
            continue

        # Plain scalar, possibly continued on more-indented following lines.
        parts = [_clean_scalar(rest)]
        while index < len(lines) and lines[index].startswith((" ", "\t")) and lines[index].strip():
            parts.append(lines[index].strip())
            index += 1
        result[key] = " ".join(parts).strip()
    return result


def load(text: str) -> Tuple[Dict[str, Any], str]:
    """Return ``(frontmatter_mapping, body)``."""
    raw, body = split(text)
    if raw is None:
        return {}, body
    return parse_mapping(raw), body

from __future__ import annotations

import re

EXCLUDED_LABELS: frozenset[str] = frozenset({
    "Notes",
    "Deleted Items",
    "Sent Items",
    "Junk E-mail",
    "Sync Issues",
    "Conflicts",
    "Local Failures",
    "Server Failures",
})

_WHITESPACE_RUN = re.compile(r"\s+")
_NON_CONFORMING = re.compile(r"[^a-z0-9_-]")


def should_skip(name: str, extra: frozenset[str] = frozenset()) -> bool:
    if name.startswith("_"):
        return True
    if name in EXCLUDED_LABELS:
        return True
    if name in extra:
        return True
    return False


def normalize_label(name: str) -> str:
    trimmed = name.strip()
    lowered = trimmed.lower()
    hyphenated = _WHITESPACE_RUN.sub("-", lowered)
    return _NON_CONFORMING.sub("", hyphenated)

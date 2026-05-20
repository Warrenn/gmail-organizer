from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping

_EMAIL_RE = re.compile(r"<\s*([^<>@\s]+@[^<>@\s]+)\s*>")
_PLAIN_EMAIL_RE = re.compile(r"^\s*([^<>@\s]+@[^<>@\s]+)\s*$")


def year_slice_queries(start_year: int, end_year: int) -> list[str]:
    if start_year > end_year:
        raise ValueError(f"start_year {start_year} > end_year {end_year}")
    return [
        f"after:{y}/01/01 before:{y + 1}/01/01"
        for y in range(start_year, end_year + 1)
    ]


def parse_from_header(value: str) -> str:
    if not value:
        return ""
    m = _EMAIL_RE.search(value)
    if m:
        return m.group(1).lower()
    m = _PLAIN_EMAIL_RE.match(value)
    if m:
        return m.group(1).lower()
    return ""


def tally_senders(messages: Iterable[Mapping[str, str]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for msg in messages:
        from_value = msg.get("From")
        if not from_value:
            continue
        email = parse_from_header(from_value)
        if email:
            counter[email] += 1
    return dict(counter)


def top_senders(tally: Mapping[str, int], n: int) -> list[tuple[str, int]]:
    return sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


def extract_headers(message_payload: Mapping) -> dict[str, str]:
    headers = message_payload.get("payload", {}).get("headers", [])
    canonical = {"from": "From", "subject": "Subject", "date": "Date", "list-unsubscribe": "List-Unsubscribe"}
    out: dict[str, str] = {}
    for h in headers:
        name = h.get("name", "")
        key = canonical.get(name.lower(), name)
        out[key] = h.get("value", "")
    return out

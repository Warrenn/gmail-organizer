from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError

from gmail_cleanup.sampling import (
    extract_headers,
    parse_from_header,
    tally_senders,
    top_senders,
)

DEFAULT_PER_YEAR_CAP = 100
DEFAULT_MAX_TOTAL = 1500
DEFAULT_START_YEAR_FLOOR = 1998  # Gmail launched in 2004; allow earlier imports just in case


def compose_year_query(extra: str, year: int) -> str:
    base = f"after:{year}/01/01 before:{year + 1}/01/01"
    extra = extra.strip()
    if extra:
        return f"({extra}) {base}"
    return base


def _retry(call: Callable[[], Any], max_retries: int = 5) -> Any:
    delay = 1.0
    for attempt in range(max_retries + 1):
        try:
            return call()
        except HttpError as e:
            status = getattr(e.resp, "status", 0)
            if attempt == max_retries or status not in (429, 500, 502, 503, 504):
                raise
            print(f"  [retry] HTTP {status} — sleeping {delay}s", file=sys.stderr)
            time.sleep(delay)
            delay *= 2
        except (TimeoutError, ConnectionError, OSError) as e:
            if attempt == max_retries:
                raise
            print(f"  [retry] network error {type(e).__name__}: {e} — sleeping {delay}s", file=sys.stderr)
            time.sleep(delay)
            delay *= 2


def list_existing_labels(service) -> list[dict]:
    resp = _retry(lambda: service.users().labels().list(userId="me").execute())
    return resp.get("labels", [])


def list_message_ids_for_query(service, query: str, max_results: int) -> list[str]:
    ids: list[str] = []
    page_token: str | None = None
    while len(ids) < max_results:
        page_size = min(500, max_results - len(ids))
        resp = _retry(
            lambda: service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                includeSpamTrash=False,
                maxResults=page_size,
                pageToken=page_token,
            )
            .execute()
        )
        for m in resp.get("messages", []):
            ids.append(m["id"])
            if len(ids) >= max_results:
                break
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


def fetch_metadata(service, msg_id: str) -> dict:
    return _retry(
        lambda: service.users()
        .messages()
        .get(
            userId="me",
            id=msg_id,
            format="metadata",
            metadataHeaders=["From", "Subject", "Date", "List-Unsubscribe"],
        )
        .execute()
    )


def detect_year_range(service, floor: int = DEFAULT_START_YEAR_FLOOR, extra_query: str = "") -> tuple[int, int]:
    """Return (oldest_year_with_mail, current_year). One cheap probe per year."""
    current_year = datetime.now(timezone.utc).year
    for year in range(floor, current_year + 1):
        query = compose_year_query(extra_query, year)
        resp = _retry(
            lambda: service.users()
            .messages()
            .list(userId="me", q=query, includeSpamTrash=False, maxResults=1)
            .execute()
        )
        if resp.get("messages"):
            return year, current_year
    return current_year, current_year


def run_discover(
    service,
    output_path: Path,
    account: str,
    per_year_cap: int = DEFAULT_PER_YEAR_CAP,
    max_total: int = DEFAULT_MAX_TOTAL,
    extra_query: str = "",
) -> dict:
    print(f"[discover] starting for {account}", file=sys.stderr)
    if extra_query:
        print(f"[discover] extra query filter: {extra_query}", file=sys.stderr)
    print("[discover] listing existing labels…", file=sys.stderr)
    labels = list_existing_labels(service)
    user_labels = [
        {"id": l["id"], "name": l["name"], "type": l.get("type", "user")}
        for l in labels
        if l.get("type") == "user"
    ]
    print(f"[discover] found {len(user_labels)} user-created labels", file=sys.stderr)

    print("[discover] detecting mailbox year range…", file=sys.stderr)
    start_year, end_year = detect_year_range(service, extra_query=extra_query)
    print(f"[discover] earliest mail: {start_year}, current: {end_year}", file=sys.stderr)

    queries = [compose_year_query(extra_query, y) for y in range(start_year, end_year + 1)]

    sample: list[dict] = []
    per_year_counts: dict[int, int] = {}

    for q, year in zip(queries, range(start_year, end_year + 1)):
        if len(sample) >= max_total:
            print(f"[discover] hit max_total={max_total}, stopping early", file=sys.stderr)
            break
        remaining = max_total - len(sample)
        cap = min(per_year_cap, remaining)
        print(f"[discover] {year}: listing up to {cap} ids ({q})", file=sys.stderr)
        ids = list_message_ids_for_query(service, q, cap)
        print(f"[discover] {year}: got {len(ids)} ids, fetching metadata…", file=sys.stderr)
        added = 0
        for i, mid in enumerate(ids, 1):
            try:
                msg = fetch_metadata(service, mid)
            except HttpError as e:
                print(f"  [skip] {mid}: {e}", file=sys.stderr)
                continue
            headers = extract_headers(msg)
            sample.append(
                {
                    "id": mid,
                    "threadId": msg.get("threadId"),
                    "year": year,
                    "From": headers.get("From", ""),
                    "FromEmail": parse_from_header(headers.get("From", "")),
                    "Subject": headers.get("Subject", ""),
                    "Date": headers.get("Date", ""),
                    "ListUnsubscribe": headers.get("List-Unsubscribe", ""),
                }
            )
            added += 1
            if i % 25 == 0:
                print(f"    {i}/{len(ids)} fetched", file=sys.stderr)
        per_year_counts[year] = added
        print(f"[discover] {year}: added {added} to sample (total {len(sample)})", file=sys.stderr)

    histogram = tally_senders([{"From": s["From"]} for s in sample])
    top = top_senders(histogram, n=50)

    output = {
        "account": account,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "year_range": [start_year, end_year],
        "per_year_counts": per_year_counts,
        "existing_labels": user_labels,
        "sample_size": len(sample),
        "sample": sample,
        "sender_histogram": histogram,
        "top_senders": top,
    }
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print(f"[discover] wrote {output_path} ({len(sample)} threads sampled, {len(histogram)} unique senders)", file=sys.stderr)
    return output

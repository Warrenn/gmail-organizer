from __future__ import annotations

import sys
import time
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError

from gmail_cleanup.apply import apply_labels_batched

BATCH_SIZE = 1000


def extract_leaf_name(nested_label: str) -> str:
    return nested_label.rsplit("/", 1)[-1]


def extract_parent_name(nested_label: str) -> str:
    if "/" not in nested_label:
        return ""
    return nested_label.rsplit("/", 1)[0]


def plan_flatten_operations(nested_labels: list[dict]) -> list[dict]:
    ops: list[dict] = []
    for label in nested_labels:
        name = label.get("name", "")
        if "/" not in name:
            continue
        ops.append(
            {
                "nested_id": label["id"],
                "nested_name": name,
                "leaf": extract_leaf_name(name),
                "parent": extract_parent_name(name),
            }
        )
    return ops


def identify_leaf_collisions(nested_labels: list[dict]) -> dict[str, list[str]]:
    by_leaf: dict[str, list[str]] = defaultdict(list)
    for label in nested_labels:
        name = label.get("name", "")
        if "/" not in name:
            continue
        by_leaf[extract_leaf_name(name)].append(name)
    return {leaf: nested for leaf, nested in by_leaf.items() if len(nested) > 1}


def identify_existing_flat_overlaps(
    nested_labels: list[dict], existing_flat_names: set[str]
) -> dict[str, str]:
    """Case-insensitive — Gmail label uniqueness is case-insensitive."""
    existing_cf = {n.casefold() for n in existing_flat_names}
    overlaps: dict[str, str] = {}
    for label in nested_labels:
        name = label.get("name", "")
        if "/" not in name:
            continue
        leaf = extract_leaf_name(name)
        if leaf.casefold() in existing_cf:
            overlaps[leaf] = name
    return overlaps


def find_case_insensitive(name_to_id: dict[str, str], name: str) -> str | None:
    name_cf = name.casefold()
    for existing_name, existing_id in name_to_id.items():
        if existing_name.casefold() == name_cf:
            return existing_id
    return None


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


def list_all_labels(service) -> list[dict]:
    resp = _retry(lambda: service.users().labels().list(userId="me").execute())
    return resp.get("labels", [])


def list_nested_user_labels(service) -> list[dict]:
    return [
        l for l in list_all_labels(service)
        if l.get("type") == "user" and "/" in l.get("name", "")
    ]


def list_message_ids_with_label(service, label_id: str) -> list[str]:
    ids: list[str] = []
    page_token: str | None = None
    while True:
        resp = _retry(
            lambda: service.users()
            .messages()
            .list(
                userId="me",
                labelIds=[label_id],
                maxResults=500,
                pageToken=page_token,
            )
            .execute()
        )
        for m in resp.get("messages", []):
            ids.append(m["id"])
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return ids


def ensure_flat_label(service, name: str, name_to_id: dict[str, str]) -> str:
    existing_id = find_case_insensitive(name_to_id, name)
    if existing_id is not None:
        return existing_id
    body = {
        "name": name,
        "messageListVisibility": "show",
        "labelListVisibility": "labelShow",
    }
    try:
        label = _retry(lambda: service.users().labels().create(userId="me", body=body).execute())
    except HttpError as e:
        if getattr(e.resp, "status", 0) == 409:
            # Stale cache or hidden conflict — re-list and find
            resp = _retry(lambda: service.users().labels().list(userId="me").execute())
            for l in resp.get("labels", []):
                if l["name"].casefold() == name.casefold():
                    name_to_id[l["name"]] = l["id"]
                    print(f"  [recovered after 409] reusing {l['name']} ({l['id']})", file=sys.stderr)
                    return l["id"]
        raise
    name_to_id[name] = label["id"]
    print(f"  [created flat] {name}", file=sys.stderr)
    return label["id"]


def delete_label(service, label_id: str) -> None:
    _retry(lambda: service.users().labels().delete(userId="me", id=label_id).execute())


def run_flatten(service) -> dict:
    print("[flatten] inventory…", file=sys.stderr)
    all_labels = list_all_labels(service)
    user_labels = [l for l in all_labels if l.get("type") == "user"]
    nested = [l for l in user_labels if "/" in l.get("name", "")]
    flat = [l for l in user_labels if "/" not in l.get("name", "")]
    name_to_id: dict[str, str] = {l["name"]: l["id"] for l in user_labels}
    flat_names = {l["name"] for l in flat}

    print(f"[flatten] {len(nested)} nested user labels, {len(flat)} flat user labels", file=sys.stderr)

    leaf_collisions = identify_leaf_collisions(nested)
    if leaf_collisions:
        print(f"[flatten] leaf-name collisions (merge into single flat label):", file=sys.stderr)
        for leaf, names in leaf_collisions.items():
            print(f"    {leaf}: {names}", file=sys.stderr)

    flat_overlaps = identify_existing_flat_overlaps(nested, flat_names)
    if flat_overlaps:
        print(f"[flatten] existing flat overlaps (merge into existing):", file=sys.stderr)
        for leaf, nested_name in flat_overlaps.items():
            print(f"    {leaf}: from {nested_name}", file=sys.stderr)

    ops = plan_flatten_operations(nested)
    summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "nested_labels_processed": [],
        "flat_labels_created": [],
        "messages_relabeled_total": 0,
        "leaf_collisions": leaf_collisions,
        "flat_overlaps": list(flat_overlaps.keys()),
    }

    for i, op in enumerate(ops, 1):
        nested_name = op["nested_name"]
        nested_id = op["nested_id"]
        leaf = op["leaf"]
        print(f"[flatten] {i}/{len(ops)} {nested_name} → {leaf}", file=sys.stderr)

        pre_existed = leaf in name_to_id
        flat_id = ensure_flat_label(service, leaf, name_to_id)
        if not pre_existed:
            summary["flat_labels_created"].append(leaf)

        ids = list_message_ids_with_label(service, nested_id)
        print(f"    {len(ids)} messages with {nested_name}", file=sys.stderr)
        if ids:
            apply_labels_batched(service, ids, [flat_id])
        delete_label(service, nested_id)

        summary["nested_labels_processed"].append(
            {"nested": nested_name, "leaf": leaf, "messages": len(ids)}
        )
        summary["messages_relabeled_total"] += len(ids)

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    return summary

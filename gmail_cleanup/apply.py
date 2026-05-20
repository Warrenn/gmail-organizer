from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError


BATCH_SIZE = 1000
MAX_LIST_PAGE = 500


def chunks_of(items: list, size: int) -> Iterator[list]:
    if size <= 0:
        raise ValueError(f"chunk size must be > 0, got {size}")
    for i in range(0, len(items), size):
        yield items[i : i + size]


def resolve_label_ids_for_target(target: str, name_to_id: Mapping[str, str]) -> list[str]:
    if target not in name_to_id:
        raise KeyError(f"label not found: {target}")
    parts = target.split("/")
    ids: list[str] = []
    for depth in range(1, len(parts) + 1):
        ancestor = "/".join(parts[:depth])
        if ancestor not in name_to_id:
            raise KeyError(f"label not found: {ancestor} (ancestor of {target})")
        ids.append(name_to_id[ancestor])
    return ids


def compile_label_plan(
    leaf_queries: Mapping[str, str],
    subject_queries: Mapping[str, str],
    name_to_id: Mapping[str, str],
) -> list[dict]:
    plan: list[dict] = []
    for label_name, query in leaf_queries.items():
        try:
            label_ids = resolve_label_ids_for_target(label_name, name_to_id)
        except KeyError as e:
            print(f"  [skip] {e}", file=sys.stderr)
            continue
        plan.append({"label_name": label_name, "query": query, "label_ids": label_ids})
    for label_name, query in subject_queries.items():
        try:
            label_ids = resolve_label_ids_for_target(label_name, name_to_id)
        except KeyError as e:
            print(f"  [skip] {e}", file=sys.stderr)
            continue
        plan.append({"label_name": label_name, "query": query, "label_ids": label_ids})
    return plan


def load_progress(path: Path) -> dict:
    if not path.exists():
        return {"started_at": None, "completed": {}}
    return json.loads(path.read_text())


def save_progress(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2))


def filter_plan_by_progress(plan: list[dict], progress: dict) -> list[dict]:
    completed = set(progress.get("completed", {}).keys())
    return [item for item in plan if item["label_name"] not in completed]


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


def list_all_messages(service, query: str) -> list[str]:
    ids: list[str] = []
    page_token: str | None = None
    while True:
        resp = _retry(
            lambda: service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                includeSpamTrash=False,
                maxResults=MAX_LIST_PAGE,
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


def apply_labels_batched(service, ids: list[str], label_ids: list[str]) -> None:
    for chunk in chunks_of(ids, BATCH_SIZE):
        _retry(
            lambda chunk=chunk: service.users()
            .messages()
            .batchModify(
                userId="me",
                body={"ids": chunk, "addLabelIds": list(label_ids)},
            )
            .execute()
        )


def run_apply(service, plan: list[dict], progress_path: Path) -> dict:
    progress = load_progress(progress_path)
    if progress.get("started_at") is None:
        progress["started_at"] = datetime.now(timezone.utc).isoformat()
    remaining = filter_plan_by_progress(plan, progress)
    skipped = len(plan) - len(remaining)
    if skipped:
        print(f"[apply] skipping {skipped} already-completed labels from progress.json", file=sys.stderr)

    total_messages_labeled = 0
    for item in remaining:
        label_name = item["label_name"]
        query = item["query"]
        label_ids = item["label_ids"]
        print(f"[apply] {label_name}: listing messages matching `{query}`…", file=sys.stderr)
        ids = list_all_messages(service, query)
        print(f"[apply] {label_name}: {len(ids)} message(s) match. Applying labels…", file=sys.stderr)
        if ids:
            apply_labels_batched(service, ids, label_ids)
        progress["completed"][label_name] = {
            "count": len(ids),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        save_progress(progress_path, progress)
        total_messages_labeled += len(ids)
        print(f"[apply] {label_name}: done ({len(ids)} labeled)", file=sys.stderr)

    progress["finished_at"] = datetime.now(timezone.utc).isoformat()
    save_progress(progress_path, progress)

    summary = {
        "labels_processed": len(remaining),
        "labels_skipped_already_done": skipped,
        "total_messages_labeled_this_run": total_messages_labeled,
        "per_label": {
            name: info["count"] for name, info in progress["completed"].items()
        },
        "progress_path": str(progress_path),
    }
    return summary

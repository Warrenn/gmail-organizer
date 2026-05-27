from __future__ import annotations

from datetime import datetime, timezone

from gmail_cleanup import rule_interpreter


def message_to_corpus_entry(message: dict, label_id_to_name: dict[str, str]) -> dict:
    headers = {h["name"]: h["value"] for h in (message.get("payload", {}).get("headers") or [])}
    label_ids = message.get("labelIds") or []
    expected_labels: list[str] = []
    seen: set[str] = set()
    for lid in label_ids:
        name = label_id_to_name.get(lid)
        if name and name not in seen:
            expected_labels.append(name)
            seen.add(name)
    return {
        "thread_id": message.get("threadId", ""),
        "message_id": message.get("id", ""),
        "from": headers.get("From", ""),
        "subject": headers.get("Subject", ""),
        "snippet": message.get("snippet", ""),
        "expected_labels": expected_labels,
    }


def select_thread_sample(items: list, n: int) -> list:
    if n <= 0:
        return []
    return list(items[:n])


def _list_user_labels(service) -> list[dict]:
    resp = service.users().labels().list(userId="me").execute()
    return [l for l in resp.get("labels", []) if l.get("type") == "user"]


def _list_message_ids_for_label(service, label_id: str, max_results: int) -> list[str]:
    """Gmail messages.list supports filtering by labelIds (server-side) — use that
    instead of a `label:` text query, which is brittle around label-name aliasing."""
    resp = service.users().messages().list(
        userId="me",
        labelIds=[label_id],
        maxResults=max_results,
    ).execute()
    return [m["id"] for m in resp.get("messages", [])]


def _get_message(service, message_id: str) -> dict:
    return service.users().messages().get(
        userId="me",
        id=message_id,
        format="metadata",
        metadataHeaders=["From", "Subject"],
    ).execute()


def build_corpus(
    service,
    per_label_sample_size: int = 5,
    exclude_labels: set[str] | None = None,
) -> dict:
    exclude_labels = exclude_labels or set()
    user_labels = _list_user_labels(service)
    label_id_to_name = {l["id"]: l["name"] for l in user_labels}

    threads_by_id: dict[str, dict] = {}

    for label in user_labels:
        if label["name"] in exclude_labels:
            continue
        msg_ids = _list_message_ids_for_label(service, label["id"], max_results=per_label_sample_size)
        sample = select_thread_sample(msg_ids, per_label_sample_size)
        for mid in sample:
            if any(t["message_id"] == mid for t in threads_by_id.values()):
                continue
            msg = _get_message(service, mid)
            entry = message_to_corpus_entry(msg, label_id_to_name)
            threads_by_id[entry["thread_id"]] = entry

    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "threads": list(threads_by_id.values()),
    }


def filter_to_agreement(corpus_data: dict, spec: dict) -> tuple[dict, list[dict]]:
    """Filter a raw corpus to threads where the interpreter's output matches
    the recorded expected_labels (set-equality, order-insensitive).

    Returns (filtered_corpus, disagreements).
    Each disagreement entry is the original thread plus an `interpreter_output`
    field showing what the interpreter produced — used as a TODO list for
    rule refinement.
    """
    kept: list[dict] = []
    disagreements: list[dict] = []
    for thread in corpus_data.get("threads", []):
        actual = sorted(rule_interpreter.classify(thread, spec))
        expected = sorted(thread.get("expected_labels", []))
        if actual == expected:
            kept.append(thread)
        else:
            disagreements.append({**thread, "interpreter_output": actual})
    return ({**corpus_data, "threads": kept}, disagreements)

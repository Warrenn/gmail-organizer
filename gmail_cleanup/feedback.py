from __future__ import annotations

from datetime import datetime, timezone

from gmail_cleanup import normalize


def parse_marker_label(name: str) -> tuple[str, str] | None:
    """Parse a marker label like '+receipts' or '-newsletters'.

    Returns (sign, target_label) where sign is '+' or '-' and target_label
    is the project-convention-normalized label name. Returns None if the
    input is not a marker label (no leading +/-, or only the prefix).

    Underscore-prefixed labels are NOT markers — the leading character
    distinguishes them.
    """
    if not name or name[0] not in ("+", "-"):
        return None
    sign = name[0]
    rest = name[1:].strip()
    if not rest:
        return None
    target = normalize.normalize_label(rest)
    if not target:
        return None
    return sign, target


def _list_user_labels(service) -> list[dict]:
    resp = service.users().labels().list(userId="me").execute()
    return [l for l in resp.get("labels", []) if l.get("type") == "user"]


def _list_message_ids_for_label(service, label_id: str, max_results: int = 200) -> list[str]:
    """Return up to `max_results` message IDs for the given label.

    This paginates over the Gmail `users.messages.list` API using `nextPageToken`
    until either `max_results` messages have been collected or there are no more
    pages to fetch.
    """
    message_ids: list[str] = []
    page_token: str | None = None

    while len(message_ids) < max_results:
        # Gmail API allows up to 500 per page; respect that and our remaining budget.
        page_size = min(500, max_results - len(message_ids))
        resp = (
            service.users()
            .messages()
            .list(
                userId="me",
                labelIds=[label_id],
                maxResults=page_size,
                pageToken=page_token,
            )
            .execute()
        )

        for m in resp.get("messages", []) or []:
            message_ids.append(m["id"])

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return message_ids


def _get_message(service, message_id: str) -> dict:
    return service.users().messages().get(
        userId="me",
        id=message_id,
        format="metadata",
        metadataHeaders=["From", "Subject"],
    ).execute()


def _message_to_thread_record(message: dict) -> dict:
    headers = {h["name"]: h["value"] for h in (message.get("payload", {}).get("headers") or [])}
    return {
        "thread_id": message.get("threadId", ""),
        "message_id": message.get("id", ""),
        "from": headers.get("From", ""),
        "subject": headers.get("Subject", ""),
        "snippet": message.get("snippet", ""),
    }


def scan_for_markers(service) -> dict:
    """Scan the mailbox for +X / -X marker labels and dump them with
    per-thread metadata. Produces the feedback.json the autonomous Claude
    session reads.
    """
    user_labels = _list_user_labels(service)

    markers: list[dict] = []
    existing_labels: list[str] = []

    for label in user_labels:
        name = label.get("name", "")
        parsed = parse_marker_label(name)
        if parsed is None:
            existing_labels.append(name)
            continue
        sign, target = parsed
        msg_ids = _list_message_ids_for_label(service, label["id"])
        threads_seen: set[str] = set()
        thread_records: list[dict] = []
        for mid in msg_ids:
            msg = _get_message(service, mid)
            record = _message_to_thread_record(msg)
            if record["thread_id"] in threads_seen:
                continue
            threads_seen.add(record["thread_id"])
            thread_records.append(record)
        markers.append({
            "label_name": name,
            "label_id": label["id"],
            "sign": sign,
            "target_label": target,
            "threads": thread_records,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "markers": markers,
        "existing_labels": sorted(existing_labels),
    }

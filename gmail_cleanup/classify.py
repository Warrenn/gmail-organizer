from __future__ import annotations

import json
import sys
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from gmail_cleanup.apply import _retry, apply_labels_batched, list_all_messages
from gmail_cleanup.flatten import list_all_labels
from gmail_cleanup.sampling import extract_headers


UNLABELED_QUERY = "-has:userlabels"


def list_unlabeled_message_ids(service) -> list[str]:
    return list_all_messages(service, UNLABELED_QUERY)


def fetch_metadata_and_snippet(service, msg_id: str) -> dict:
    msg = _retry(
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
    headers = extract_headers(msg)
    return {
        "id": msg_id,
        "threadId": msg.get("threadId"),
        "labelIds": msg.get("labelIds", []),
        "snippet": msg.get("snippet", "")[:300],
        "from": headers.get("From", ""),
        "subject": headers.get("Subject", ""),
        "date": headers.get("Date", ""),
        "listUnsubscribe": headers.get("List-Unsubscribe", ""),
    }


def export_for_classification(service, output_path: Path) -> dict:
    ids = list_unlabeled_message_ids(service)
    print(f"[classify-export] {len(ids)} unlabeled messages", file=sys.stderr)
    items: list[dict] = []
    for i, mid in enumerate(ids, 1):
        items.append(fetch_metadata_and_snippet(service, mid))
        if i % 50 == 0 or i == len(ids):
            print(f"  fetched {i}/{len(ids)}", file=sys.stderr)
    all_labels = list_all_labels(service)
    available = sorted({l["name"] for l in all_labels if l.get("type") == "user"})
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "available_labels": available,
        "messages": items,
    }
    output_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"[classify-export] wrote {output_path} ({len(items)} messages, {len(available)} available labels)", file=sys.stderr)
    return data


def group_by_label_set(classification: Mapping[str, list[str]]) -> dict[tuple[str, ...], list[str]]:
    grouped: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for msg_id, labels in classification.items():
        key = tuple(sorted(set(labels)))
        if not key:
            continue
        grouped[key].append(msg_id)
    return dict(grouped)


def resolve_label_names_to_ids(label_names: list[str], name_to_id: Mapping[str, str]) -> list[str]:
    out: list[str] = []
    name_to_id_cf = {n.casefold(): id_ for n, id_ in name_to_id.items()}
    seen: set[str] = set()
    for name in label_names:
        lid = name_to_id.get(name) or name_to_id_cf.get(name.casefold())
        if lid and lid not in seen:
            out.append(lid)
            seen.add(lid)
    return out


def validate_classification(
    classification: Mapping[str, list[str]],
    dump: Mapping,
) -> tuple[dict[str, list[str]], list[str]]:
    """Strip unknown labels and unknown message IDs. Return (valid, [invalid_ids_and_unknown_labels])."""
    known_ids = {m["id"] for m in dump.get("messages", [])}
    available = set(dump.get("available_labels", []))
    available_cf = {a.casefold() for a in available}

    valid: dict[str, list[str]] = {}
    invalid: list[str] = []

    for msg_id, labels in classification.items():
        if msg_id not in known_ids:
            invalid.append(msg_id)
            continue
        filtered: list[str] = []
        for lbl in labels:
            if not available:
                filtered.append(lbl)
            elif lbl in available or lbl.casefold() in available_cf:
                filtered.append(lbl)
            else:
                invalid.append(f"{msg_id}:{lbl}")
        if filtered:
            valid[msg_id] = filtered
    return valid, invalid


def apply_classification(service, classification_path: Path, dump_path: Path) -> dict:
    dump = json.loads(dump_path.read_text())
    classification = json.loads(classification_path.read_text())
    valid, invalid = validate_classification(classification, dump)
    if invalid:
        print(f"[classify-apply] dropped {len(invalid)} invalid entries", file=sys.stderr)

    all_labels = list_all_labels(service)
    name_to_id = {l["name"]: l["id"] for l in all_labels if l.get("type") == "user"}

    grouped = group_by_label_set(valid)
    summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "messages_classified": len(valid),
        "messages_invalid": len(invalid),
        "label_application_counts": {},
        "groups": len(grouped),
    }

    for label_tuple, message_ids in grouped.items():
        label_ids = resolve_label_names_to_ids(list(label_tuple), name_to_id)
        if not label_ids:
            print(f"  [skip] no resolvable labels in {label_tuple}", file=sys.stderr)
            continue
        print(f"[classify-apply] applying {label_tuple} to {len(message_ids)} messages", file=sys.stderr)
        apply_labels_batched(service, message_ids, label_ids)
        for label_name in label_tuple:
            summary["label_application_counts"][label_name] = (
                summary["label_application_counts"].get(label_name, 0) + len(message_ids)
            )

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    return summary

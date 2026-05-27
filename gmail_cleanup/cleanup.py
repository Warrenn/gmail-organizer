from __future__ import annotations


def _list_existing_labels(service) -> dict[str, str]:
    resp = service.users().labels().list(userId="me").execute()
    return {l["name"]: l["id"] for l in resp.get("labels", []) if l.get("type") == "user"}


def _ensure_label_exists(service, name: str, existing: dict[str, str]) -> tuple[str, bool]:
    if name in existing:
        return existing[name], False
    resp = service.users().labels().create(
        userId="me",
        body={"name": name, "messageListVisibility": "show", "labelListVisibility": "labelShow"},
    ).execute()
    new_id = resp["id"]
    existing[name] = new_id
    return new_id, True


def cleanup_resolved_markers(service, resolved: list[dict]) -> dict:
    existing = _list_existing_labels(service)
    threads_modified = 0
    target_labels_created = 0
    marker_labels_deleted = 0
    errors: list[dict] = []

    for entry in resolved:
        marker_id = entry["marker_label_id"]
        marker_name = entry["marker_label_name"]
        sign = entry["sign"]
        target_name = entry["target_label_name"]
        thread_ids = entry.get("thread_ids") or []

        try:
            target_id, created = _ensure_label_exists(service, target_name, existing)
            if created:
                target_labels_created += 1
        except Exception as e:
            errors.append({
                "marker": marker_name,
                "stage": "ensure_target_label",
                "error": str(e),
            })
            continue

        for tid in thread_ids:
            try:
                if sign == "+":
                    body = {"addLabelIds": [target_id], "removeLabelIds": [marker_id]}
                else:  # sign == "-"
                    body = {"addLabelIds": [], "removeLabelIds": [target_id, marker_id]}
                service.users().threads().modify(userId="me", id=tid, body=body).execute()
                threads_modified += 1
            except Exception as e:
                errors.append({
                    "marker": marker_name,
                    "stage": "modify_thread",
                    "thread_id": tid,
                    "error": str(e),
                })

        try:
            service.users().labels().delete(userId="me", id=marker_id).execute()
            marker_labels_deleted += 1
        except Exception as e:
            errors.append({
                "marker": marker_name,
                "stage": "delete_marker",
                "error": str(e),
            })

    return {
        "markers_processed": len(resolved),
        "threads_modified": threads_modified,
        "target_labels_created": target_labels_created,
        "marker_labels_deleted": marker_labels_deleted,
        "errors": errors,
    }

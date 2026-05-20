from __future__ import annotations

import sys

from googleapiclient.errors import HttpError


def list_existing_label_names(service) -> dict[str, str]:
    resp = service.users().labels().list(userId="me").execute()
    return {l["name"]: l["id"] for l in resp.get("labels", [])}


def create_label(service, name: str) -> dict:
    body = {
        "name": name,
        "messageListVisibility": "show",
        "labelListVisibility": "labelShow",
    }
    return service.users().labels().create(userId="me", body=body).execute()


def create_missing_labels(service, target_labels: list[str]) -> dict:
    existing = list_existing_label_names(service)
    ordered = sorted(target_labels, key=lambda l: (l.count("/"), l))
    created: list[dict] = []
    skipped: list[str] = []
    errors: list[dict] = []
    for name in ordered:
        if name in existing:
            skipped.append(name)
            continue
        try:
            label = create_label(service, name)
            created.append({"name": name, "id": label["id"]})
            existing[name] = label["id"]
            print(f"  created: {name}", file=sys.stderr)
        except HttpError as e:
            errors.append({"name": name, "error": str(e)})
            print(f"  ERROR creating {name}: {e}", file=sys.stderr)
    return {"created": created, "skipped": skipped, "errors": errors}

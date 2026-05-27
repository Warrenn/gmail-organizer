from __future__ import annotations

from gmail_cleanup import apply, labels, normalize


def plan_renames(
    labels: list[dict],
    extra_excludes: frozenset[str] = frozenset(),
) -> dict:
    renames: list[dict] = []
    merges: list[dict] = []
    skipped: list[dict] = []

    candidates: list[dict] = []
    for label in labels:
        name = label["name"]
        label_id = label["id"]

        if name.startswith("_"):
            skipped.append({"id": label_id, "name": name, "reason": "underscore_prefix"})
            continue
        if name in normalize.EXCLUDED_LABELS or name in extra_excludes:
            skipped.append({"id": label_id, "name": name, "reason": "excluded"})
            continue

        candidates.append({
            "id": label_id,
            "name": name,
            "normalized": normalize.normalize_label(name),
        })

    groups: dict[str, list[dict]] = {}
    for c in candidates:
        groups.setdefault(c["normalized"], []).append(c)

    for normalized_name, members in groups.items():
        if len(members) == 1:
            m = members[0]
            if m["name"] == normalized_name:
                skipped.append({"id": m["id"], "name": m["name"], "reason": "already_conforming"})
            else:
                renames.append({"id": m["id"], "old_name": m["name"], "new_name": normalized_name})
            continue

        preferred = [m for m in members if m["name"].lower() == normalized_name]
        pool = preferred if preferred else members
        survivor = min(pool, key=lambda m: m["id"])

        if survivor["name"] == normalized_name:
            skipped.append({"id": survivor["id"], "name": survivor["name"], "reason": "already_conforming"})
        else:
            renames.append({"id": survivor["id"], "old_name": survivor["name"], "new_name": normalized_name})

        for m in members:
            if m["id"] == survivor["id"]:
                continue
            merges.append({
                "source_id": m["id"],
                "source_name": m["name"],
                "target_id": survivor["id"],
                "target_name": survivor["name"],
            })

    return {"renames": renames, "merges": merges, "skipped": skipped}


def apply_plan(service, plan: dict) -> dict:
    merge_details: list[dict] = []
    rename_details: list[dict] = []
    errors: list[dict] = []

    for merge in plan.get("merges", []):
        source_id = merge["source_id"]
        target_id = merge["target_id"]
        try:
            ids = apply.list_all_messages(service, f"label:{source_id}")
            if ids:
                apply.apply_labels_batched(service, ids, [target_id])
            labels.delete_label(service, source_id)
            merge_details.append({
                "source_id": source_id,
                "source_name": merge["source_name"],
                "target_id": target_id,
                "target_name": merge["target_name"],
                "messages_relabeled": len(ids),
            })
        except Exception as e:
            errors.append({
                "operation": "merge",
                "source_id": source_id,
                "error": str(e),
            })

    for ren in plan.get("renames", []):
        label_id = ren["id"]
        new_name = ren["new_name"]
        try:
            labels.update_label(service, label_id, new_name)
            rename_details.append({
                "id": label_id,
                "old_name": ren["old_name"],
                "new_name": new_name,
            })
        except Exception as e:
            errors.append({
                "operation": "rename",
                "id": label_id,
                "error": str(e),
            })

    return {
        "renames_applied": len(rename_details),
        "merges_applied": len(merge_details),
        "errors": errors,
        "merge_details": merge_details,
        "rename_details": rename_details,
    }

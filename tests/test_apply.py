from __future__ import annotations

import pytest

from gmail_cleanup import apply


def test_chunks_of_exact_multiple():
    assert list(apply.chunks_of([1, 2, 3, 4], 2)) == [[1, 2], [3, 4]]


def test_chunks_of_partial_final():
    assert list(apply.chunks_of([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]


def test_chunks_of_empty():
    assert list(apply.chunks_of([], 100)) == []


def test_chunks_of_smaller_than_size():
    assert list(apply.chunks_of([1, 2], 100)) == [[1, 2]]


def test_chunks_of_invalid_size():
    with pytest.raises(ValueError):
        list(apply.chunks_of([1, 2, 3], 0))
    with pytest.raises(ValueError):
        list(apply.chunks_of([1, 2, 3], -1))


def test_resolve_label_ids_leaf_returns_parent_and_self():
    name_to_id = {"Finance": "L_finance", "Finance/FNB": "L_fnb"}
    ids = apply.resolve_label_ids_for_target("Finance/FNB", name_to_id)
    assert ids == ["L_finance", "L_fnb"]


def test_resolve_label_ids_top_level_returns_self_only():
    name_to_id = {"Receipts": "L_receipts"}
    ids = apply.resolve_label_ids_for_target("Receipts", name_to_id)
    assert ids == ["L_receipts"]


def test_resolve_label_ids_missing_parent_raises():
    name_to_id = {"Finance/FNB": "L_fnb"}  # no Finance parent
    with pytest.raises(KeyError, match="Finance"):
        apply.resolve_label_ids_for_target("Finance/FNB", name_to_id)


def test_resolve_label_ids_missing_target_raises():
    name_to_id = {"Finance": "L_finance"}
    with pytest.raises(KeyError, match="Finance/FNB"):
        apply.resolve_label_ids_for_target("Finance/FNB", name_to_id)


def test_resolve_label_ids_deep_nesting():
    name_to_id = {"A": "1", "A/B": "2", "A/B/C": "3"}
    # Only direct parent + self in our scheme (Gmail labels are at most one-deep typically)
    ids = apply.resolve_label_ids_for_target("A/B/C", name_to_id)
    assert ids == ["1", "2", "3"]


def test_compile_label_plan_combines_leaf_and_subject():
    leaf = {"Finance/FNB": "from:fnb.co.za", "Newsletters/Medium": "from:medium.com"}
    subject = {"Receipts": "subject:receipt"}
    name_to_id = {
        "Finance": "F",
        "Finance/FNB": "FF",
        "Newsletters": "N",
        "Newsletters/Medium": "NM",
        "Receipts": "R",
    }
    plan = apply.compile_label_plan(leaf, subject, name_to_id)
    assert len(plan) == 3
    by_label = {item["label_name"]: item for item in plan}
    assert by_label["Finance/FNB"]["query"] == "from:fnb.co.za"
    assert by_label["Finance/FNB"]["label_ids"] == ["F", "FF"]
    assert by_label["Newsletters/Medium"]["label_ids"] == ["N", "NM"]
    assert by_label["Receipts"]["query"] == "subject:receipt"
    assert by_label["Receipts"]["label_ids"] == ["R"]


def test_compile_label_plan_skips_unknown_labels():
    leaf = {"Finance/FNB": "from:fnb.co.za", "Bogus/Label": "from:nowhere"}
    subject = {}
    name_to_id = {"Finance": "F", "Finance/FNB": "FF"}  # Bogus not present
    plan = apply.compile_label_plan(leaf, subject, name_to_id)
    assert [p["label_name"] for p in plan] == ["Finance/FNB"]


def test_load_progress_empty_when_missing(tmp_path):
    progress = apply.load_progress(tmp_path / "progress.json")
    assert progress == {"started_at": None, "completed": {}}


def test_save_and_load_progress_roundtrip(tmp_path):
    path = tmp_path / "progress.json"
    data = {
        "started_at": "2026-05-19T12:00:00Z",
        "completed": {"Finance/FNB": {"count": 42, "completed_at": "2026-05-19T12:01:00Z"}},
    }
    apply.save_progress(path, data)
    loaded = apply.load_progress(path)
    assert loaded == data


def test_filter_plan_by_progress_skips_completed():
    plan = [
        {"label_name": "Finance/FNB", "query": "q1", "label_ids": ["a", "b"]},
        {"label_name": "Newsletters/Medium", "query": "q2", "label_ids": ["c", "d"]},
    ]
    progress = {"completed": {"Finance/FNB": {"count": 10, "completed_at": "..."}}}
    remaining = apply.filter_plan_by_progress(plan, progress)
    assert [p["label_name"] for p in remaining] == ["Newsletters/Medium"]

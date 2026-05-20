from __future__ import annotations

import json
from pathlib import Path

import pytest

from gmail_cleanup import classify


def test_group_by_label_set_collapses_identical_sets():
    classification = {
        "m1": ["Finance", "FNB"],
        "m2": ["Finance", "FNB"],
        "m3": ["Newsletters", "Medium"],
        "m4": ["Finance", "FNB"],
    }
    grouped = classify.group_by_label_set(classification)
    keys = sorted(grouped.keys())
    assert keys == [("FNB", "Finance"), ("Medium", "Newsletters")]
    assert sorted(grouped[("FNB", "Finance")]) == ["m1", "m2", "m4"]
    assert grouped[("Medium", "Newsletters")] == ["m3"]


def test_group_by_label_set_sorts_label_names_in_key():
    """Keys must be canonical (sorted) so {A,B} and {B,A} group together."""
    classification = {
        "m1": ["Newsletters", "Medium"],
        "m2": ["Medium", "Newsletters"],
    }
    grouped = classify.group_by_label_set(classification)
    assert list(grouped.keys()) == [("Medium", "Newsletters")]
    assert sorted(grouped[("Medium", "Newsletters")]) == ["m1", "m2"]


def test_resolve_label_names_to_ids_basic():
    name_to_id = {"Finance": "L1", "FNB": "L2", "Medium": "L3"}
    ids = classify.resolve_label_names_to_ids(["Finance", "FNB"], name_to_id)
    assert sorted(ids) == ["L1", "L2"]


def test_resolve_label_names_case_insensitive():
    name_to_id = {"medium": "L1", "Finance": "L2"}
    ids = classify.resolve_label_names_to_ids(["Medium", "Finance"], name_to_id)
    assert sorted(ids) == ["L1", "L2"]


def test_resolve_label_names_skips_unknown_labels():
    name_to_id = {"Finance": "L1"}
    ids = classify.resolve_label_names_to_ids(["Finance", "NonexistentLabel"], name_to_id)
    assert ids == ["L1"]


def test_validate_classification_rejects_messages_not_in_dump():
    dump = {"messages": [{"id": "m1"}, {"id": "m2"}]}
    classification = {"m1": ["A"], "m3": ["B"]}  # m3 not in dump
    valid, invalid = classify.validate_classification(classification, dump)
    assert valid == {"m1": ["A"]}
    assert invalid == ["m3"]


def test_validate_classification_strips_unknown_labels():
    dump = {"messages": [{"id": "m1"}, {"id": "m2"}], "available_labels": ["Finance", "Newsletters"]}
    classification = {"m1": ["Finance", "BogusLabel"], "m2": ["Newsletters"]}
    valid, invalid = classify.validate_classification(classification, dump)
    assert valid == {"m1": ["Finance"], "m2": ["Newsletters"]}
    assert "BogusLabel" in str(invalid)


def test_validate_classification_with_strict_false_keeps_unknown_labels(tmp_path):
    """When dump has no available_labels list, all labels pass through."""
    dump = {"messages": [{"id": "m1"}]}
    classification = {"m1": ["AnyLabel"]}
    valid, _ = classify.validate_classification(classification, dump)
    assert valid == {"m1": ["AnyLabel"]}

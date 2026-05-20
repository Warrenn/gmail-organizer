from __future__ import annotations

from gmail_cleanup import flatten


def test_extract_leaf_name_simple():
    assert flatten.extract_leaf_name("Newsletters/Medium") == "Medium"


def test_extract_leaf_name_with_space_in_parent():
    assert flatten.extract_leaf_name("Sync Issues/Conflicts") == "Conflicts"


def test_extract_leaf_name_with_space_in_leaf():
    assert flatten.extract_leaf_name("Sync Issues/Local Failures") == "Local Failures"


def test_extract_leaf_name_no_slash_returns_input():
    assert flatten.extract_leaf_name("TopLevel") == "TopLevel"


def test_extract_leaf_name_empty():
    assert flatten.extract_leaf_name("") == ""


def test_extract_parent_name_simple():
    assert flatten.extract_parent_name("Newsletters/Medium") == "Newsletters"


def test_extract_parent_name_no_slash_returns_empty():
    assert flatten.extract_parent_name("TopLevel") == ""


def test_extract_parent_name_with_space():
    assert flatten.extract_parent_name("Sync Issues/Conflicts") == "Sync Issues"


def test_plan_flatten_operations_groups_by_leaf():
    """Two nested labels with same leaf (e.g. Newsletters/Mexc + Notifications/Mexc) merge into one flat target."""
    nested = [
        {"id": "L1", "name": "Newsletters/Mexc"},
        {"id": "L2", "name": "Notifications/Mexc"},
        {"id": "L3", "name": "Finance/FNB"},
    ]
    ops = flatten.plan_flatten_operations(nested)
    # Each nested label gets its own op (no grouping at the op level — they each target the same flat leaf)
    assert len(ops) == 3
    assert ops[0]["nested_name"] == "Newsletters/Mexc"
    assert ops[0]["leaf"] == "Mexc"
    assert ops[0]["parent"] == "Newsletters"
    assert ops[1]["nested_name"] == "Notifications/Mexc"
    assert ops[1]["leaf"] == "Mexc"
    assert ops[1]["parent"] == "Notifications"
    assert ops[2]["nested_name"] == "Finance/FNB"
    assert ops[2]["leaf"] == "FNB"


def test_plan_flatten_operations_skips_non_nested():
    nested = [
        {"id": "L1", "name": "Newsletters/Medium"},
        {"id": "L2", "name": "TopLevel"},  # not nested — shouldn't be in input but defensively skip
    ]
    ops = flatten.plan_flatten_operations(nested)
    assert len(ops) == 1
    assert ops[0]["nested_name"] == "Newsletters/Medium"


def test_identify_conflicts_finds_same_leaf_across_parents():
    nested = [
        {"id": "L1", "name": "Newsletters/Mexc"},
        {"id": "L2", "name": "Notifications/Mexc"},
        {"id": "L3", "name": "Finance/FNB"},
    ]
    conflicts = flatten.identify_leaf_collisions(nested)
    assert conflicts == {"Mexc": ["Newsletters/Mexc", "Notifications/Mexc"]}


def test_identify_conflicts_finds_overlap_with_existing_flat():
    nested = [
        {"id": "L1", "name": "Newsletters/Medium"},
        {"id": "L2", "name": "Finance/FNB"},
    ]
    existing_flat = {"Medium", "OtherFlat"}
    overlaps = flatten.identify_existing_flat_overlaps(nested, existing_flat)
    assert overlaps == {"Medium": "Newsletters/Medium"}


def test_identify_conflicts_no_collisions():
    nested = [
        {"id": "L1", "name": "Newsletters/Medium"},
        {"id": "L2", "name": "Finance/FNB"},
    ]
    assert flatten.identify_leaf_collisions(nested) == {}
    assert flatten.identify_existing_flat_overlaps(nested, {"Unrelated"}) == {}


def test_identify_existing_flat_overlaps_is_case_insensitive():
    """Gmail label uniqueness is case-insensitive (e.g., lowercase 'medium' collides with 'Medium')."""
    nested = [
        {"id": "L1", "name": "Newsletters/Medium"},
        {"id": "L2", "name": "Finance/FNB"},
    ]
    overlaps = flatten.identify_existing_flat_overlaps(nested, {"medium"})  # lowercase existing
    assert overlaps == {"Medium": "Newsletters/Medium"}


def test_find_case_insensitive_match_returns_existing_id():
    name_to_id = {"medium": "Label_X", "Other": "Label_Y"}
    assert flatten.find_case_insensitive(name_to_id, "Medium") == "Label_X"
    assert flatten.find_case_insensitive(name_to_id, "MEDIUM") == "Label_X"
    assert flatten.find_case_insensitive(name_to_id, "Other") == "Label_Y"


def test_find_case_insensitive_returns_none_when_no_match():
    name_to_id = {"medium": "Label_X"}
    assert flatten.find_case_insensitive(name_to_id, "Nonexistent") is None

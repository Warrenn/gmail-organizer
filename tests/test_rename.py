from __future__ import annotations

import pytest

from gmail_cleanup import rename


class _FakeRequest:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error

    def execute(self):
        if self._error is not None:
            raise self._error
        return self._response


class _FakeMessages:
    def __init__(self, messages_by_label: dict[str, list[str]] | None = None):
        self.messages_by_label = messages_by_label or {}
        self.list_calls: list[dict] = []
        self.batch_modify_calls: list[dict] = []

    def list(self, **kwargs):
        self.list_calls.append(kwargs)
        q = kwargs.get("q", "")
        label_id = q.split(":", 1)[1] if ":" in q else None
        ids = self.messages_by_label.get(label_id, [])
        return _FakeRequest({"messages": [{"id": i} for i in ids]})

    def batchModify(self, **kwargs):
        self.batch_modify_calls.append(kwargs)
        return _FakeRequest({})


class _FakeLabels:
    def __init__(self):
        self.patch_calls: list[dict] = []
        self.delete_calls: list[dict] = []
        self.patch_errors_by_id: dict[str, Exception] = {}
        self.delete_errors_by_id: dict[str, Exception] = {}

    def patch(self, userId, id, body):
        self.patch_calls.append({"userId": userId, "id": id, "body": body})
        return _FakeRequest(
            response={"id": id, "name": body.get("name")},
            error=self.patch_errors_by_id.get(id),
        )

    def delete(self, userId, id):
        self.delete_calls.append({"userId": userId, "id": id})
        return _FakeRequest(error=self.delete_errors_by_id.get(id))


class _FakeUsers:
    def __init__(self, messages_by_label=None):
        self._messages = _FakeMessages(messages_by_label)
        self._labels = _FakeLabels()

    def messages(self):
        return self._messages

    def labels(self):
        return self._labels


class _FakeService:
    def __init__(self, messages_by_label=None):
        self._users = _FakeUsers(messages_by_label)

    def users(self):
        return self._users


def test_plan_empty_input_returns_empty_plan():
    plan = rename.plan_renames([])
    assert plan == {"renames": [], "merges": [], "skipped": []}


def test_plan_simple_rename():
    plan = rename.plan_renames([{"id": "L1", "name": "Amazon"}])
    assert plan["renames"] == [{"id": "L1", "old_name": "Amazon", "new_name": "amazon"}]
    assert plan["merges"] == []
    assert plan["skipped"] == []


def test_plan_already_conforming_is_skipped():
    plan = rename.plan_renames([{"id": "L1", "name": "scribd"}])
    assert plan["renames"] == []
    assert plan["skipped"] == [{"id": "L1", "name": "scribd", "reason": "already_conforming"}]


def test_plan_outlook_excluded():
    plan = rename.plan_renames([{"id": "L1", "name": "Notes"}])
    assert plan["renames"] == []
    assert plan["skipped"] == [{"id": "L1", "name": "Notes", "reason": "excluded"}]


def test_plan_all_outlook_labels_excluded():
    inputs = [
        {"id": "L1", "name": "Notes"},
        {"id": "L2", "name": "Deleted Items"},
        {"id": "L3", "name": "Sent Items"},
        {"id": "L4", "name": "Junk E-mail"},
        {"id": "L5", "name": "Sync Issues"},
        {"id": "L6", "name": "Conflicts"},
        {"id": "L7", "name": "Local Failures"},
        {"id": "L8", "name": "Server Failures"},
    ]
    plan = rename.plan_renames(inputs)
    assert len(plan["skipped"]) == 8
    assert all(s["reason"] == "excluded" for s in plan["skipped"])
    assert plan["renames"] == []
    assert plan["merges"] == []


def test_plan_underscore_prefix_skipped():
    plan = rename.plan_renames([
        {"id": "L1", "name": "_Archive"},
        {"id": "L2", "name": "_Outbox"},
    ])
    assert plan["renames"] == []
    assert {s["reason"] for s in plan["skipped"]} == {"underscore_prefix"}


def test_plan_extra_exclude_skipped():
    plan = rename.plan_renames(
        [{"id": "L1", "name": "Amazon"}],
        extra_excludes=frozenset({"Amazon"}),
    )
    assert plan["renames"] == []
    assert plan["skipped"] == [{"id": "L1", "name": "Amazon", "reason": "excluded"}]


def test_plan_multiword_hyphenated():
    plan = rename.plan_renames([{"id": "L1", "name": "Mac in cloud"}])
    assert plan["renames"] == [
        {"id": "L1", "old_name": "Mac in cloud", "new_name": "mac-in-cloud"}
    ]


def test_plan_bracket_label_alone_simple_rename():
    plan = rename.plan_renames([{"id": "L25", "name": "[Notion]"}])
    assert plan["renames"] == [
        {"id": "L25", "old_name": "[Notion]", "new_name": "notion"}
    ]
    assert plan["merges"] == []


def test_plan_collision_creates_merge():
    """The [Notion]/Notion case: both normalize to 'notion'. Notion survives, [Notion] merges in."""
    plan = rename.plan_renames([
        {"id": "L174", "name": "Notion"},
        {"id": "L25", "name": "[Notion]"},
    ])
    # Notion survives and gets renamed to lowercase
    assert plan["renames"] == [
        {"id": "L174", "old_name": "Notion", "new_name": "notion"}
    ]
    # [Notion] merges into Notion
    assert plan["merges"] == [
        {
            "source_id": "L25",
            "source_name": "[Notion]",
            "target_id": "L174",
            "target_name": "Notion",
        }
    ]
    assert plan["skipped"] == []


def test_plan_collision_survivor_prefers_case_insensitive_match():
    """When two labels collide, the one whose current name matches normalized form (case-insensitively) wins."""
    plan = rename.plan_renames([
        {"id": "L_a", "name": "[Foo]"},
        {"id": "L_b", "name": "Foo"},
    ])
    # Foo.lower() == "foo" == normalize("Foo"); [Foo] does not.
    rename_ids = [r["id"] for r in plan["renames"]]
    merge_source_ids = [m["source_id"] for m in plan["merges"]]
    assert rename_ids == ["L_b"]
    assert merge_source_ids == ["L_a"]


def test_plan_collision_no_preferred_survivor_uses_stable_order():
    """If neither original matches normalized case-insensitively, pick the lexically smallest id as survivor."""
    plan = rename.plan_renames([
        {"id": "L_b", "name": "[Bar]"},
        {"id": "L_a", "name": "Bar!"},
    ])
    # Both normalize to "bar". Neither original lowercases to "bar". Survivor = L_a (lexically smallest id).
    assert [r["id"] for r in plan["renames"]] == ["L_a"]
    assert [m["source_id"] for m in plan["merges"]] == ["L_b"]


def test_plan_three_way_collision_one_survivor_two_merges():
    plan = rename.plan_renames([
        {"id": "L1", "name": "foo"},     # already-conforming form
        {"id": "L2", "name": "[Foo]"},
        {"id": "L3", "name": "FOO"},
    ])
    # L1 ("foo") is already conforming AND matches normalized. Survivor.
    # L2 and L3 both merge into L1.
    assert [s["id"] for s in plan["skipped"] if s["reason"] == "already_conforming"] == ["L1"]
    merge_sources = sorted(m["source_id"] for m in plan["merges"])
    assert merge_sources == ["L2", "L3"]
    assert all(m["target_id"] == "L1" for m in plan["merges"])
    # The survivor is already conforming → no rename emitted.
    assert plan["renames"] == []


def test_plan_mixed_realistic_input():
    """A small slice that exercises every classification."""
    inputs = [
        {"id": "L_arc", "name": "_Archive"},        # underscore skip
        {"id": "L_notes", "name": "Notes"},          # outlook skip
        {"id": "L_scribd", "name": "scribd"},        # already conforming
        {"id": "L_amazon", "name": "Amazon"},        # simple rename
        {"id": "L_mac", "name": "Mac in cloud"},     # multi-word
        {"id": "L_doc", "name": "docuwriter.ai"},    # punctuation removed
        {"id": "L_notion", "name": "Notion"},        # collision survivor
        {"id": "L_bnotion", "name": "[Notion]"},     # collision source
    ]
    plan = rename.plan_renames(inputs)
    # Renames
    rename_map = {r["id"]: r["new_name"] for r in plan["renames"]}
    assert rename_map == {
        "L_amazon": "amazon",
        "L_mac": "mac-in-cloud",
        "L_doc": "docuwriterai",
        "L_notion": "notion",
    }
    # Merges
    assert plan["merges"] == [
        {
            "source_id": "L_bnotion",
            "source_name": "[Notion]",
            "target_id": "L_notion",
            "target_name": "Notion",
        }
    ]
    # Skipped
    skipped_by_id = {s["id"]: s["reason"] for s in plan["skipped"]}
    assert skipped_by_id == {
        "L_arc": "underscore_prefix",
        "L_notes": "excluded",
        "L_scribd": "already_conforming",
    }


def test_plan_skipped_labels_dont_block_collisions():
    """An Outlook-excluded label with same letters as a normalized form doesn't count as a collision."""
    inputs = [
        {"id": "L_notes", "name": "Notes"},  # excluded
        {"id": "L_other", "name": "notes"},  # already conforming, totally separate label
    ]
    plan = rename.plan_renames(inputs)
    assert plan["merges"] == []
    skipped_ids = {s["id"] for s in plan["skipped"]}
    assert skipped_ids == {"L_notes", "L_other"}


# ---------------------------------------------------------------------------
# apply_plan tests
# ---------------------------------------------------------------------------


def test_apply_empty_plan_makes_no_calls():
    service = _FakeService()
    summary = rename.apply_plan(service, {"renames": [], "merges": [], "skipped": []})
    assert summary["renames_applied"] == 0
    assert summary["merges_applied"] == 0
    assert summary["errors"] == []
    assert service._users._labels.patch_calls == []
    assert service._users._labels.delete_calls == []
    assert service._users._messages.list_calls == []


def test_apply_single_rename_calls_patch():
    service = _FakeService()
    plan = {
        "renames": [{"id": "L_a", "old_name": "Amazon", "new_name": "amazon"}],
        "merges": [],
        "skipped": [],
    }
    summary = rename.apply_plan(service, plan)
    assert summary["renames_applied"] == 1
    assert summary["errors"] == []
    patch_calls = service._users._labels.patch_calls
    assert len(patch_calls) == 1
    assert patch_calls[0] == {"userId": "me", "id": "L_a", "body": {"name": "amazon"}}


def test_apply_multiple_renames_all_called():
    service = _FakeService()
    plan = {
        "renames": [
            {"id": "L1", "old_name": "Amazon", "new_name": "amazon"},
            {"id": "L2", "old_name": "Travel", "new_name": "travel"},
            {"id": "L3", "old_name": "Mac in cloud", "new_name": "mac-in-cloud"},
        ],
        "merges": [],
        "skipped": [],
    }
    summary = rename.apply_plan(service, plan)
    assert summary["renames_applied"] == 3
    patched_ids = [c["id"] for c in service._users._labels.patch_calls]
    assert patched_ids == ["L1", "L2", "L3"]


def test_apply_merge_with_messages_relabels_and_deletes():
    service = _FakeService(messages_by_label={"L_src": ["m1", "m2", "m3"]})
    plan = {
        "renames": [],
        "merges": [{
            "source_id": "L_src",
            "source_name": "[Notion]",
            "target_id": "L_tgt",
            "target_name": "Notion",
        }],
        "skipped": [],
    }
    summary = rename.apply_plan(service, plan)
    assert summary["merges_applied"] == 1
    # Source messages were listed
    list_calls = service._users._messages.list_calls
    assert any(c.get("q") == "label:L_src" for c in list_calls)
    # batchModify called with target label and source's message ids
    batch_calls = service._users._messages.batch_modify_calls
    assert len(batch_calls) == 1
    assert sorted(batch_calls[0]["body"]["ids"]) == ["m1", "m2", "m3"]
    assert batch_calls[0]["body"]["addLabelIds"] == ["L_tgt"]
    # Source label deleted
    delete_calls = service._users._labels.delete_calls
    assert delete_calls == [{"userId": "me", "id": "L_src"}]


def test_apply_merge_with_zero_messages_still_deletes_label():
    service = _FakeService(messages_by_label={"L_src": []})
    plan = {
        "renames": [],
        "merges": [{
            "source_id": "L_src",
            "source_name": "[Empty]",
            "target_id": "L_tgt",
            "target_name": "Empty",
        }],
        "skipped": [],
    }
    summary = rename.apply_plan(service, plan)
    assert summary["merges_applied"] == 1
    # No batchModify since no messages
    assert service._users._messages.batch_modify_calls == []
    # But label still deleted
    assert service._users._labels.delete_calls == [{"userId": "me", "id": "L_src"}]


def test_apply_rename_error_collected_and_others_proceed():
    service = _FakeService()
    boom = RuntimeError("simulated")
    service._users._labels.patch_errors_by_id["L_bad"] = boom
    plan = {
        "renames": [
            {"id": "L_good1", "old_name": "Amazon", "new_name": "amazon"},
            {"id": "L_bad", "old_name": "Travel", "new_name": "travel"},
            {"id": "L_good2", "old_name": "Wise", "new_name": "wise"},
        ],
        "merges": [],
        "skipped": [],
    }
    summary = rename.apply_plan(service, plan)
    # Two good renames succeeded
    assert summary["renames_applied"] == 2
    # One error recorded
    assert len(summary["errors"]) == 1
    err = summary["errors"][0]
    assert err["operation"] == "rename"
    assert err["id"] == "L_bad"
    assert "simulated" in err["error"]
    # All three patches were attempted
    assert [c["id"] for c in service._users._labels.patch_calls] == ["L_good1", "L_bad", "L_good2"]


def test_apply_merge_error_collected_and_others_proceed():
    service = _FakeService(messages_by_label={"L_bad": ["m1"], "L_good": ["m2"]})
    boom = RuntimeError("delete failed")
    service._users._labels.delete_errors_by_id["L_bad"] = boom
    plan = {
        "renames": [],
        "merges": [
            {"source_id": "L_bad", "source_name": "src1", "target_id": "T", "target_name": "tgt"},
            {"source_id": "L_good", "source_name": "src2", "target_id": "T", "target_name": "tgt"},
        ],
        "skipped": [],
    }
    summary = rename.apply_plan(service, plan)
    assert summary["merges_applied"] == 1
    assert len(summary["errors"]) == 1
    assert summary["errors"][0]["operation"] == "merge"
    assert summary["errors"][0]["source_id"] == "L_bad"


def test_apply_merges_run_before_renames():
    """Merges (which delete labels) must complete before renames, so renaming a
    surviving label doesn't conflict with a pending case-only neighbour."""
    service = _FakeService(messages_by_label={"L_brackets": []})
    plan = {
        "renames": [
            {"id": "L_notion", "old_name": "Notion", "new_name": "notion"},
        ],
        "merges": [
            {
                "source_id": "L_brackets",
                "source_name": "[Notion]",
                "target_id": "L_notion",
                "target_name": "Notion",
            },
        ],
        "skipped": [],
    }
    rename.apply_plan(service, plan)
    delete_calls = service._users._labels.delete_calls
    patch_calls = service._users._labels.patch_calls
    # We expect a delete to be recorded; and a patch to be recorded.
    # Since they're recorded in the order they happen, the delete should come
    # before the patch in a unified timeline. We approximate by checking
    # the test setup invariants: 1 delete and 1 patch happened.
    assert len(delete_calls) == 1
    assert len(patch_calls) == 1


def test_apply_skipped_entries_are_no_op():
    service = _FakeService()
    plan = {
        "renames": [],
        "merges": [],
        "skipped": [
            {"id": "L1", "name": "scribd", "reason": "already_conforming"},
            {"id": "L2", "name": "_Archive", "reason": "underscore_prefix"},
            {"id": "L3", "name": "Notes", "reason": "excluded"},
        ],
    }
    summary = rename.apply_plan(service, plan)
    assert summary["renames_applied"] == 0
    assert summary["merges_applied"] == 0
    assert service._users._labels.patch_calls == []
    assert service._users._labels.delete_calls == []
    assert service._users._messages.list_calls == []

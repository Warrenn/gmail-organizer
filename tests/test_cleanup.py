from __future__ import annotations

import pytest

from gmail_cleanup import cleanup


# ---------------------------------------------------------------------------
# Fake Gmail service
# ---------------------------------------------------------------------------


class _Req:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _Labels:
    def __init__(self, existing: dict[str, str]):
        # existing: name -> id
        self._existing = dict(existing)
        self.create_calls: list[dict] = []
        self.delete_calls: list[str] = []
        self._next_id = 1000

    def list(self, userId):
        return _Req({"labels": [{"id": lid, "name": name, "type": "user"} for name, lid in self._existing.items()]})

    def create(self, userId, body):
        name = body["name"]
        self.create_calls.append(body)
        lid = f"Label_new_{self._next_id}"
        self._next_id += 1
        self._existing[name] = lid
        return _Req({"id": lid, "name": name})

    def delete(self, userId, id):
        self.delete_calls.append(id)
        return _Req({})


class _Threads:
    def __init__(self):
        self.modify_calls: list[dict] = []

    def modify(self, userId, id, body):
        self.modify_calls.append({"id": id, "body": body})
        return _Req({})


class _Users:
    def __init__(self, labels=None):
        self._labels = _Labels(labels or {})
        self._threads = _Threads()

    def labels(self):
        return self._labels

    def threads(self):
        return self._threads


class _Service:
    def __init__(self, labels=None):
        self._users = _Users(labels)

    def users(self):
        return self._users


# ---------------------------------------------------------------------------
# cleanup_resolved_markers
# ---------------------------------------------------------------------------


def test_cleanup_plus_marker_applies_target_label_and_deletes_marker():
    service = _Service(labels={"+receipts": "L_marker", "receipts": "L_target"})
    resolved = [{
        "marker_label_id": "L_marker",
        "marker_label_name": "+receipts",
        "sign": "+",
        "target_label_name": "receipts",
        "thread_ids": ["t1", "t2"],
    }]
    summary = cleanup.cleanup_resolved_markers(service, resolved)

    threads = service._users._threads
    # Two thread modifications: each adds target and removes marker
    assert len(threads.modify_calls) == 2
    for call in threads.modify_calls:
        body = call["body"]
        assert "L_target" in body["addLabelIds"]
        assert "L_marker" in body["removeLabelIds"]
    # Marker label deleted
    assert service._users._labels.delete_calls == ["L_marker"]
    # Summary reflects what happened
    assert summary["markers_processed"] == 1
    assert summary["threads_modified"] == 2
    assert summary["marker_labels_deleted"] == 1
    assert summary["target_labels_created"] == 0


def test_cleanup_minus_marker_removes_target_and_deletes_marker():
    service = _Service(labels={"-newsletters": "L_marker", "newsletters": "L_target"})
    resolved = [{
        "marker_label_id": "L_marker",
        "marker_label_name": "-newsletters",
        "sign": "-",
        "target_label_name": "newsletters",
        "thread_ids": ["t1"],
    }]
    cleanup.cleanup_resolved_markers(service, resolved)

    call = service._users._threads.modify_calls[0]
    # Remove both target AND marker
    assert "L_target" in call["body"]["removeLabelIds"]
    assert "L_marker" in call["body"]["removeLabelIds"]
    assert call["body"].get("addLabelIds", []) == []


def test_cleanup_creates_target_label_if_missing():
    """A `+X` resolution may introduce a brand-new label that doesn't exist
    in Gmail yet — cleanup must create it before applying."""
    service = _Service(labels={"+newthing": "L_marker"})  # `newthing` does NOT exist yet
    resolved = [{
        "marker_label_id": "L_marker",
        "marker_label_name": "+newthing",
        "sign": "+",
        "target_label_name": "newthing",
        "thread_ids": ["t1"],
    }]
    summary = cleanup.cleanup_resolved_markers(service, resolved)

    assert len(service._users._labels.create_calls) == 1
    assert service._users._labels.create_calls[0]["name"] == "newthing"
    assert summary["target_labels_created"] == 1


def test_cleanup_skips_marker_with_no_threads():
    """A marker with no threads still has its label deleted (it was placed and
    never sat on a thread, e.g. a typo), but no thread modifications happen."""
    service = _Service(labels={"+typo": "L_marker"})
    resolved = [{
        "marker_label_id": "L_marker",
        "marker_label_name": "+typo",
        "sign": "+",
        "target_label_name": "typo",
        "thread_ids": [],
    }]
    cleanup.cleanup_resolved_markers(service, resolved)

    assert service._users._threads.modify_calls == []
    assert service._users._labels.delete_calls == ["L_marker"]


def test_cleanup_multiple_markers():
    service = _Service(labels={
        "+receipts": "L_plus",
        "-newsletters": "L_minus",
        "receipts": "L_r",
        "newsletters": "L_n",
    })
    resolved = [
        {
            "marker_label_id": "L_plus",
            "marker_label_name": "+receipts",
            "sign": "+",
            "target_label_name": "receipts",
            "thread_ids": ["t1"],
        },
        {
            "marker_label_id": "L_minus",
            "marker_label_name": "-newsletters",
            "sign": "-",
            "target_label_name": "newsletters",
            "thread_ids": ["t2"],
        },
    ]
    summary = cleanup.cleanup_resolved_markers(service, resolved)
    assert summary["markers_processed"] == 2
    assert summary["threads_modified"] == 2
    assert sorted(service._users._labels.delete_calls) == ["L_minus", "L_plus"]


def test_cleanup_minus_marker_does_not_create_missing_target_label():
    """A `-X` resolution must never create the target label. If `x` doesn't
    exist there's nothing to remove — only the marker is deleted."""
    service = _Service(labels={"-newsletters": "L_marker"})  # `newsletters` absent
    resolved = [{
        "marker_label_id": "L_marker",
        "marker_label_name": "-newsletters",
        "sign": "-",
        "target_label_name": "newsletters",
        "thread_ids": ["t1"],
    }]
    summary = cleanup.cleanup_resolved_markers(service, resolved)

    # No label was created
    assert service._users._labels.create_calls == []
    assert summary["target_labels_created"] == 0
    # The marker is still deleted
    assert service._users._labels.delete_calls == ["L_marker"]
    # The thread was modified but only to strip the marker — no phantom target id
    call = service._users._threads.modify_calls[0]
    assert call["body"].get("addLabelIds", []) == []
    # No None / made-up target id leaked into removeLabelIds
    assert call["body"]["removeLabelIds"] == ["L_marker"]


def test_cleanup_rejects_invalid_sign():
    """An entry with a sign that is neither '+' nor '-' is rejected: it must
    not modify any thread or label, and must surface a validate_sign error."""
    service = _Service(labels={"+receipts": "L_marker", "receipts": "L_target"})
    resolved = [{
        "marker_label_id": "L_marker",
        "marker_label_name": "*weird",
        "sign": "*",
        "target_label_name": "receipts",
        "thread_ids": ["t1"],
    }]
    summary = cleanup.cleanup_resolved_markers(service, resolved)

    assert any(e["stage"] == "validate_sign" for e in summary["errors"])
    assert service._users._threads.modify_calls == []
    assert service._users._labels.create_calls == []
    assert service._users._labels.delete_calls == []


def test_cleanup_collects_errors_per_marker_does_not_fail_fast():
    """If one marker's cleanup fails, others should still proceed."""
    service = _Service(labels={"+receipts": "L_a", "receipts": "L_r"})

    # Inject an error on the second thread's modify
    original_modify = service._users._threads.modify
    call_count = {"n": 0}

    def faulty_modify(userId, id, body):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated transient")
        return original_modify(userId, id, body)

    service._users._threads.modify = faulty_modify

    resolved = [{
        "marker_label_id": "L_a",
        "marker_label_name": "+receipts",
        "sign": "+",
        "target_label_name": "receipts",
        "thread_ids": ["t1", "t2"],
    }]
    summary = cleanup.cleanup_resolved_markers(service, resolved)
    assert len(summary["errors"]) >= 1
    # The other thread still got processed
    assert summary["threads_modified"] >= 1

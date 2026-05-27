from __future__ import annotations

import pytest

from gmail_cleanup import feedback


# ---------------------------------------------------------------------------
# parse_marker_label — pure helper
# ---------------------------------------------------------------------------


def test_parse_marker_label_plus():
    sign, target = feedback.parse_marker_label("+receipts")
    assert sign == "+"
    assert target == "receipts"


def test_parse_marker_label_minus():
    sign, target = feedback.parse_marker_label("-newsletters")
    assert sign == "-"
    assert target == "newsletters"


def test_parse_marker_label_normalizes_target():
    """Target is normalized to project convention so Claude sees a clean name."""
    sign, target = feedback.parse_marker_label("+Mac in Cloud")
    assert sign == "+"
    assert target == "mac-in-cloud"


def test_parse_marker_label_non_marker_returns_none():
    assert feedback.parse_marker_label("newsletters") is None
    assert feedback.parse_marker_label("_Outbox") is None
    assert feedback.parse_marker_label("") is None


def test_parse_marker_label_empty_prefix_only():
    assert feedback.parse_marker_label("+") is None
    assert feedback.parse_marker_label("-") is None


# ---------------------------------------------------------------------------
# scan_for_markers — with a fake service
# ---------------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, response):
        self._response = response

    def execute(self):
        return self._response


class _FakeLabelsApi:
    def __init__(self, labels):
        self._labels = labels

    def list(self, userId):
        return _FakeRequest({"labels": self._labels})


class _FakeMessagesApi:
    def __init__(self, by_label, message_by_id):
        self._by_label = by_label
        self._message_by_id = message_by_id

    def list(self, **kwargs):
        label_ids = kwargs.get("labelIds") or []
        ids: list[str] = []
        for lid in label_ids:
            ids.extend(self._by_label.get(lid, []))
        return _FakeRequest({"messages": [{"id": i} for i in ids]})

    def get(self, userId, id, format=None, metadataHeaders=None):
        return _FakeRequest(self._message_by_id[id])


class _FakeUsers:
    def __init__(self, labels, by_label, message_by_id):
        self._labels = _FakeLabelsApi(labels)
        self._messages = _FakeMessagesApi(by_label, message_by_id)

    def labels(self):
        return self._labels

    def messages(self):
        return self._messages


class _FakeService:
    def __init__(self, labels=None, by_label=None, message_by_id=None):
        self._users = _FakeUsers(labels or [], by_label or {}, message_by_id or {})

    def users(self):
        return self._users


def _make_message(msg_id, thread_id, from_, subject, snippet, label_ids):
    return {
        "id": msg_id,
        "threadId": thread_id,
        "labelIds": label_ids,
        "snippet": snippet,
        "payload": {
            "headers": [
                {"name": "From", "value": from_},
                {"name": "Subject", "value": subject},
            ],
        },
    }


def test_scan_no_markers_returns_empty():
    service = _FakeService(
        labels=[
            {"id": "L1", "name": "amazon", "type": "user"},
            {"id": "L2", "name": "stripe", "type": "user"},
        ],
    )
    result = feedback.scan_for_markers(service)
    assert result["markers"] == []
    assert sorted(result["existing_labels"]) == ["amazon", "stripe"]


def test_scan_one_plus_marker_with_threads():
    service = _FakeService(
        labels=[
            {"id": "L_marker", "name": "+receipts", "type": "user"},
            {"id": "L_amazon", "name": "amazon", "type": "user"},
            {"id": "L_stripe", "name": "stripe", "type": "user"},
        ],
        by_label={
            "L_marker": ["m1", "m2"],
        },
        message_by_id={
            "m1": _make_message("m1", "t1", "noreply@stripe.com", "Your Stripe payout", "Payout of $100", ["L_marker", "L_stripe"]),
            "m2": _make_message("m2", "t2", "billing@example.com", "Invoice 42", "Snippet here", ["L_marker"]),
        },
    )
    result = feedback.scan_for_markers(service)
    assert len(result["markers"]) == 1
    marker = result["markers"][0]
    assert marker["label_name"] == "+receipts"
    assert marker["sign"] == "+"
    assert marker["target_label"] == "receipts"
    assert marker["label_id"] == "L_marker"
    assert len(marker["threads"]) == 2
    thread_ids = sorted(t["thread_id"] for t in marker["threads"])
    assert thread_ids == ["t1", "t2"]


def test_scan_marker_threads_include_metadata():
    service = _FakeService(
        labels=[{"id": "L_m", "name": "+work", "type": "user"}],
        by_label={"L_m": ["m1"]},
        message_by_id={
            "m1": _make_message("m1", "t1", "boss@example.com", "Meeting tomorrow", "Hi all", ["L_m"]),
        },
    )
    result = feedback.scan_for_markers(service)
    thread = result["markers"][0]["threads"][0]
    assert thread["from"] == "boss@example.com"
    assert thread["subject"] == "Meeting tomorrow"
    assert thread["snippet"] == "Hi all"


def test_scan_minus_marker():
    service = _FakeService(
        labels=[{"id": "L_m", "name": "-newsletters", "type": "user"}],
        by_label={"L_m": ["m1"]},
        message_by_id={
            "m1": _make_message("m1", "t1", "noreply@svc.com", "Your verification code", "Code 12345", ["L_m"]),
        },
    )
    result = feedback.scan_for_markers(service)
    marker = result["markers"][0]
    assert marker["sign"] == "-"
    assert marker["target_label"] == "newsletters"


def test_scan_multiple_markers():
    service = _FakeService(
        labels=[
            {"id": "L_plus", "name": "+receipts", "type": "user"},
            {"id": "L_minus", "name": "-newsletters", "type": "user"},
            {"id": "L_other", "name": "stripe", "type": "user"},
        ],
        by_label={"L_plus": ["m1"], "L_minus": ["m2"]},
        message_by_id={
            "m1": _make_message("m1", "t1", "x", "y", "z", ["L_plus"]),
            "m2": _make_message("m2", "t2", "a", "b", "c", ["L_minus"]),
        },
    )
    result = feedback.scan_for_markers(service)
    assert len(result["markers"]) == 2
    signs = sorted(m["sign"] for m in result["markers"])
    assert signs == ["+", "-"]
    # existing_labels lists the non-marker labels
    assert result["existing_labels"] == ["stripe"]


def test_scan_marker_with_no_threads_still_appears():
    """An empty marker label still gets reported — Claude needs to know it exists
    (it'll be cleaned up post-deploy even if there were no threads to act on)."""
    service = _FakeService(
        labels=[{"id": "L_m", "name": "+receipts", "type": "user"}],
        by_label={"L_m": []},
        message_by_id={},
    )
    result = feedback.scan_for_markers(service)
    assert len(result["markers"]) == 1
    assert result["markers"][0]["threads"] == []


def test_scan_includes_generated_at_timestamp():
    service = _FakeService()
    result = feedback.scan_for_markers(service)
    assert "generated_at" in result
    assert isinstance(result["generated_at"], str)


def test_scan_ignores_underscore_prefixed_labels():
    """_Outbox and similar must not be confused for markers."""
    service = _FakeService(
        labels=[
            {"id": "L1", "name": "_Outbox", "type": "user"},
            {"id": "L2", "name": "_Archive", "type": "user"},
            {"id": "L3", "name": "stripe", "type": "user"},
        ],
    )
    result = feedback.scan_for_markers(service)
    assert result["markers"] == []


def test_scan_ignores_system_labels():
    service = _FakeService(
        labels=[
            {"id": "L1", "name": "+receipts", "type": "user"},
            {"id": "INBOX", "name": "INBOX", "type": "system"},
            {"id": "TRASH", "name": "TRASH", "type": "system"},
        ],
        by_label={"L1": []},
    )
    result = feedback.scan_for_markers(service)
    # system labels excluded from existing_labels
    assert "INBOX" not in result["existing_labels"]
    assert "TRASH" not in result["existing_labels"]
    # marker still detected
    assert len(result["markers"]) == 1

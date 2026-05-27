from __future__ import annotations

import pytest

from gmail_cleanup import corpus


def test_message_to_corpus_entry_extracts_headers_and_labels():
    msg = {
        "id": "m1",
        "threadId": "t1",
        "labelIds": ["Label_10", "Label_27", "INBOX"],
        "snippet": "Hello there, your receipt is attached",
        "payload": {
            "headers": [
                {"name": "From", "value": "Support <support@stripe.com>"},
                {"name": "Subject", "value": "Your Stripe payout"},
                {"name": "Date", "value": "Mon, 1 Jan 2026 10:00:00 +0000"},
            ],
        },
    }
    label_id_to_name = {"Label_10": "stripe", "Label_27": "finance"}
    entry = corpus.message_to_corpus_entry(msg, label_id_to_name)
    assert entry["thread_id"] == "t1"
    assert entry["message_id"] == "m1"
    assert entry["from"] == "Support <support@stripe.com>"
    assert entry["subject"] == "Your Stripe payout"
    assert entry["snippet"] == "Hello there, your receipt is attached"
    # System labels (INBOX) excluded; only convention user labels kept.
    assert sorted(entry["expected_labels"]) == ["finance", "stripe"]


def test_message_to_corpus_entry_handles_missing_headers():
    msg = {"id": "m1", "threadId": "t1", "labelIds": [], "snippet": "", "payload": {"headers": []}}
    entry = corpus.message_to_corpus_entry(msg, {})
    assert entry["from"] == ""
    assert entry["subject"] == ""
    assert entry["snippet"] == ""


def test_message_to_corpus_entry_filters_unknown_label_ids():
    msg = {
        "id": "m1",
        "threadId": "t1",
        "labelIds": ["Label_unknown", "Label_10"],
        "snippet": "",
        "payload": {"headers": []},
    }
    entry = corpus.message_to_corpus_entry(msg, {"Label_10": "stripe"})
    # Unknown label_ids (system labels not in mapping) are silently dropped
    assert entry["expected_labels"] == ["stripe"]


def test_message_to_corpus_entry_dedupes_labels():
    msg = {
        "id": "m1",
        "threadId": "t1",
        "labelIds": ["Label_10", "Label_10"],
        "snippet": "",
        "payload": {"headers": []},
    }
    entry = corpus.message_to_corpus_entry(msg, {"Label_10": "stripe"})
    assert entry["expected_labels"] == ["stripe"]


def test_select_thread_sample_takes_first_n():
    assert corpus.select_thread_sample(["a", "b", "c", "d", "e"], 3) == ["a", "b", "c"]


def test_select_thread_sample_returns_all_when_n_exceeds_size():
    assert corpus.select_thread_sample(["a", "b"], 10) == ["a", "b"]


def test_select_thread_sample_zero():
    assert corpus.select_thread_sample(["a", "b"], 0) == []


def test_select_thread_sample_empty_input():
    assert corpus.select_thread_sample([], 5) == []


# ---------------------------------------------------------------------------
# build_corpus with a fake service
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


def _make_message(msg_id: str, thread_id: str, from_: str, subject: str, snippet: str, label_ids: list[str]) -> dict:
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


def test_build_corpus_empty_when_no_user_labels():
    service = _FakeService(labels=[])
    result = corpus.build_corpus(service, per_label_sample_size=5)
    assert result["version"] == 1
    assert result["threads"] == []


def test_build_corpus_samples_per_label():
    service = _FakeService(
        labels=[
            {"id": "Label_10", "name": "stripe", "type": "user"},
            {"id": "Label_27", "name": "finance", "type": "user"},
            {"id": "INBOX", "name": "INBOX", "type": "system"},  # filtered out
        ],
        by_label={
            "Label_10": ["m_stripe_1", "m_stripe_2", "m_stripe_3"],
            "Label_27": ["m_finance_1", "m_finance_2"],
        },
        message_by_id={
            "m_stripe_1": _make_message("m_stripe_1", "t_s1", "a@stripe.com", "subj1", "snip1", ["Label_10"]),
            "m_stripe_2": _make_message("m_stripe_2", "t_s2", "b@stripe.com", "subj2", "snip2", ["Label_10", "Label_27"]),
            "m_stripe_3": _make_message("m_stripe_3", "t_s3", "c@stripe.com", "subj3", "snip3", ["Label_10"]),
            "m_finance_1": _make_message("m_finance_1", "t_f1", "x@fnb.co.za", "subj4", "snip4", ["Label_27"]),
            "m_finance_2": _make_message("m_finance_2", "t_f2", "y@fnb.co.za", "subj5", "snip5", ["Label_27"]),
        },
    )
    result = corpus.build_corpus(service, per_label_sample_size=2)
    # 2 from each of 2 labels = 4 unique messages (m_stripe_2 is in both label searches but should appear once)
    thread_ids = [t["thread_id"] for t in result["threads"]]
    # No duplicates
    assert len(thread_ids) == len(set(thread_ids))


def test_build_corpus_skips_excluded_labels():
    service = _FakeService(
        labels=[
            {"id": "Label_10", "name": "stripe", "type": "user"},
            {"id": "Label_99", "name": "Junk E-mail", "type": "user"},
        ],
        by_label={"Label_10": ["m1"], "Label_99": ["m2"]},
        message_by_id={
            "m1": _make_message("m1", "t1", "x", "y", "z", ["Label_10"]),
            "m2": _make_message("m2", "t2", "a", "b", "c", ["Label_99"]),
        },
    )
    result = corpus.build_corpus(service, per_label_sample_size=5, exclude_labels={"Junk E-mail"})
    thread_ids = [t["thread_id"] for t in result["threads"]]
    assert "t2" not in thread_ids
    assert "t1" in thread_ids


def test_build_corpus_dedupes_threads_across_labels():
    """A message with multiple labels appears in multiple label searches;
    its corpus entry should appear only once with all its labels."""
    service = _FakeService(
        labels=[
            {"id": "L1", "name": "stripe", "type": "user"},
            {"id": "L2", "name": "finance", "type": "user"},
        ],
        by_label={"L1": ["m1"], "L2": ["m1"]},
        message_by_id={
            "m1": _make_message("m1", "t1", "x@stripe.com", "subj", "snip", ["L1", "L2"]),
        },
    )
    result = corpus.build_corpus(service, per_label_sample_size=5)
    assert len(result["threads"]) == 1
    assert sorted(result["threads"][0]["expected_labels"]) == ["finance", "stripe"]


def test_build_corpus_includes_version_and_metadata():
    service = _FakeService(labels=[])
    result = corpus.build_corpus(service, per_label_sample_size=5)
    assert result["version"] == 1
    assert "generated_at" in result
    assert isinstance(result["threads"], list)


# ---------------------------------------------------------------------------
# filter_to_agreement
# ---------------------------------------------------------------------------


def test_filter_to_agreement_keeps_agreeing_threads():
    from gmail_cleanup import rule_interpreter
    spec = rule_interpreter.load_rules_from_string("""
version: 1
sender_rules:
  - id: stripe
    match: {from_contains: stripe.com}
    labels: [finance, stripe]
additive_subject_rules: []
fallback_rules: []
""")
    raw = {
        "version": 1,
        "generated_at": "X",
        "threads": [
            {"thread_id": "t1", "from": "x@stripe.com", "subject": "", "snippet": "", "expected_labels": ["finance", "stripe"]},
            {"thread_id": "t2", "from": "y@other.com", "subject": "", "snippet": "", "expected_labels": ["other"]},
        ],
    }
    filtered, disagreements = corpus.filter_to_agreement(raw, spec)
    assert len(filtered["threads"]) == 1
    assert filtered["threads"][0]["thread_id"] == "t1"
    assert len(disagreements) == 1
    assert disagreements[0]["thread_id"] == "t2"
    assert disagreements[0]["interpreter_output"] == []
    assert disagreements[0]["expected_labels"] == ["other"]


def test_filter_to_agreement_uses_set_equality_not_order():
    from gmail_cleanup import rule_interpreter
    spec = rule_interpreter.load_rules_from_string("""
version: 1
sender_rules:
  - id: stripe
    match: {from_contains: stripe.com}
    labels: [finance, stripe]
additive_subject_rules: []
fallback_rules: []
""")
    raw = {
        "version": 1,
        "generated_at": "X",
        "threads": [
            {"thread_id": "t1", "from": "x@stripe.com", "subject": "", "snippet": "", "expected_labels": ["stripe", "finance"]},  # reversed order
        ],
    }
    filtered, _ = corpus.filter_to_agreement(raw, spec)
    assert len(filtered["threads"]) == 1


def test_filter_to_agreement_preserves_corpus_metadata():
    from gmail_cleanup import rule_interpreter
    spec = rule_interpreter.load_rules_from_string("""
version: 1
sender_rules: []
additive_subject_rules: []
fallback_rules: []
""")
    raw = {"version": 1, "generated_at": "2026-01-01", "threads": []}
    filtered, _ = corpus.filter_to_agreement(raw, spec)
    assert filtered["version"] == 1
    assert filtered["generated_at"] == "2026-01-01"
    assert filtered["threads"] == []

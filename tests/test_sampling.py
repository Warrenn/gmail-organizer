from __future__ import annotations

from gmail_cleanup import sampling


def test_year_slice_queries_inclusive_range():
    slices = sampling.year_slice_queries(2022, 2024)
    assert slices == [
        "after:2022/01/01 before:2023/01/01",
        "after:2023/01/01 before:2024/01/01",
        "after:2024/01/01 before:2025/01/01",
    ]


def test_year_slice_queries_single_year():
    assert sampling.year_slice_queries(2020, 2020) == [
        "after:2020/01/01 before:2021/01/01",
    ]


def test_year_slice_queries_rejects_inverted_range():
    import pytest

    with pytest.raises(ValueError):
        sampling.year_slice_queries(2025, 2020)


def test_parse_from_header_plain_email():
    assert sampling.parse_from_header("alice@example.com") == "alice@example.com"


def test_parse_from_header_with_display_name():
    assert sampling.parse_from_header('"Alice Smith" <alice@example.com>') == "alice@example.com"


def test_parse_from_header_unquoted_display_name():
    assert sampling.parse_from_header("Alice Smith <alice@example.com>") == "alice@example.com"


def test_parse_from_header_lowercases_email():
    assert sampling.parse_from_header("Alice <Alice@Example.COM>") == "alice@example.com"


def test_parse_from_header_returns_empty_for_malformed():
    assert sampling.parse_from_header("not an email") == ""
    assert sampling.parse_from_header("") == ""


def test_tally_senders_counts_occurrences():
    messages = [
        {"From": "alice@example.com"},
        {"From": "Bob <bob@example.com>"},
        {"From": "alice@example.com"},
        {"From": '"Alice" <ALICE@example.com>'},
        {"From": "carol@example.com"},
    ]
    tally = sampling.tally_senders(messages)
    assert tally["alice@example.com"] == 3
    assert tally["bob@example.com"] == 1
    assert tally["carol@example.com"] == 1


def test_tally_senders_skips_missing_from_field():
    messages = [{"Subject": "no from header"}, {"From": "a@b.com"}]
    tally = sampling.tally_senders(messages)
    assert tally == {"a@b.com": 1}


def test_top_senders_sorted_desc():
    tally = {"a@x.com": 5, "b@x.com": 10, "c@x.com": 2}
    top = sampling.top_senders(tally, n=2)
    assert top == [("b@x.com", 10), ("a@x.com", 5)]


def test_extract_headers_picks_named_headers():
    payload = {
        "payload": {
            "headers": [
                {"name": "From", "value": "x@y.com"},
                {"name": "Subject", "value": "hi"},
                {"name": "Date", "value": "Mon, 1 Jan 2024 00:00:00 +0000"},
                {"name": "List-Unsubscribe", "value": "<mailto:unsub@y.com>"},
            ]
        }
    }
    headers = sampling.extract_headers(payload)
    assert headers == {
        "From": "x@y.com",
        "Subject": "hi",
        "Date": "Mon, 1 Jan 2024 00:00:00 +0000",
        "List-Unsubscribe": "<mailto:unsub@y.com>",
    }


def test_extract_headers_case_insensitive():
    payload = {"payload": {"headers": [{"name": "from", "value": "x@y.com"}]}}
    headers = sampling.extract_headers(payload)
    assert headers["From"] == "x@y.com"

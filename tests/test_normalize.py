from __future__ import annotations

import pytest

from gmail_cleanup import normalize


def test_normalize_already_lowercase_unchanged():
    assert normalize.normalize_label("scribd") == "scribd"


def test_normalize_lowercases_mixed_case():
    assert normalize.normalize_label("Amazon") == "amazon"


def test_normalize_uppercase_lowered():
    assert normalize.normalize_label("AWS") == "aws"


def test_normalize_trims_leading_whitespace():
    assert normalize.normalize_label("  amazon") == "amazon"


def test_normalize_trims_trailing_whitespace():
    assert normalize.normalize_label("amazon  ") == "amazon"


def test_normalize_trims_tabs():
    assert normalize.normalize_label("\tamazon\t") == "amazon"


def test_normalize_internal_space_to_hyphen():
    assert normalize.normalize_label("Mac in cloud") == "mac-in-cloud"


def test_normalize_collapses_multiple_spaces_to_single_hyphen():
    assert normalize.normalize_label("Mac  in   cloud") == "mac-in-cloud"


def test_normalize_removes_brackets():
    assert normalize.normalize_label("[Notion]") == "notion"


def test_normalize_removes_period():
    assert normalize.normalize_label("docuwriter.ai") == "docuwriterai"


def test_normalize_preserves_existing_hyphen():
    assert normalize.normalize_label("Ein-Itin") == "ein-itin"


def test_normalize_preserves_underscore():
    assert normalize.normalize_label("foo_bar") == "foo_bar"


def test_normalize_preserves_digits():
    assert normalize.normalize_label("Japanesepod101") == "japanesepod101"


def test_normalize_junk_email_keeps_internal_hyphen():
    assert normalize.normalize_label("Junk E-mail") == "junk-e-mail"


def test_normalize_strips_misc_punctuation():
    assert normalize.normalize_label("foo!@#$%bar") == "foobar"


def test_normalize_is_idempotent():
    once = normalize.normalize_label("[Notion]")
    twice = normalize.normalize_label(once)
    assert once == twice


def test_normalize_idempotent_on_hyphenated():
    once = normalize.normalize_label("Mac in cloud")
    twice = normalize.normalize_label(once)
    assert once == twice


def test_should_skip_underscore_prefix_archive():
    assert normalize.should_skip("_Archive") is True


def test_should_skip_underscore_prefix_outbox():
    assert normalize.should_skip("_Outbox") is True


def test_should_skip_outlook_notes():
    assert normalize.should_skip("Notes") is True


def test_should_skip_outlook_deleted_items():
    assert normalize.should_skip("Deleted Items") is True


def test_should_skip_outlook_sent_items():
    assert normalize.should_skip("Sent Items") is True


def test_should_skip_outlook_junk():
    assert normalize.should_skip("Junk E-mail") is True


def test_should_skip_outlook_sync_issues():
    assert normalize.should_skip("Sync Issues") is True


def test_should_skip_outlook_conflicts():
    assert normalize.should_skip("Conflicts") is True


def test_should_skip_outlook_local_failures():
    assert normalize.should_skip("Local Failures") is True


def test_should_skip_outlook_server_failures():
    assert normalize.should_skip("Server Failures") is True


def test_should_skip_regular_label_returns_false():
    assert normalize.should_skip("Amazon") is False


def test_should_skip_lowercase_label_returns_false():
    assert normalize.should_skip("scribd") is False


def test_should_skip_with_extra_exclude():
    assert normalize.should_skip("MyLabel", extra=frozenset({"MyLabel"})) is True


def test_should_skip_extra_does_not_match_other_labels():
    assert normalize.should_skip("Amazon", extra=frozenset({"MyLabel"})) is False


def test_should_skip_outlook_excludes_are_case_sensitive():
    # The Outlook label names are fixed strings; lowercase variant is not excluded.
    assert normalize.should_skip("notes") is False


def test_excluded_labels_constant_contains_all_eight():
    expected = {
        "Notes",
        "Deleted Items",
        "Sent Items",
        "Junk E-mail",
        "Sync Issues",
        "Conflicts",
        "Local Failures",
        "Server Failures",
    }
    assert set(normalize.EXCLUDED_LABELS) == expected

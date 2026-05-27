from __future__ import annotations

import pytest

from gmail_cleanup import generate


# ---------------------------------------------------------------------------
# compile_gmail_query — used for sender_rules and additive_subject_rules
# (Rules.gs RULES and SUBJECT_RULES arrays).
# ---------------------------------------------------------------------------


def test_query_from_contains_single():
    assert generate.compile_gmail_query({"from_contains": "stripe.com"}) == "from:stripe.com"


def test_query_from_contains_any_single_item_no_parens():
    assert generate.compile_gmail_query({"from_contains_any": ["stripe.com"]}) == "from:stripe.com"


def test_query_from_contains_any_multiple_items_or_group():
    assert generate.compile_gmail_query(
        {"from_contains_any": ["telkomsa.net", "telkom.co.za"]}
    ) == "from:(telkomsa.net OR telkom.co.za)"


def test_query_from_not_contains_any():
    assert generate.compile_gmail_query(
        {"from_not_contains_any": ["cardnotification", "officialemail"]}
    ) == "-from:cardnotification -from:officialemail"


def test_query_from_with_negation_combined():
    q = generate.compile_gmail_query({
        "from_contains": "absa.africa",
        "from_not_contains_any": ["cardnotification", "officialemail"],
    })
    assert q == "from:absa.africa -from:cardnotification -from:officialemail"


def test_query_subject_contains_any_quotes_phrases_with_spaces():
    q = generate.compile_gmail_query({
        "subject_contains_any": ["receipt", "order confirmation", "your order"],
    })
    assert q == 'subject:(receipt OR "order confirmation" OR "your order")'


def test_query_subject_contains_any_single_word_no_quotes():
    assert generate.compile_gmail_query({"subject_contains_any": ["receipt"]}) == "subject:receipt"


# ---------------------------------------------------------------------------
# compile_js_condition — used for fallback_rules (Classifier.gs)
# ---------------------------------------------------------------------------


def test_js_from_contains():
    assert generate.compile_js_condition({"from_contains": "stripe.com"}) == "fromHas('stripe.com')"


def test_js_from_contains_any_single():
    assert generate.compile_js_condition({"from_contains_any": ["stripe.com"]}) == "fromHas('stripe.com')"


def test_js_from_contains_any_multiple():
    assert generate.compile_js_condition(
        {"from_contains_any": ["a", "b", "c"]}
    ) == "(fromHas('a') || fromHas('b') || fromHas('c'))"


def test_js_from_not_contains_any():
    assert generate.compile_js_condition(
        {"from_not_contains_any": ["x", "y"]}
    ) == "(!fromHas('x') && !fromHas('y'))"


def test_js_subject_contains():
    assert generate.compile_js_condition({"subject_contains": "receipt"}) == "subjHas('receipt')"


def test_js_subject_contains_any_multiple():
    assert generate.compile_js_condition(
        {"subject_contains_any": ["a", "b"]}
    ) == "(subjHas('a') || subjHas('b'))"


def test_js_subject_starts_with_any():
    assert generate.compile_js_condition(
        {"subject_starts_with_any": ["otp"]}
    ) == "(subject.trim().toLowerCase().startsWith('otp'))"


def test_js_subject_matches_regex():
    assert generate.compile_js_condition(
        {"subject_matches_regex": r"^\d{6,}\."}
    ) == r"/^\d{6,}\./.test(subject)"


def test_js_snippet_contains():
    assert generate.compile_js_condition({"snippet_contains": "buffelspoort"}) == "snipHas('buffelspoort')"


def test_js_text_contains_any_multiple():
    assert generate.compile_js_condition(
        {"text_contains_any": ["onlyfans", "vixen.com"]}
    ) == "(text.indexOf('onlyfans') !== -1 || text.indexOf('vixen.com') !== -1)"


def test_js_top_level_keys_anded():
    cond = generate.compile_js_condition({
        "from_contains": "absa.africa",
        "from_not_contains_any": ["cardnotification"],
    })
    # AND of two; ordering matters (insertion order)
    assert cond == "fromHas('absa.africa') && (!fromHas('cardnotification'))"


def test_js_any_of_or_group():
    cond = generate.compile_js_condition({
        "any_of": [
            {"from_contains": "echosign"},
            {"from_contains": "adobe acrobat"},
        ],
    })
    assert cond == "(fromHas('echosign') || fromHas('adobe acrobat'))"


def test_js_all_of_and_group():
    cond = generate.compile_js_condition({
        "all_of": [
            {"from_contains": "stripe"},
            {"subject_contains": "payout"},
        ],
    })
    assert cond == "(fromHas('stripe') && subjHas('payout'))"


def test_js_quotes_strings_with_single_quote_escaped():
    """Strings containing a single quote must be safely escaped for JS source."""
    assert generate.compile_js_condition({"from_contains": "it's"}) == r"fromHas('it\'s')"


# ---------------------------------------------------------------------------
# generate_rules_gs — snapshot of the emitted Rules.gs body
# ---------------------------------------------------------------------------


def test_generate_rules_gs_basic_snapshot():
    spec = {
        "version": 1,
        "sender_rules": [
            {"id": "stripe", "match": {"from_contains": "stripe.com"}, "labels": ["finance", "stripe"]},
            {"id": "telkom", "match": {"from_contains_any": ["telkomsa.net", "telkom.co.za"]}, "labels": ["bills", "telkom"]},
        ],
        "additive_subject_rules": [
            {"id": "subject-receipts", "match": {"subject_contains_any": ["receipt", "invoice"]}, "labels": ["receipts"]},
        ],
        "fallback_rules": [],
    }
    out = generate.generate_rules_gs(spec)
    assert "DO NOT EDIT" in out
    assert "from:stripe.com" in out
    assert "from:(telkomsa.net OR telkom.co.za)" in out
    assert "subject:(receipt OR invoice)" in out
    assert "['finance', 'stripe']" in out
    assert "['receipts']" in out
    # Both arrays declared
    assert "const RULES = [" in out
    assert "const SUBJECT_RULES = [" in out


# ---------------------------------------------------------------------------
# generate_classifier_gs — snapshot of the emitted Classifier.gs body
# ---------------------------------------------------------------------------


def test_generate_classifier_gs_basic_snapshot():
    spec = {
        "version": 1,
        "sender_rules": [],
        "additive_subject_rules": [],
        "fallback_rules": [
            {"id": "absa-work", "match": {"from_contains": "absa.africa", "from_not_contains_any": ["cardnotification"]}, "labels": ["work", "absa"]},
            {"id": "noreply", "match": {"from_contains_any": ["noreply", "no-reply"]}, "labels": ["notifications"]},
            {"id": "default", "labels": ["newsletters"]},
        ],
    }
    out = generate.generate_classifier_gs(spec)
    assert "DO NOT EDIT" in out
    assert "function classifyThread_" in out
    # The absa-work rule's condition
    assert "fromHas('absa.africa')" in out
    assert "!fromHas('cardnotification')" in out
    assert "return ['work', 'absa']" in out
    # The noreply rule
    assert "(fromHas('noreply') || fromHas('no-reply'))" in out
    assert "return ['notifications']" in out
    # The default trailing rule (no match)
    assert "return ['newsletters']" in out

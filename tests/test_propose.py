from __future__ import annotations

from gmail_cleanup import propose


def test_categorize_finance_by_known_domain():
    assert propose.categorize_sender("statements@chase.com", [""], False) == "Finance"
    assert propose.categorize_sender("noreply@paypal.com", [""], False) == "Finance"


def test_categorize_travel_by_known_domain():
    assert propose.categorize_sender("automated@airbnb.com", [""], False) == "Travel"
    assert propose.categorize_sender("noreply@booking.com", [""], False) == "Travel"


def test_categorize_shopping_by_known_domain():
    assert propose.categorize_sender("auto-confirm@amazon.com", [""], False) == "Shopping"


def test_categorize_receipts_by_subject_keyword():
    assert propose.categorize_sender("orders@randomstore.example", ["Your receipt for order #123"], False) == "Receipts"
    assert propose.categorize_sender("billing@whatever.example", ["Invoice INV-001"], False) == "Receipts"


def test_categorize_newsletters_by_unsubscribe_header():
    assert propose.categorize_sender("news@unknown-newsletter.example", ["Weekly digest"], True) == "Newsletters"


def test_categorize_substack_known_domain():
    assert propose.categorize_sender("noreply@substack.com", [""], False) == "Newsletters"
    assert propose.categorize_sender("author@somesub.substack.com", [""], False) == "Newsletters"


def test_categorize_personal_by_personal_domain():
    assert propose.categorize_sender("friend@gmail.com", ["hey want to grab coffee?"], False) == "Personal"
    assert propose.categorize_sender("cousin@yahoo.com", [""], False) == "Personal"


def test_categorize_falls_through_to_other():
    assert propose.categorize_sender("random@unknown-co.example", [""], False) == "Other"


def test_known_finance_keywords_in_domain():
    # generic bank-like domains
    assert propose.categorize_sender("alerts@somebank.com", [""], False) == "Finance"
    assert propose.categorize_sender("auto@capitec.co.za", [""], False) == "Finance"


def test_sender_label_from_email_strips_subdomain_and_suffix():
    assert propose.sender_label("statements@chase.com") == "Chase"
    assert propose.sender_label("automated@airbnb.com") == "Airbnb"
    assert propose.sender_label("noreply@somesub.substack.com") == "Substack"
    assert propose.sender_label("billing@my-store.co.za") == "My-Store"


def test_sender_label_handles_malformed():
    assert propose.sender_label("") == ""
    assert propose.sender_label("not-an-email") == ""


def _sample(senders_with_counts: dict[str, int], unsubscribe: set[str] = frozenset(), subjects: dict[str, list[str]] | None = None) -> dict:
    """Build a fake discover.json blob from a counts dict."""
    subjects = subjects or {}
    sample = []
    for email, count in senders_with_counts.items():
        subs = subjects.get(email, [""]) * count
        for s in subs[:count]:
            sample.append({
                "From": email,
                "FromEmail": email,
                "Subject": s,
                "ListUnsubscribe": "<mailto:u@x>" if email in unsubscribe else "",
            })
    return {
        "sample": sample,
        "sender_histogram": senders_with_counts,
        "top_senders": sorted(senders_with_counts.items(), key=lambda kv: -kv[1]),
        "existing_labels": [],
    }


def test_propose_tree_buckets_by_category():
    discover = _sample({
        "statements@chase.com": 25,
        "alerts@chase.com": 10,
        "automated@airbnb.com": 8,
        "auto-confirm@amazon.com": 15,
        "noreply@substack.com": 30,
    }, unsubscribe={"noreply@substack.com"})
    tree = propose.propose_tree(discover, top_n_per_category=5, min_sender_count=3)
    labels = set(tree["labels"])
    assert "Finance" in labels
    assert "Finance/Chase" in labels
    assert "Travel" in labels
    assert "Travel/Airbnb" in labels
    assert "Shopping" in labels
    assert "Shopping/Amazon" in labels
    assert "Newsletters" in labels
    assert "Newsletters/Substack" in labels


def test_propose_tree_respects_min_sender_count():
    discover = _sample({
        "statements@chase.com": 2,  # below threshold
        "alerts@chase.com": 1,
        "auto-confirm@amazon.com": 50,
    })
    tree = propose.propose_tree(discover, top_n_per_category=5, min_sender_count=3)
    labels = set(tree["labels"])
    # Finance category appears because we still create top-level even if no sub passes threshold
    assert "Finance" in labels
    # but no sub-label for chase since each is below 3
    assert "Finance/Chase" not in labels
    # amazon clears threshold
    assert "Shopping/Amazon" in labels


def test_propose_tree_caps_subs_per_category():
    senders = {f"x{i}@chase.com": 100 - i for i in range(10)}
    discover = _sample(senders)
    tree = propose.propose_tree(discover, top_n_per_category=3, min_sender_count=1)
    finance_subs = [l for l in tree["labels"] if l.startswith("Finance/")]
    # all chase senders normalize to same sender_label "Chase", so we get 1 sub
    assert finance_subs == ["Finance/Chase"]


def test_propose_tree_returns_label_evidence():
    discover = _sample({"statements@chase.com": 25})
    tree = propose.propose_tree(discover, top_n_per_category=5, min_sender_count=3)
    assert "evidence" in tree
    assert "Finance/Chase" in tree["evidence"]
    ev = tree["evidence"]["Finance/Chase"]
    assert ev["count"] == 25
    assert ev["example_sender"] == "statements@chase.com"


def test_propose_tree_includes_existing_labels_in_output():
    discover = _sample({"a@chase.com": 5})
    discover["existing_labels"] = [{"id": "Label_1", "name": "MyOldLabel", "type": "user"}]
    tree = propose.propose_tree(discover, top_n_per_category=5, min_sender_count=3)
    assert "existing_labels" in tree
    assert tree["existing_labels"] == [{"id": "Label_1", "name": "MyOldLabel", "type": "user"}]

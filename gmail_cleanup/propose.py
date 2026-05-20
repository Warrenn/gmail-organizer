from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path

from gmail_cleanup.sampling import parse_from_header

DOMAIN_CATEGORIES: dict[str, str] = {
    # Finance / banking / payments
    "chase.com": "Finance",
    "chasebank.com": "Finance",
    "paypal.com": "Finance",
    "stripe.com": "Finance",
    "wise.com": "Finance",
    "revolut.com": "Finance",
    "americanexpress.com": "Finance",
    "amex.com": "Finance",
    "capitec.co.za": "Finance",
    "fnb.co.za": "Finance",
    "absa.co.za": "Finance",
    "nedbank.co.za": "Finance",
    "standardbank.co.za": "Finance",
    "discovery.co.za": "Finance",
    "investec.com": "Finance",
    "investec.co.za": "Finance",
    # Shopping
    "amazon.com": "Shopping",
    "amazon.co.za": "Shopping",
    "amazon.co.uk": "Shopping",
    "takealot.com": "Shopping",
    "ebay.com": "Shopping",
    "etsy.com": "Shopping",
    "shopify.com": "Shopping",
    "aliexpress.com": "Shopping",
    # Travel
    "airbnb.com": "Travel",
    "booking.com": "Travel",
    "uber.com": "Travel",
    "lyft.com": "Travel",
    "expedia.com": "Travel",
    "kayak.com": "Travel",
    "hotels.com": "Travel",
    "flysafair.co.za": "Travel",
    "kulula.com": "Travel",
    "ba.com": "Travel",
    "delta.com": "Travel",
    "united.com": "Travel",
    "emirates.com": "Travel",
    "qatar.com": "Travel",
    "tripadvisor.com": "Travel",
    # Social
    "facebook.com": "Social",
    "facebookmail.com": "Social",
    "instagram.com": "Social",
    "twitter.com": "Social",
    "x.com": "Social",
    "linkedin.com": "Social",
    "youtube.com": "Social",
    "reddit.com": "Social",
    # Work / dev tools
    "github.com": "Work",
    "gitlab.com": "Work",
    "notion.so": "Work",
    "slack.com": "Work",
    "atlassian.com": "Work",
    "asana.com": "Work",
    "trello.com": "Work",
    "figma.com": "Work",
    "linear.app": "Work",
    "vercel.com": "Work",
    "netlify.com": "Work",
    # Newsletters / media
    "substack.com": "Newsletters",
    "medium.com": "Newsletters",
    "nytimes.com": "Newsletters",
    "economist.com": "Newsletters",
    "ft.com": "Newsletters",
    "wsj.com": "Newsletters",
    "theatlantic.com": "Newsletters",
    "newyorker.com": "Newsletters",
    # Subscriptions / streaming
    "netflix.com": "Subscriptions",
    "spotify.com": "Subscriptions",
    "applemusic.com": "Subscriptions",
    "hulu.com": "Subscriptions",
    "disneyplus.com": "Subscriptions",
    "showmax.com": "Subscriptions",
    # Notifications / utilities
    "apple.com": "Notifications",
    "google.com": "Notifications",
    "googlemail.com": "Notifications",
    "accounts.google.com": "Notifications",
    "dropbox.com": "Notifications",
    "1password.com": "Notifications",
    # Personal email providers
    "gmail.com": "Personal",
    "yahoo.com": "Personal",
    "outlook.com": "Personal",
    "hotmail.com": "Personal",
    "icloud.com": "Personal",
    "me.com": "Personal",
    "live.com": "Personal",
    "aol.com": "Personal",
    "protonmail.com": "Personal",
    "fastmail.com": "Personal",
}

FINANCE_DOMAIN_KEYWORDS = (
    "bank", "capitec", "fnb", "absa", "nedbank", "standardbank",
    "paypal", "stripe", "wise", "revolut", "discovery",
)

RECEIPT_SUBJECT_PATTERNS = (
    re.compile(r"\breceipt\b", re.I),
    re.compile(r"\binvoice\b", re.I),
    re.compile(r"order\s+confirmation", re.I),
    re.compile(r"payment\s+confirmation", re.I),
    re.compile(r"your\s+order", re.I),
    re.compile(r"thank\s+you\s+for\s+your\s+(order|purchase)", re.I),
)

MULTI_PART_TLDS = (".co.za", ".co.uk", ".com.au", ".co.nz", ".com.br", ".co.jp")


def _domain_of(email: str) -> str:
    if "@" not in email:
        return ""
    return email.split("@", 1)[1].lower().strip()


def categorize_sender(email: str, sample_subjects: Iterable[str], has_unsubscribe: bool) -> str:
    domain = _domain_of(email)
    if not domain:
        return "Other"

    # 1. Exact known domain match
    if domain in DOMAIN_CATEGORIES:
        return DOMAIN_CATEGORIES[domain]

    # 2. Subdomain of a known domain
    for known_domain, category in DOMAIN_CATEGORIES.items():
        if domain.endswith("." + known_domain):
            return category

    # 3. Finance keywords in domain
    if any(kw in domain for kw in FINANCE_DOMAIN_KEYWORDS):
        return "Finance"

    # 4. Receipt subject keywords
    for subject in sample_subjects:
        if subject and any(p.search(subject) for p in RECEIPT_SUBJECT_PATTERNS):
            return "Receipts"

    # 5. Unsubscribe header → Newsletter
    if has_unsubscribe:
        return "Newsletters"

    return "Other"


def sender_label(email: str) -> str:
    domain = _domain_of(email)
    if not domain:
        return ""

    stripped = domain
    matched_multi = False
    for tld in MULTI_PART_TLDS:
        if stripped.endswith(tld):
            stripped = stripped[: -len(tld)]
            matched_multi = True
            break
    if not matched_multi:
        if "." not in stripped:
            return ""
        stripped = stripped.rsplit(".", 1)[0]

    if not stripped:
        return ""
    last = stripped.rsplit(".", 1)[-1]
    if not last:
        return ""
    return last.title()


def propose_tree(
    discover: dict,
    top_n_per_category: int = 5,
    min_sender_count: int = 3,
) -> dict:
    sample = discover.get("sample", [])
    histogram = discover.get("sender_histogram", {})

    subjects_by_sender: dict[str, list[str]] = defaultdict(list)
    unsubscribe_by_sender: dict[str, bool] = defaultdict(bool)
    for entry in sample:
        email = entry.get("FromEmail") or parse_from_header(entry.get("From", ""))
        if not email:
            continue
        subj = entry.get("Subject", "")
        if subj and len(subjects_by_sender[email]) < 5:
            subjects_by_sender[email].append(subj)
        if entry.get("ListUnsubscribe"):
            unsubscribe_by_sender[email] = True

    # category -> sender_label -> {count, top_sender_email, top_sender_count}
    grouped: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"count": 0, "top_sender": "", "top_sender_count": 0}))
    category_totals: dict[str, int] = defaultdict(int)

    for email, count in histogram.items():
        category = categorize_sender(
            email,
            subjects_by_sender.get(email, []),
            unsubscribe_by_sender.get(email, False),
        )
        label = sender_label(email)
        category_totals[category] += count
        if not label:
            continue
        bucket = grouped[category][label]
        bucket["count"] += count
        if count > bucket["top_sender_count"]:
            bucket["top_sender"] = email
            bucket["top_sender_count"] = count

    labels: list[str] = []
    evidence: dict[str, dict] = {}

    for category in sorted(category_totals.keys()):
        labels.append(category)
        evidence[category] = {"count": category_totals[category]}

        candidates = grouped.get(category, {})
        filtered = [
            (lbl, info) for lbl, info in candidates.items()
            if info["top_sender_count"] >= min_sender_count
        ]
        filtered.sort(key=lambda kv: (-kv[1]["count"], kv[0]))
        for lbl, info in filtered[:top_n_per_category]:
            full = f"{category}/{lbl}"
            labels.append(full)
            evidence[full] = {
                "count": info["count"],
                "example_sender": info["top_sender"],
            }

    return {
        "labels": labels,
        "evidence": evidence,
        "existing_labels": discover.get("existing_labels", []),
    }


def render_tree(tree: dict) -> str:
    lines: list[str] = []
    current_category: str | None = None
    for label in tree["labels"]:
        ev = tree["evidence"].get(label, {})
        if "/" in label:
            _, sub = label.split("/", 1)
            ex = ev.get("example_sender", "")
            lines.append(f"    └─ {sub}    ({ev.get('count', 0)} messages, e.g. {ex})")
        else:
            current_category = label
            lines.append(f"\n{label}    ({ev.get('count', 0)} messages total)")
    existing = tree.get("existing_labels", [])
    if existing:
        lines.append("\nExisting labels in your account (will be preserved):")
        for l in existing:
            lines.append(f"  • {l['name']}")
    return "\n".join(lines).strip()


def run_propose(discover_path: Path, output_path: Path, top_n: int = 5, min_count: int = 3) -> dict:
    discover = json.loads(discover_path.read_text())
    tree = propose_tree(discover, top_n_per_category=top_n, min_sender_count=min_count)
    output_path.write_text(json.dumps(tree, indent=2, ensure_ascii=False))
    return tree

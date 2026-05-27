"""Property tests for gmail_cleanup/rules.yaml.

Catches creative bad rules that the corpus regression test can't:
- regex patterns that match (almost) anything
- labels that don't follow the project convention
- empty/bogus rule bodies
- unreachable rules (default placed before more-specific rules)

Runs on every PR. The feedback-loop autonomous workflow relies on these
tests to refuse rule changes that would shrink-blast the classifier.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from gmail_cleanup import normalize, rule_interpreter


RULES_PATH = Path(__file__).parent.parent / "gmail_cleanup" / "rules.yaml"


@pytest.fixture(scope="module")
def spec() -> dict:
    return rule_interpreter.load_rules(RULES_PATH)


def _iter_all_rules(spec: dict):
    for section in ("sender_rules", "additive_subject_rules", "fallback_rules"):
        for rule in spec.get(section, []):
            yield section, rule


# ---------------------------------------------------------------------------
# Property 1: no regex pattern is overly permissive
# ---------------------------------------------------------------------------


_LOW_INFO_PROBES = ["", "a", "1", " ", "x"]


def _is_regex_too_permissive(pattern: str) -> bool:
    """Heuristic: a regex that matches any of {"", "a", " ", "1", "x"} is
    too permissive to be useful as a discriminator."""
    try:
        compiled = re.compile(pattern)
    except re.error:
        return True  # broken regex is a different problem; flag it
    for probe in _LOW_INFO_PROBES:
        if compiled.search(probe) is not None:
            return True
    return False


def _walk_match_objects(match: dict):
    """Yield every match-object found in match, including nested any_of/all_of."""
    yield match
    for nested_list in (match.get("any_of") or [], match.get("all_of") or []):
        for nested in nested_list:
            yield from _walk_match_objects(nested)


def test_no_regex_is_overly_permissive(spec):
    violations = []
    for section, rule in _iter_all_rules(spec):
        match = rule.get("match") or {}
        for m in _walk_match_objects(match):
            pattern = m.get("subject_matches_regex")
            if pattern and _is_regex_too_permissive(pattern):
                violations.append((section, rule["id"], pattern))
    assert not violations, (
        "Regex patterns that match low-info strings (suggests rule is too permissive):\n  "
        + "\n  ".join(f"{s}/{rid}: {p!r}" for s, rid, p in violations)
    )


# ---------------------------------------------------------------------------
# Property 2: every label follows the project convention
# ---------------------------------------------------------------------------


def _label_is_compliant(label: str) -> bool:
    if normalize.should_skip(label):
        return True
    return normalize.normalize_label(label) == label


def test_all_labels_follow_convention(spec):
    violations = []
    for section, rule in _iter_all_rules(spec):
        for lbl in rule.get("labels", []):
            if not _label_is_compliant(lbl):
                violations.append((section, rule["id"], lbl))
    assert not violations, (
        "Labels not following lowercase/hyphenated convention (and not in EXCLUDED_LABELS):\n  "
        + "\n  ".join(f"{s}/{rid}: {lbl!r}" for s, rid, lbl in violations)
    )


# ---------------------------------------------------------------------------
# Property 3: no rule's match condition is trivially-true
# ---------------------------------------------------------------------------


def _is_match_trivially_true(match: dict) -> bool:
    """A match is trivially true if every operator's payload is empty in a way
    that makes the operator a no-op (e.g., from_not_contains_any: [] is
    vacuously true; from_contains: '' matches every input)."""
    if not match:
        return True
    for key, value in match.items():
        if key == "from_not_contains_any":
            # Vacuously true on empty list; that's a no-op but not trivially-true alone.
            continue
        if key == "from_contains" and value == "":
            return True
        if key == "subject_contains" and value == "":
            return True
        if key == "snippet_contains" and value == "":
            return True
        if key in {"from_contains_any", "subject_contains_any", "snippet_contains_any", "text_contains_any"}:
            if not value:
                return True  # never matches — also bad
            if "" in value:
                return True  # contains empty string substring → always true
        if key == "any_of":
            if not value:
                return True
        if key == "all_of":
            if not value:
                return True
    return False


def test_no_rule_has_trivially_true_match(spec):
    violations = []
    for section, rule in _iter_all_rules(spec):
        match = rule.get("match")
        if match is None:
            # Trailing default fallback can omit match; that's intentional.
            continue
        if _is_match_trivially_true(match):
            violations.append((section, rule["id"], match))
    assert not violations, (
        "Rules with trivially-true (or empty-list) match conditions:\n  "
        + "\n  ".join(f"{s}/{rid}: {m!r}" for s, rid, m in violations)
    )


# ---------------------------------------------------------------------------
# Property 4: only the LAST fallback_rule may omit `match`
# ---------------------------------------------------------------------------


def test_only_last_fallback_can_be_default(spec):
    fallback = spec["fallback_rules"]
    if not fallback:
        return
    for rule in fallback[:-1]:
        assert rule.get("match") is not None, (
            f"non-trailing fallback_rule {rule['id']!r} omits 'match' — it would "
            "shadow every later rule (already enforced by validator but double-check here)"
        )


# ---------------------------------------------------------------------------
# Property 5: no duplicate (section, rule_id) pairs across sections
# ---------------------------------------------------------------------------


def test_no_duplicate_rule_ids_across_sections(spec):
    """The interpreter already enforces unique ids across the whole file,
    but this property test makes the constraint visible at the spec level."""
    seen: set[str] = set()
    duplicates: list[str] = []
    for _, rule in _iter_all_rules(spec):
        rid = rule["id"]
        if rid in seen:
            duplicates.append(rid)
        seen.add(rid)
    assert not duplicates, f"duplicate rule ids: {duplicates}"

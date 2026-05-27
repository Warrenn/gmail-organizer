from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml


SUPPORTED_VERSION = 1

SENDER_OPERATORS = frozenset({
    "from_contains",
    "from_contains_any",
    "from_not_contains_any",
})

CONTENT_OPERATORS = frozenset({
    "subject_contains",
    "subject_contains_any",
    "subject_not_contains_any",
    "subject_starts_with_any",
    "subject_matches_regex",
    "snippet_contains",
    "snippet_contains_any",
    "text_contains_any",
})

LOGICAL_OPERATORS = frozenset({"any_of", "all_of"})

ALL_OPERATORS = SENDER_OPERATORS | CONTENT_OPERATORS | LOGICAL_OPERATORS


def load_rules(path: Path) -> dict:
    return load_rules_from_string(path.read_text())


def load_rules_from_string(text: str) -> dict:
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError("rule spec must be a YAML mapping at the top level")

    version = raw.get("version")
    if version is None:
        raise ValueError("rule spec missing required 'version' field")
    if version != SUPPORTED_VERSION:
        raise ValueError(
            f"unsupported rule spec version {version}; this interpreter supports {SUPPORTED_VERSION}"
        )

    spec = {
        "version": version,
        "sender_rules": list(raw.get("sender_rules") or []),
        "additive_subject_rules": list(raw.get("additive_subject_rules") or []),
        "fallback_rules": list(raw.get("fallback_rules") or []),
    }

    _validate(spec)
    return spec


def _validate(spec: dict) -> None:
    seen_ids: set[str] = set()

    for rule in spec["sender_rules"]:
        _validate_rule(rule, allow_content_operators=False, section="sender_rules", seen_ids=seen_ids)

    for rule in spec["additive_subject_rules"]:
        _validate_rule(rule, allow_content_operators=True, section="additive_subject_rules", seen_ids=seen_ids)

    for i, rule in enumerate(spec["fallback_rules"]):
        is_last = i == len(spec["fallback_rules"]) - 1
        _validate_rule(
            rule,
            allow_content_operators=True,
            section="fallback_rules",
            seen_ids=seen_ids,
            allow_missing_match=is_last,
        )


def _validate_rule(
    rule: dict,
    *,
    allow_content_operators: bool,
    section: str,
    seen_ids: set[str],
    allow_missing_match: bool = False,
) -> None:
    rid = rule.get("id")
    if not rid:
        raise ValueError(f"{section}: rule missing required 'id' field: {rule!r}")
    if rid in seen_ids:
        raise ValueError(f"duplicate rule id: {rid!r}")
    seen_ids.add(rid)

    labels = rule.get("labels")
    if not labels or not isinstance(labels, list):
        raise ValueError(f"{section}/{rid}: 'labels' must be a non-empty list")

    match = rule.get("match")
    if match is None:
        if not allow_missing_match:
            raise ValueError(f"{section}/{rid}: rule must have a 'match' field")
        return
    if not isinstance(match, dict):
        raise ValueError(f"{section}/{rid}: 'match' must be a mapping, got {type(match).__name__}")

    _validate_match_object(match, allow_content_operators=allow_content_operators, rule_id=rid, section=section)


def _validate_match_object(
    match: dict,
    *,
    allow_content_operators: bool,
    rule_id: str,
    section: str,
) -> None:
    for key, value in match.items():
        if key not in ALL_OPERATORS:
            raise ValueError(f"{section}/{rule_id}: unknown operator {key!r}")
        if key in CONTENT_OPERATORS and not allow_content_operators:
            raise ValueError(
                f"{section}/{rule_id}: sender_rule match may not use content operator {key!r}"
            )
        if key in LOGICAL_OPERATORS:
            if not allow_content_operators:
                raise ValueError(
                    f"{section}/{rule_id}: sender_rule match may not use logical operator {key!r} in v1"
                )
            if not isinstance(value, list):
                raise ValueError(f"{section}/{rule_id}: {key!r} must be a list of match-objects")
            for nested in value:
                if not isinstance(nested, dict):
                    raise ValueError(f"{section}/{rule_id}: {key!r} entries must be match-objects")
                _validate_match_object(nested, allow_content_operators=True, rule_id=rule_id, section=section)


def evaluate_match(match: dict, thread: dict) -> bool:
    sender = (thread.get("from") or "").lower()
    subject = thread.get("subject") or ""
    snippet = (thread.get("snippet") or "").lower()
    subject_lower = subject.lower()
    text = f"{sender} || {subject_lower} || {snippet}"

    for op, value in match.items():
        if not _check_operator(op, value, sender, subject, subject_lower, snippet, text, thread):
            return False
    return True


def _check_operator(
    op: str,
    value: Any,
    sender: str,
    subject: str,
    subject_lower: str,
    snippet: str,
    text: str,
    thread: dict,
) -> bool:
    if op == "from_contains":
        return value.lower() in sender
    if op == "from_contains_any":
        return any(s.lower() in sender for s in value)
    if op == "from_not_contains_any":
        return not any(s.lower() in sender for s in value)

    if op == "subject_contains":
        return value.lower() in subject_lower
    if op == "subject_contains_any":
        return any(s.lower() in subject_lower for s in value)
    if op == "subject_not_contains_any":
        return not any(s.lower() in subject_lower for s in value)
    if op == "subject_starts_with_any":
        stripped = subject.strip().lower()
        return any(stripped.startswith(s.lower()) for s in value)
    if op == "subject_matches_regex":
        return re.search(value, subject) is not None

    if op == "snippet_contains":
        return value.lower() in snippet
    if op == "snippet_contains_any":
        return any(s.lower() in snippet for s in value)

    if op == "text_contains_any":
        return any(s.lower() in text for s in value)

    if op == "any_of":
        return any(evaluate_match(nested, thread) for nested in value)
    if op == "all_of":
        return all(evaluate_match(nested, thread) for nested in value)

    raise ValueError(f"unknown operator at evaluation time: {op!r}")


def classify(thread: dict, spec: dict) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()

    def add(new_labels: list[str]) -> None:
        for label in new_labels:
            if label not in seen:
                labels.append(label)
                seen.add(label)

    for rule in spec["sender_rules"]:
        if evaluate_match(rule["match"], thread):
            add(rule["labels"])
            break

    for rule in spec["additive_subject_rules"]:
        if evaluate_match(rule["match"], thread):
            add(rule["labels"])

    if not labels:
        for rule in spec["fallback_rules"]:
            match = rule.get("match")
            if match is None or evaluate_match(match, thread):
                add(rule["labels"])
                break

    return labels

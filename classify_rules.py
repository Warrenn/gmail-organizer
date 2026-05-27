"""Rule-based classifier — thin wrapper around gmail_cleanup.rule_interpreter.

Reads unlabeled_messages.json, produces classification.json using the rules
defined in gmail_cleanup/rules.yaml (the single source of truth).

This file used to contain hand-written if/return chains; that logic was
ported into gmail_cleanup/rules.yaml during the feedback-loop Phase 0
refactor. Edits to classifier behavior now happen in rules.yaml, not here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from gmail_cleanup import rule_interpreter


_RULES_PATH = Path(__file__).parent / "gmail_cleanup" / "rules.yaml"
_cached_spec: dict | None = None


def _get_spec() -> dict:
    global _cached_spec
    if _cached_spec is None:
        _cached_spec = rule_interpreter.load_rules(_RULES_PATH)
    return _cached_spec


def classify(msg: dict) -> list[str]:
    """Classify a single message dict to a list of label names.

    Accepts the same shape as the legacy classify_rules.py: a dict with
    keys "from", "subject", "snippet" (all optional, default empty).
    """
    return rule_interpreter.classify(msg, _get_spec())


def main():
    src = Path("unlabeled_messages.json")
    dst = Path("classification.json")
    data = json.loads(src.read_text())
    messages = data["messages"]
    available = set(data.get("available_labels", []))

    classification: dict[str, list[str]] = {}
    label_counts: dict[str, int] = {}
    unmapped = 0

    available_cf = {a.casefold(): a for a in available}

    for msg in messages:
        labels = classify(msg)

        if available:
            filtered: list[str] = []
            for lbl in labels:
                canonical = available_cf.get(lbl.casefold())
                if canonical:
                    filtered.append(canonical)
            if not filtered:
                filtered = ["Other"] if "Other" in available else []
                unmapped += 1
            labels = filtered

        if labels:
            classification[msg["id"]] = labels
            for l in labels:
                label_counts[l] = label_counts.get(l, 0) + 1

    dst.write_text(json.dumps(classification, indent=2))
    print(f"classified {len(classification)} messages; {unmapped} fell through to Other", file=sys.stderr)
    print(f"per-label counts:", file=sys.stderr)
    for name in sorted(label_counts, key=lambda n: -label_counts[n]):
        print(f"  {label_counts[name]:5d}  {name}", file=sys.stderr)


if __name__ == "__main__":
    main()

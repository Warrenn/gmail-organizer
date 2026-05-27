"""Corpus regression test.

Loads tests/corpus.json (the agreement-filtered set of threads with their
expected labels) and asserts the interpreter produces identical output for
each. This is the keystone guardrail for rule changes: any modification to
gmail_cleanup/rules.yaml that breaks an existing corpus thread fails CI.

If `tests/corpus.json` is absent (e.g., fresh checkout), the test is skipped
with instructions for regenerating it.

To rebuild: `python -m gmail_cleanup corpus-build --per-label 5`
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from gmail_cleanup import rule_interpreter


CORPUS_PATH = Path(__file__).parent / "corpus.json"
RULES_PATH = Path(__file__).parent.parent / "gmail_cleanup" / "rules.yaml"


def _load_corpus() -> dict | None:
    if not CORPUS_PATH.exists():
        return None
    return json.loads(CORPUS_PATH.read_text())


def test_corpus_regression():
    corpus_data = _load_corpus()
    if corpus_data is None:
        pytest.skip(
            f"{CORPUS_PATH} not present — run "
            "`python -m gmail_cleanup corpus-build` to bootstrap"
        )

    spec = rule_interpreter.load_rules(RULES_PATH)
    mismatches: list[dict] = []
    for thread in corpus_data["threads"]:
        actual = sorted(rule_interpreter.classify(thread, spec))
        expected = sorted(thread["expected_labels"])
        if actual != expected:
            mismatches.append({
                "thread_id": thread["thread_id"],
                "from": thread["from"][:50],
                "subject": thread["subject"][:50],
                "expected": expected,
                "actual": actual,
            })

    if mismatches:
        msg_lines = [
            f"\n{len(mismatches)} / {len(corpus_data['threads'])} corpus threads "
            "broke under the current rules.yaml.",
            "Either revert the rule change or rebuild the corpus with "
            "`python -m gmail_cleanup corpus-build`.",
            "",
            "First 20 mismatches:",
        ]
        for m in mismatches[:20]:
            msg_lines.append(
                f"  {m['from']:50s} {m['subject']:50s}"
            )
            msg_lines.append(f"    expected: {m['expected']}")
            msg_lines.append(f"    actual:   {m['actual']}")
        if len(mismatches) > 20:
            msg_lines.append(f"  ... and {len(mismatches) - 20} more")
        pytest.fail("\n".join(msg_lines))


def test_corpus_threads_have_required_fields():
    """Defensive — corpus structure must contain the fields the interpreter
    needs. Catches a regression in corpus-build."""
    corpus_data = _load_corpus()
    if corpus_data is None:
        pytest.skip(f"{CORPUS_PATH} not present")
    required = {"thread_id", "from", "subject", "snippet", "expected_labels"}
    for t in corpus_data["threads"]:
        missing = required - set(t.keys())
        assert not missing, f"corpus thread missing fields: {missing} in {t.get('thread_id', '?')}"

"""Regression: the amazon-sender rule must not tag retail Amazon mail as work/aws.

Before the fix, `amazon-sender` matched all of `amazon.com` (from_contains),
so retail order/Prime/Kindle mail was labeled [work, aws]. It is now narrowed
to AWS-identifying domains; retail amazon.com falls through instead.
"""
from __future__ import annotations

from pathlib import Path

from gmail_cleanup import rule_interpreter

_RULES_PATH = Path(__file__).resolve().parent.parent / "gmail_cleanup" / "rules.yaml"


def _classify(**thread) -> list[str]:
    spec = rule_interpreter.load_rules(_RULES_PATH)
    return rule_interpreter.classify(thread, spec)


def test_retail_amazon_not_labeled_work_or_aws():
    labels = _classify(
        **{
            "from": "shipment-tracking@amazon.com",
            "subject": "Your Amazon.com order has shipped",
            "snippet": "Your package is on the way.",
        }
    )
    assert "work" not in labels
    assert "aws" not in labels


def test_aws_subdomain_still_labeled_aws():
    labels = _classify(
        **{
            "from": "no-reply@aws.amazon.com",
            "subject": "Your AWS account",
            "snippet": "AWS billing summary.",
        }
    )
    assert "aws" in labels


def test_amazonaws_still_labeled_aws():
    labels = _classify(
        **{
            "from": "ses@email.amazonaws.com",
            "subject": "Notification",
            "snippet": "",
        }
    )
    assert "aws" in labels

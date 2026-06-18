"""scan Lambda — the Step Functions entry step.

Loads the Gmail token from SSM (into the environment only — never a file),
scans the mailbox for +X/-X marker labels, and — only if markers exist —
builds the regression corpus. Uploads ``feedback.json`` and ``tests/corpus.json``
to the S3 artifact bucket for the downstream refine task, and returns
``hasMarkers`` so the state machine's Choice can skip the (costly) refine →
deploy → cleanup branch when there is nothing to do.

Thin wrapper: the actual logic lives in the existing ``gmail_cleanup``
feedback-scan + corpus-build commands, identical to scripts/feedback-loop.sh.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

# Support both `import lambdas.scan.handler` (tests/local) and the Lambda
# runtime layout where common.py sits alongside on the path.
try:
    from lambdas import common
except ImportError:  # pragma: no cover - runtime import shape
    import common  # type: ignore

from gmail_cleanup import corpus, feedback
from gmail_cleanup import auth


def handler(event, context=None):
    bucket = common.env("ARTIFACT_BUCKET", required=True)
    prefix = common.env("ARTIFACT_PREFIX", default="")
    per_label = int(common.env("CORPUS_PER_LABEL", default="3"))

    # Gmail token → env only. Never written to disk; dies with the process.
    common.load_secret_into_env(auth.TOKEN_ENV, "gmail-token-json")
    service = auth.get_service()

    workdir = Path(tempfile.mkdtemp(prefix="scan-"))
    feedback_path = workdir / "feedback.json"

    result = feedback.scan_for_markers(service)
    feedback_path.write_text(json.dumps(result, indent=2))
    marker_count = len(result.get("markers", []))
    has_markers = marker_count > 0

    if not has_markers:
        # Nothing to refine. Skip corpus build (bounds Gmail sampling cost) and
        # skip the artifact upload — the state machine stops on hasMarkers=false.
        return {"hasMarkers": False, "markerCount": 0}

    # Markers found: ship feedback.json + a fresh regression corpus so the
    # refine task can verify -X survivors / corpus regression.
    common.upload(bucket, "feedback.json", feedback_path, prefix=prefix)

    try:
        from gmail_cleanup import rule_interpreter

        raw = corpus.build_corpus(service, per_label_sample_size=per_label)
        # Filter to interpreter-agreement using the repo's checked-in rules, the
        # same as `corpus-build`. The rules file ships inside the Lambda package.
        rules_path = Path(__file__).resolve().parent / "rules.yaml"
        if not rules_path.exists():
            # Fall back to the package-relative rules if not bundled alongside.
            rules_path = Path(rule_interpreter.__file__).resolve().parent / "rules.yaml"
        spec = rule_interpreter.load_rules(rules_path)
        filtered, _disagreements = corpus.filter_to_agreement(raw, spec)
        corpus_path = workdir / "corpus.json"
        corpus_path.write_text(json.dumps(filtered, indent=2))
        common.upload(bucket, "corpus.json", corpus_path, prefix=prefix)
    except Exception as e:  # noqa: BLE001 - non-fatal, refine still runs
        # corpus-build is best-effort (matches feedback-loop.sh): if it fails,
        # refine still runs and will bail on any -X it can't verify.
        print(f"corpus-build failed (non-fatal): {e}")

    return {"hasMarkers": True, "markerCount": marker_count}

"""cleanup-markers Lambda — applies the resolved +X/-X markers to Gmail.

Replaces cleanup-markers.yml. Runs last in the state machine, after refine has
merged the rule changes and uploaded ``feedback_resolved.json`` to S3 (the file
is no longer committed — see STRATEGY.md Q2). Reads that manifest from S3 and,
for each resolved marker, adds/removes the target label on the source threads
and deletes the marker label — via the existing ``cleanup-markers`` command.

Gmail token is loaded from SSM into the environment only — never a file.
"""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

try:
    from lambdas import common
except ImportError:  # pragma: no cover - runtime import shape
    import common  # type: ignore

from gmail_cleanup import __main__ as cli
from gmail_cleanup import auth


def handler(event, context=None):
    bucket = common.env("ARTIFACT_BUCKET", required=True)
    prefix = common.env("ARTIFACT_PREFIX", default="")

    workdir = Path(tempfile.mkdtemp(prefix="cleanup-"))
    resolved_path = workdir / "feedback_resolved.json"

    found = common.download(bucket, "feedback_resolved.json", resolved_path, prefix=prefix)
    if not found:
        # No manifest → nothing was resolved this run. cmd_cleanup_markers also
        # treats a missing file as a clean no-op, but short-circuit to avoid
        # loading Gmail creds we don't need.
        return {"cleaned": False, "reason": "no feedback_resolved.json in S3"}

    # Gmail token → env only. cmd_cleanup_markers builds the service lazily via
    # auth.get_service(), which reads this env var. Never on disk.
    common.load_secret_into_env(auth.TOKEN_ENV, "gmail-token-json")

    rc = cli.cmd_cleanup_markers(argparse.Namespace(input=str(resolved_path)))
    if rc != 0:
        # Non-zero means some marker mutations errored (Gmail labels may be in a
        # partial state); surface it so Step Functions marks the run failed and
        # the failure alarm fires.
        raise RuntimeError(f"cleanup-markers exited {rc}")
    return {"cleaned": True}

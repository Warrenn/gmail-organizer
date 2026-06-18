"""deploy-apps-script Lambda — pushes the refreshed Apps Script to Google.

Replaces the old deploy.yml. After the refine task merges improved rules, the
regenerated ``Rules.gs`` / ``Classifier.gs`` must reach the LIVE Google Apps
Script labeler, otherwise the new rules never take effect Google-side.

The refine entrypoint uploads the post-merge ``apps-script/`` files to the S3
artifact bucket; this Lambda pulls them, then pushes them via the Apps Script
API using a least-privilege OAuth token (scope: script.projects) loaded from
SSM into the environment only. Fileless: no clasp, no credential on disk.

Thin wrapper around the existing ``deploy-apps-script`` command logic.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

try:
    from lambdas import common
except ImportError:  # pragma: no cover - runtime import shape
    import common  # type: ignore

from gmail_cleanup import __main__ as cli
from gmail_cleanup import auth

# Apps Script files the refine task regenerates + ships to S3. The manifest +
# Code.gs are static but included so updateContent (which replaces ALL content)
# never drops them.
APPS_SCRIPT_FILES = ("Rules.gs", "Classifier.gs", "Code.gs", "appsscript.json")


def handler(event, context=None):
    bucket = common.env("ARTIFACT_BUCKET", required=True)
    prefix = common.env("ARTIFACT_PREFIX", default="")
    script_id = common.env("APPS_SCRIPT_ID", required=True)

    # Pull the post-merge apps-script files the refine task uploaded. Fall back
    # to the copy baked into the Lambda package for files not present in S3
    # (e.g. an unchanged manifest) so updateContent always has a complete set.
    workdir = Path(tempfile.mkdtemp(prefix="deploy-")) / "apps-script"
    workdir.mkdir(parents=True)
    baked = Path(__file__).resolve().parent / "apps-script"

    pulled_any = False
    for name in APPS_SCRIPT_FILES:
        if common.download(bucket, f"apps-script/{name}", workdir / name, prefix=prefix):
            pulled_any = True
        elif (baked / name).exists():
            (workdir / name).write_text((baked / name).read_text())

    if not pulled_any and not any(workdir.iterdir()):
        raise RuntimeError(
            "no apps-script files found in S3 or baked into the package; "
            "nothing to deploy"
        )

    # Apps Script token → env only (scope: script.projects). Never on disk.
    common.load_secret_into_env(auth.APPS_SCRIPT_TOKEN_ENV, "apps-script-token-json")

    import argparse

    rc = cli.cmd_deploy_apps_script(
        argparse.Namespace(script_id=script_id, apps_dir=str(workdir))
    )
    if rc != 0:
        raise RuntimeError(f"deploy-apps-script exited {rc}")
    return {"deployed": True, "scriptId": script_id}

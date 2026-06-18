"""Tests for the feedback-loop Lambda handlers (scan / deploy / cleanup).

Each handler is a thin wrapper around an existing ``gmail_cleanup`` command.
The tests mock AWS (SSM + S3) with moto and stub the Gmail / Apps Script
service boundary, asserting the orchestration: creds come from SSM (into env,
never disk), artifacts move through S3, and the right command runs.
"""

from __future__ import annotations

import importlib
import json

import boto3
import pytest

moto = pytest.importorskip("moto")
from moto import mock_aws  # noqa: E402

REGION = "eu-west-1"
BUCKET = "test-artifact-bucket"


@pytest.fixture
def aws_env(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("ARTIFACT_BUCKET", BUCKET)
    monkeypatch.setenv("SSM_PREFIX", "/cleanup-gmail")


def _fresh_common():
    """Reimport common so its cached boto3 clients are rebuilt inside the moto
    context (moto patches at call time, but cached clients from a prior test
    would point at a torn-down mock)."""
    from lambdas import common
    importlib.reload(common)
    common._ssm_client = None
    common._s3_client = None
    return common


def _put_secret(name, value):
    boto3.client("ssm", region_name=REGION).put_parameter(
        Name=name, Value=value, Type="SecureString"
    )


def _make_bucket():
    boto3.client("s3", region_name=REGION).create_bucket(
        Bucket=BUCKET,
        CreateBucketConfiguration={"LocationConstraint": REGION},
    )


def _s3_get(key):
    obj = boto3.client("s3", region_name=REGION).get_object(Bucket=BUCKET, Key=key)
    return obj["Body"].read().decode()


def _s3_keys():
    resp = boto3.client("s3", region_name=REGION).list_objects_v2(Bucket=BUCKET)
    return {o["Key"] for o in resp.get("Contents", [])}


# ===========================================================================
# scan handler
# ===========================================================================
@mock_aws
def test_scan_no_markers_returns_false_and_uploads_nothing(aws_env, monkeypatch):
    _make_bucket()
    _put_secret("/cleanup-gmail/gmail-token-json", '{"token":"x"}')
    _fresh_common()

    from lambdas.scan import handler as scan
    importlib.reload(scan)

    monkeypatch.setattr(scan.auth, "get_service", lambda: object())
    monkeypatch.setattr(
        scan.feedback, "scan_for_markers",
        lambda service: {"markers": [], "existing_labels": []},
    )
    # token must have been loaded into env, never to disk
    monkeypatch.setattr(scan.auth, "TOKEN_ENV", "GMAIL_TOKEN_JSON")

    out = scan.handler({}, None)
    assert out == {"hasMarkers": False, "markerCount": 0}
    assert _s3_keys() == set(), "no markers ⇒ no artifacts uploaded"
    import os
    assert os.environ["GMAIL_TOKEN_JSON"] == '{"token":"x"}'


@mock_aws
def test_scan_with_markers_uploads_feedback_and_returns_true(aws_env, monkeypatch):
    _make_bucket()
    _put_secret("/cleanup-gmail/gmail-token-json", '{"token":"x"}')
    _fresh_common()

    from lambdas.scan import handler as scan
    importlib.reload(scan)

    monkeypatch.setattr(scan.auth, "get_service", lambda: object())
    feedback_doc = {
        "markers": [{"marker_label_name": "+receipts", "threads": [{"id": "t1"}]}],
        "existing_labels": ["receipts"],
    }
    monkeypatch.setattr(scan.feedback, "scan_for_markers", lambda service: feedback_doc)
    # Make corpus build a controlled, importless success.
    monkeypatch.setattr(scan.corpus, "build_corpus",
                        lambda service, per_label_sample_size=3: {"threads": []})
    monkeypatch.setattr(scan.corpus, "filter_to_agreement",
                        lambda raw, spec: ({"threads": []}, []))
    import gmail_cleanup.rule_interpreter as ri
    monkeypatch.setattr(ri, "load_rules", lambda path: {"sender_rules": []})

    out = scan.handler({}, None)
    assert out["hasMarkers"] is True
    assert out["markerCount"] == 1
    keys = _s3_keys()
    assert "feedback.json" in keys
    assert json.loads(_s3_get("feedback.json"))["markers"][0]["marker_label_name"] == "+receipts"
    # corpus.json should also be uploaded
    assert "corpus.json" in keys


@mock_aws
def test_scan_honours_artifact_prefix(aws_env, monkeypatch):
    _make_bucket()
    _put_secret("/cleanup-gmail/gmail-token-json", '{"token":"x"}')
    monkeypatch.setenv("ARTIFACT_PREFIX", "run-42")
    _fresh_common()

    from lambdas.scan import handler as scan
    importlib.reload(scan)
    monkeypatch.setattr(scan.auth, "get_service", lambda: object())
    monkeypatch.setattr(
        scan.feedback, "scan_for_markers",
        lambda service: {"markers": [{"marker_label_name": "+x", "threads": []}],
                         "existing_labels": []},
    )
    monkeypatch.setattr(scan.corpus, "build_corpus",
                        lambda service, per_label_sample_size=3: {"threads": []})
    monkeypatch.setattr(scan.corpus, "filter_to_agreement",
                        lambda raw, spec: ({"threads": []}, []))
    import gmail_cleanup.rule_interpreter as ri
    monkeypatch.setattr(ri, "load_rules", lambda path: {})

    scan.handler({}, None)
    assert "run-42/feedback.json" in _s3_keys()


# ===========================================================================
# cleanup handler
# ===========================================================================
@mock_aws
def test_cleanup_no_manifest_is_noop(aws_env, monkeypatch):
    _make_bucket()
    _fresh_common()

    from lambdas.cleanup import handler as cleanup
    importlib.reload(cleanup)

    # If it tried to load Gmail creds or call the CLI, this would blow up —
    # asserting the early no-op return when there's no manifest in S3.
    out = cleanup.handler({}, None)
    assert out["cleaned"] is False


@mock_aws
def test_cleanup_reads_manifest_from_s3_and_runs_command(aws_env, monkeypatch):
    _make_bucket()
    _put_secret("/cleanup-gmail/gmail-token-json", '{"token":"x"}')
    manifest = [{
        "marker_label_id": "L1", "marker_label_name": "+receipts",
        "sign": "+", "target_label_name": "receipts", "thread_ids": ["t1"],
    }]
    boto3.client("s3", region_name=REGION).put_object(
        Bucket=BUCKET, Key="feedback_resolved.json", Body=json.dumps(manifest).encode()
    )
    _fresh_common()

    from lambdas.cleanup import handler as cleanup
    importlib.reload(cleanup)

    seen = {}

    def fake_cmd(args):
        seen["input"] = args.input
        seen["manifest"] = json.loads(open(args.input).read())
        return 0

    monkeypatch.setattr(cleanup.cli, "cmd_cleanup_markers", fake_cmd)

    out = cleanup.handler({}, None)
    assert out["cleaned"] is True
    assert seen["manifest"] == manifest
    import os
    assert os.environ["GMAIL_TOKEN_JSON"] == '{"token":"x"}'


@mock_aws
def test_cleanup_raises_when_command_errors(aws_env, monkeypatch):
    _make_bucket()
    _put_secret("/cleanup-gmail/gmail-token-json", '{"token":"x"}')
    boto3.client("s3", region_name=REGION).put_object(
        Bucket=BUCKET, Key="feedback_resolved.json", Body=b"[]"
    )
    _fresh_common()
    from lambdas.cleanup import handler as cleanup
    importlib.reload(cleanup)
    monkeypatch.setattr(cleanup.cli, "cmd_cleanup_markers", lambda args: 2)
    with pytest.raises(RuntimeError):
        cleanup.handler({}, None)


# ===========================================================================
# deploy handler
# ===========================================================================
@mock_aws
def test_deploy_pulls_apps_script_from_s3_and_deploys(aws_env, monkeypatch):
    _make_bucket()
    _put_secret("/cleanup-gmail/apps-script-token-json", '{"token":"y"}')
    monkeypatch.setenv("APPS_SCRIPT_ID", "SID123")
    s3 = boto3.client("s3", region_name=REGION)
    for name, body in [
        ("Rules.gs", "// rules"),
        ("Classifier.gs", "// classifier"),
        ("Code.gs", "function f(){}"),
        ("appsscript.json", '{"timeZone":"UTC"}'),
    ]:
        s3.put_object(Bucket=BUCKET, Key=f"apps-script/{name}", Body=body.encode())
    _fresh_common()

    from lambdas.deploy import handler as deploy
    importlib.reload(deploy)

    captured = {}

    def fake_cmd(args):
        captured["apps_dir"] = args.apps_dir
        captured["script_id"] = args.script_id
        files = sorted(p.name for p in __import__("pathlib").Path(args.apps_dir).iterdir())
        captured["files"] = files
        return 0

    monkeypatch.setattr(deploy.cli, "cmd_deploy_apps_script", fake_cmd)

    out = deploy.handler({}, None)
    assert out["deployed"] is True
    assert captured["script_id"] == "SID123"
    assert set(captured["files"]) == {"Rules.gs", "Classifier.gs", "Code.gs", "appsscript.json"}
    import os
    assert os.environ["APPS_SCRIPT_TOKEN_JSON"] == '{"token":"y"}'


@mock_aws
def test_deploy_requires_script_id(aws_env, monkeypatch):
    _make_bucket()
    _put_secret("/cleanup-gmail/apps-script-token-json", '{"token":"y"}')
    monkeypatch.delenv("APPS_SCRIPT_ID", raising=False)
    _fresh_common()
    from lambdas.deploy import handler as deploy
    importlib.reload(deploy)
    with pytest.raises(RuntimeError):
        deploy.handler({}, None)

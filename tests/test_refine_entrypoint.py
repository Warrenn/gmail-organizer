"""Behavioural tests for container/refine-entrypoint.sh.

The entrypoint is what the Fargate "refine" task runs. It is the AWS-side
analogue of the `refine` GitHub Actions job: it provisions a clean checkout,
pulls the scan artifacts from S3, runs the SAME scripts/feedback-loop.sh
``refine``+``verify`` phases (DRY_RUN=false, LOOP_AUTO_MERGE=true) under the
Max-subscription token, then ships feedback_resolved.json to S3.

These tests drive it with *stub* executables (aws / git / gh / claude /
feedback-loop.sh) on PATH so its orchestration can be verified with no real
credentials, no network, and no Docker — mirroring tests/test_feedback_loop_script.py.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY = REPO_ROOT / "container" / "refine-entrypoint.sh"


def _write_exec(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(0o755)


@pytest.fixture
def stub_bin(tmp_path: Path):
    """Stub executables, prepended to PATH, that log their argv.

    aws            → logs argv; serves SSM token pulls and S3 cp; for the
                     github-token GetParameter it prints a dummy token.
    git            → logs argv (so we can assert a clone happened); no-op.
    gh             → logs argv; no-op.
    claude         → logged via feedback-loop.sh stub (not invoked here).
    feedback-loop.sh → logs the subcommand + key env it saw, and writes a
                     feedback_resolved.json into the workdir (so the upload
                     step has something to ship).
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    aws_log = tmp_path / "aws.log"
    git_log = tmp_path / "git.log"
    loop_log = tmp_path / "loop.log"

    _write_exec(
        bindir / "aws",
        f'printf "%s\\n" "$*" >> "{aws_log}"\n'
        'cmd="$1 $2"\n'
        'case "$cmd" in\n'
        '  "ssm get-parameter") echo "dummy-secret" ;;\n'
        '  "s3 cp")\n'
        # When copying FROM s3 to a local dest, create the dest so downstream
        # steps see the artifact; when copying TO s3, just succeed.
        '    dst="${@: -1}"\n'
        '    case "$3" in\n'
        '      s3://*) : ;;                       # upload\n'
        '      *) [ "$dst" != "s3://*" ] && : ;;  # download\n'
        '    esac\n'
        '    ;;\n'
        '  *) : ;;\n'
        'esac\n'
        'exit 0\n',
    )

    # git may be invoked as `git -c http.extraheader=... clone <url> <dst>`;
    # scan argv for the `clone` verb and create the destination directory
    # (the last argument) so the entrypoint's subsequent `cd repo` succeeds.
    _write_exec(bindir / "git", f'printf "%s\\n" "$*" >> "{git_log}"\n'
                                'for a in "$@"; do\n'
                                '  if [ "$a" = "clone" ]; then mkdir -p "${@: -1}"; break; fi\n'
                                'done\n'
                                'exit 0\n')
    _write_exec(bindir / "gh", 'exit 0\n')

    # Stub feedback-loop.sh: log subcommand + the auth/merge env it ran under,
    # and emit a resolved manifest so the upload step has a payload.
    _write_exec(
        bindir / "feedback-loop.sh",
        f'printf "sub=%s DRY_RUN=%s AUTO_MERGE=%s APIKEY=%s OAUTH_PULLED=%s GH_TOKEN=%s PR_NUMBER=%s\\n" '
        f'"$1" "${{DRY_RUN:-<unset>}}" "${{LOOP_AUTO_MERGE:-<unset>}}" '
        f'"${{ANTHROPIC_API_KEY:-<unset>}}" "${{CLAUDE_OAUTH_VIA_SCRIPT:-script}}" '
        f'"${{GH_TOKEN:-<unset>}}" "${{PR_NUMBER:-<unset>}}" >> "{loop_log}"\n'
        # The real cmd_refine reports pr_number/branch via $GITHUB_OUTPUT; mimic
        # that so the entrypoint's refine->verify state bridge can be exercised.
        'if [ "$1" = "refine" ] && [ -n "${GITHUB_OUTPUT:-}" ]; then\n'
        '  printf "pr_number=30\\nbranch=loop/test\\n" >> "$GITHUB_OUTPUT"\n'
        'fi\n'
        'printf "[]\\n" > feedback_resolved.json\n'
        'exit 0\n',
    )

    return {
        "bindir": bindir,
        "aws_log": aws_log,
        "git_log": git_log,
        "loop_log": loop_log,
    }


def _run(*, stub, cwd, env=None):
    full_env = dict(os.environ)
    full_env["PATH"] = f"{stub['bindir']}{os.pathsep}{full_env['PATH']}"
    full_env.pop("ANTHROPIC_API_KEY", None)
    # Required config the entrypoint reads from env.
    full_env.setdefault("ARTIFACT_BUCKET", "test-bucket")
    full_env.setdefault("REPO_SLUG", "Warrenn/gmail-organizer")
    full_env.setdefault("SSM_PREFIX", "/cleanup-gmail")
    # Point the entrypoint at our stub feedback-loop.sh, not the real one.
    full_env.setdefault("FEEDBACK_LOOP_SH", "feedback-loop.sh")
    if env:
        full_env.update({k: v for k, v in env.items() if v is not None})
        for k, v in (env or {}).items():
            if v is None:
                full_env.pop(k, None)
    return subprocess.run(
        ["bash", str(ENTRY)],
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
    )


def test_entrypoint_exists_and_is_shell():
    assert ENTRY.exists(), "container/refine-entrypoint.sh must exist"
    assert ENTRY.read_text().startswith("#!"), "must have a shebang"


def test_refuses_when_api_key_is_present(tmp_path, stub_bin):
    r = _run(stub=stub_bin, cwd=tmp_path,
             env={"ANTHROPIC_API_KEY": "sk-should-not-be-used"})
    assert r.returncode != 0, "must refuse to run when an API key is set"
    assert "ANTHROPIC_API_KEY" in (r.stdout + r.stderr)
    assert not stub_bin["loop_log"].exists(), "refine must not run under an API key"


def test_clones_repo_via_github_token_from_ssm(tmp_path, stub_bin):
    r = _run(stub=stub_bin, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    aws_calls = stub_bin["aws_log"].read_text()
    # GitHub token must be pulled from SSM.
    assert "ssm get-parameter" in aws_calls
    assert "/cleanup-gmail/github-token" in aws_calls
    # A clone must have happened.
    git_calls = stub_bin["git_log"].read_text()
    assert "clone" in git_calls


def test_pulls_feedback_and_corpus_from_s3(tmp_path, stub_bin):
    r = _run(stub=stub_bin, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    aws_calls = stub_bin["aws_log"].read_text()
    assert "feedback.json" in aws_calls, "must pull feedback.json from S3"
    assert "corpus.json" in aws_calls, "must pull the regression corpus from S3"
    # The pull direction is FROM s3 (download): an s3:// source appears.
    assert "s3://" in aws_calls


def test_runs_refine_then_verify_autonomous_and_not_dry(tmp_path, stub_bin):
    r = _run(stub=stub_bin, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    loop = stub_bin["loop_log"].read_text().splitlines()
    subs = [l.split()[0] for l in loop]  # "sub=refine" etc.
    assert subs[0] == "sub=refine"
    assert subs[1] == "sub=verify"
    # Fully autonomous: real side effects + auto-merge.
    for line in loop:
        assert "DRY_RUN=false" in line, line
        assert "AUTO_MERGE=true" in line, line


def test_pr_number_bridged_from_refine_to_verify(tmp_path, stub_bin):
    """refine reports pr_number via $GITHUB_OUTPUT; the entrypoint must lift it
    into PR_NUMBER for the SEPARATE verify process — otherwise verify dies with
    'LOOP_AUTO_MERGE=true but PR_NUMBER is empty' (the live-run failure)."""
    r = _run(stub=stub_bin, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    loop = stub_bin["loop_log"].read_text().splitlines()
    refine_line = next(l for l in loop if l.startswith("sub=refine"))
    verify_line = next(l for l in loop if l.startswith("sub=verify"))
    # refine runs before the PR exists; verify must receive it.
    assert "PR_NUMBER=<unset>" in refine_line, refine_line
    assert "PR_NUMBER=30" in verify_line, f"verify must get PR_NUMBER from refine; saw: {verify_line}"


def test_uploads_resolved_manifest_to_s3(tmp_path, stub_bin):
    r = _run(stub=stub_bin, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    aws_calls = stub_bin["aws_log"].read_text()
    # An upload TO s3 of feedback_resolved.json must occur.
    upload_lines = [l for l in aws_calls.splitlines()
                    if "s3 cp" in l and "feedback_resolved.json" in l and "s3://" in l]
    assert upload_lines, f"must upload feedback_resolved.json to S3; saw:\n{aws_calls}"


def test_requires_artifact_bucket(tmp_path, stub_bin):
    r = _run(stub=stub_bin, cwd=tmp_path, env={"ARTIFACT_BUCKET": None})
    assert r.returncode != 0, "must fail fast when ARTIFACT_BUCKET is unset"
    assert "ARTIFACT_BUCKET" in (r.stdout + r.stderr)

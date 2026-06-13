"""Behavioural tests for scripts/feedback-loop.sh.

The script is the single source of truth shared by local runs and the
GitHub Actions workflow. These tests exercise it with *stub* executables
(aws / gh / claude / python) on PATH and a throwaway git repo, so the
loop's behaviour can be verified with no real credentials and no network.

What each phase must do is asserted here; the workflow YAML only wires
GitHub context to the same script, so testing the script tests both.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "feedback-loop.sh"


# --------------------------------------------------------------------------
# Stub harness
# --------------------------------------------------------------------------
def _write_exec(path: Path, body: str) -> None:
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(0o755)


@pytest.fixture
def stub_bin(tmp_path: Path):
    """A directory of stub executables, prepended to PATH.

    aws    → echoes a dummy value (so SSM pulls write a non-empty file / key)
    gh     → appends its argv to $GH_LOG and prints plausible output
    claude → touches $CLAUDE_MARKER (proof the refine step invoked it)
    python → writes a fixture feedback.json for `-m ... feedback-scan`,
             otherwise delegates `-c` to the real python3
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh_log = tmp_path / "gh.log"
    claude_marker = tmp_path / "claude.invoked"

    _write_exec(bindir / "aws", 'echo "dummy-value"\n')

    _write_exec(
        bindir / "gh",
        'printf "%s\\n" "$*" >> "$GH_LOG"\n'
        'case "$1 $2" in\n'
        '  "pr list") echo "" ;;\n'                       # no existing PR
        '  "pr create") echo "https://github.com/o/r/pull/123" ;;\n'
        '  *) : ;;\n'
        'esac\n',
    )

    _write_exec(bindir / "claude", 'touch "$CLAUDE_MARKER"\n')

    # marker count fixture defaults to 0; tests override FIXTURE_MARKERS
    _write_exec(
        bindir / "python",
        'if [ "$1" = "-m" ]; then\n'
        '  [ -n "$GMAIL_TOKEN_JSON" ] || { echo "GMAIL_TOKEN_JSON not in env" >&2; exit 3; }\n'
        '  out="feedback.json"\n'
        '  for a in "$@"; do [ "$prev" = "--output" ] && out="$a"; prev="$a"; done\n'
        '  n="${FIXTURE_MARKERS:-0}"\n'
        '  markers=""\n'
        '  i=0; while [ "$i" -lt "$n" ]; do markers="$markers{\\"id\\":\\"m$i\\"},"; i=$((i+1)); done\n'
        '  markers="${markers%,}"\n'
        '  printf \'{"markers":[%s],"existing_labels":[]}\' "$markers" > "$out"\n'
        'elif [ "$1" = "-c" ]; then\n'
        '  exec python3 "$@"\n'
        'fi\n',
    )

    return {"bindir": bindir, "gh_log": gh_log, "claude_marker": claude_marker}


def _run(subcmd, *, cwd, stub, env=None):
    full_env = dict(os.environ)
    full_env["PATH"] = f"{stub['bindir']}{os.pathsep}{full_env['PATH']}"
    full_env["GH_LOG"] = str(stub["gh_log"])
    full_env["CLAUDE_MARKER"] = str(stub["claude_marker"])
    # Isolate Actions-only env: only tests that pass it explicitly get it.
    full_env.pop("GITHUB_OUTPUT", None)
    full_env.setdefault("DRY_RUN", "true")
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", str(SCRIPT), subcmd],
        cwd=str(cwd),
        env=full_env,
        capture_output=True,
        text=True,
    )


# --------------------------------------------------------------------------
# A throwaway git repo for the verify phase
# --------------------------------------------------------------------------
def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.local")
    _git(repo, "config", "user.name", "t")
    (repo / "gmail_cleanup").mkdir()
    (repo / "gmail_cleanup" / "rules.yaml").write_text("version: 1\n")
    (repo / "README.md").write_text("hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    return repo


def _branch_changing(repo: Path, relpath: str) -> None:
    _git(repo, "checkout", "-q", "-b", "loop/test")
    target = repo / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text((target.read_text() if target.exists() else "") + "\n# edit\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "edit")


# --------------------------------------------------------------------------
# verify — allow-list
# --------------------------------------------------------------------------
def test_verify_passes_for_allowlisted_diff(git_repo, stub_bin):
    _branch_changing(git_repo, "gmail_cleanup/rules.yaml")
    r = _run("verify", cwd=git_repo, stub=stub_bin,
             env={"BASE_REF": "main", "PR_NUMBER": "1"})
    assert r.returncode == 0, r.stderr
    # no escape: no issue filed
    assert "issue create" not in stub_bin["gh_log"].read_text() if stub_bin["gh_log"].exists() else True


def test_verify_fails_and_escapes_for_offlist_diff(git_repo, stub_bin):
    _branch_changing(git_repo, "README.md")
    r = _run("verify", cwd=git_repo, stub=stub_bin,
             env={"BASE_REF": "main", "PR_NUMBER": "1"})
    assert r.returncode == 1, (r.stdout, r.stderr)
    # the escape path (close PR + file loop-broken issue) must be triggered
    combined = r.stdout + r.stderr
    assert "README.md" in combined
    assert ("issue create" in combined) or ("loop-escape" in combined) or ("loop-broken" in combined)


# --------------------------------------------------------------------------
# DRY_RUN guards side effects (auto-merge is the easy probe)
# --------------------------------------------------------------------------
def test_dry_run_skips_auto_merge(git_repo, stub_bin):
    _branch_changing(git_repo, "gmail_cleanup/rules.yaml")
    r = _run("verify", cwd=git_repo, stub=stub_bin,
             env={"BASE_REF": "main", "PR_NUMBER": "1",
                  "LOOP_AUTO_MERGE": "true", "DRY_RUN": "true"})
    assert r.returncode == 0, r.stderr
    gh_calls = stub_bin["gh_log"].read_text() if stub_bin["gh_log"].exists() else ""
    assert "pr merge" not in gh_calls, "merge must NOT execute under DRY_RUN"
    assert "[dry-run]" in (r.stdout + r.stderr)


def test_auto_merge_runs_when_not_dry(git_repo, stub_bin):
    _branch_changing(git_repo, "gmail_cleanup/rules.yaml")
    r = _run("verify", cwd=git_repo, stub=stub_bin,
             env={"BASE_REF": "main", "PR_NUMBER": "1",
                  "LOOP_AUTO_MERGE": "true", "DRY_RUN": "false"})
    assert r.returncode == 0, r.stderr
    assert "pr merge" in stub_bin["gh_log"].read_text()


# --------------------------------------------------------------------------
# scan — counting, set_output, cred scrub
# --------------------------------------------------------------------------
def test_scan_sets_has_markers_output_and_writes_no_cred_files(tmp_path, stub_bin):
    work = tmp_path / "work"
    work.mkdir()
    gh_out = tmp_path / "gh_output"
    gh_out.write_text("")
    r = _run("scan", cwd=work, stub=stub_bin,
             env={"FIXTURE_MARKERS": "2", "GITHUB_OUTPUT": str(gh_out)})
    assert r.returncode == 0, r.stderr
    assert "has_markers=true" in gh_out.read_text()
    # Fileless contract: credentials must NEVER be written to disk.
    assert not (work / "credentials.json").exists()
    assert not (work / "token.json").exists()
    # the only file scan may create is the feedback output
    assert {p.name for p in work.iterdir()} <= {"feedback.json"}


def test_scan_reports_no_markers(tmp_path, stub_bin):
    work = tmp_path / "work"
    work.mkdir()
    gh_out = tmp_path / "gh_output"
    gh_out.write_text("")
    r = _run("scan", cwd=work, stub=stub_bin,
             env={"FIXTURE_MARKERS": "0", "GITHUB_OUTPUT": str(gh_out)})
    assert r.returncode == 0, r.stderr
    assert "has_markers=false" in gh_out.read_text()


def test_scan_without_github_output_is_a_clean_noop(tmp_path, stub_bin):
    # Local runs have no $GITHUB_OUTPUT — set_output must no-op, not crash.
    work = tmp_path / "work"
    work.mkdir()
    r = _run("scan", cwd=work, stub=stub_bin, env={"FIXTURE_MARKERS": "1"})
    assert r.returncode == 0, r.stderr
    assert "markers=1" in (r.stdout + r.stderr)


# --------------------------------------------------------------------------
# refine — runs claude when invoked (needs a git repo)
# --------------------------------------------------------------------------
def test_refine_runs_claude_and_guards_push(git_repo, stub_bin):
    prompt = git_repo / "prompt.md"
    prompt.write_text("do the refinement\n")
    r = _run("refine", cwd=git_repo, stub=stub_bin, env={"PROMPT_FILE": str(prompt)})
    assert r.returncode == 0, r.stderr
    assert stub_bin["claude_marker"].exists(), "refine must invoke the claude CLI"
    gh_calls = stub_bin["gh_log"].read_text() if stub_bin["gh_log"].exists() else ""
    # under DRY_RUN the push and pr create are logged, never executed
    assert "[dry-run]" in (r.stdout + r.stderr)
    assert "pr create" not in gh_calls


# --------------------------------------------------------------------------
# heartbeat — files a loop-broken issue
# --------------------------------------------------------------------------
def test_heartbeat_files_issue_when_not_dry(tmp_path, stub_bin):
    work = tmp_path / "work"
    work.mkdir()
    r = _run("heartbeat", cwd=work, stub=stub_bin,
             env={"DRY_RUN": "false", "SCAN_RESULT": "failure"})
    assert r.returncode == 0, r.stderr
    assert "issue create" in stub_bin["gh_log"].read_text()


# --------------------------------------------------------------------------
# all — skips refine when nothing to do
# --------------------------------------------------------------------------
def test_all_skips_refine_when_no_markers(tmp_path, stub_bin):
    work = tmp_path / "work"
    work.mkdir()
    r = _run("all", cwd=work, stub=stub_bin, env={"FIXTURE_MARKERS": "0"})
    assert r.returncode == 0, r.stderr
    assert not stub_bin["claude_marker"].exists(), "refine/claude must not run with 0 markers"


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------
def test_unknown_subcommand_exits_nonzero(tmp_path, stub_bin):
    work = tmp_path / "work"
    work.mkdir()
    r = _run("bogus", cwd=work, stub=stub_bin)
    assert r.returncode != 0

#!/usr/bin/env bash
#
# feedback-loop.sh — single source of truth for the autonomous label-rule
# refinement loop. The GitHub Actions workflow (.github/workflows/feedback-loop.yml)
# and local runs invoke THIS script; neither holds a copy of the logic.
#
# GitHub Actions is responsible only for what a shell script genuinely cannot do:
#   - OIDC federation to AWS (id-token: write + configure-aws-credentials)
#   - checkout, and runtime provisioning (Python, the `claude` CLI)
# Everything below — SSM credential pull (into env, never files), scan, Claude
# refinement, git, gh — happens here, identically in CI and locally.
#
# Locally: authenticate to AWS first (`aws sso login` / a profile), then run
#   ./scripts/feedback-loop.sh all
# Side effects (push / gh pr create / merge / issue create) are DRY_RUN-guarded
# and default to ON locally, so local runs are safe to repeat. CI sets DRY_RUN=false.
#
# Usage:
#   feedback-loop.sh scan       load Gmail token (env, from SSM), scan for +X/-X markers
#   feedback-loop.sh refine     pull subscription OAuth token, branch, run Claude, push, PR
#   feedback-loop.sh verify     diff allow-list check, optional auto-merge
#   feedback-loop.sh heartbeat  file a loop-broken issue for a failed run
#   feedback-loop.sh all        scan; if markers, refine then verify (local default)
#
# See scripts/README.md for the full environment-variable contract.

set -euo pipefail

# --- Configuration via environment (with safe defaults) --------------------
: "${DRY_RUN:=true}"                                   # CI sets "false"
: "${PYTHON:=python}"                                  # local mac: set PYTHON=python3 / venv
: "${SSM_PREFIX:=/cleanup-gmail}"
: "${FEEDBACK_FILE:=feedback.json}"
: "${RESOLVED_FILE:=feedback_resolved.json}"
: "${PROMPT_FILE:=.github/prompts/feedback-loop.md}"
: "${BASE_REF:=origin/main}"
: "${LOOP_AUTO_MERGE:=false}"
: "${CORPUS_PER_LABEL:=3}"                              # threads/label for the regression corpus
: "${BRANCH_NAME:=}"                                   # refine computes one if empty
: "${PR_NUMBER:=}"
: "${GH_TOKEN:=}"
: "${RUN_URL:=local-run}"
: "${SCAN_RESULT:=}" ; : "${REFINE_RESULT:=}" ; : "${VERIFY_RESULT:=}"

# Files Claude is permitted to modify. The verify phase rejects anything else.
# feedback_resolved.json is intentionally absent: it is no longer committed
# (it ships to the S3 artifact bucket — see container/refine-entrypoint.sh and
# STRATEGY.md Q2), so it must never appear in a refine commit/diff.
ALLOWED_RE='^(gmail_cleanup/rules\.yaml|tests/(corpus|corpus_disagreements)\.json|apps-script/(Rules|Classifier)\.gs)$'

# --- Helpers ---------------------------------------------------------------
log()  { printf '%s\n' "$*" >&2; }
die()  { log "ERROR: $*"; exit 1; }

# Write a GitHub Actions step output iff running under Actions; else no-op.
set_output() {
  [ -n "${GITHUB_OUTPUT:-}" ] && printf '%s=%s\n' "$1" "$2" >> "$GITHUB_OUTPUT"
  return 0
}

# Mask a secret in Actions logs iff running under Actions; else no-op.
mask() {
  [ -n "${GITHUB_ACTIONS:-}" ] && printf '::add-mask::%s\n' "$1"
  return 0
}

# Run a side-effecting command, or just log it when DRY_RUN=true.
guarded() {
  if [ "$DRY_RUN" = "true" ]; then
    log "[dry-run] $*"
  else
    "$@"
  fi
}

# Push a branch to origin. With GH_TOKEN (CI) authenticate via a Basic
# x-access-token header — the scheme GitHub's git-over-HTTPS requires (a Bearer
# header is rejected as invalid credentials). Without GH_TOKEN, rely on local
# git auth (SSH / credential helper).
push_branch() {
  local branch="$1"
  if [ -n "$GH_TOKEN" ]; then
    local basic
    basic=$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 | tr -d '\n')
    git -c http.extraheader="AUTHORIZATION: basic ${basic}" push -u origin "$branch"
  else
    git push -u origin "$branch"
  fi
}

ssm() {
  aws ssm get-parameter --name "$1" --with-decryption \
    --query Parameter.Value --output text
}

# Load the Gmail token from SSM into an environment variable — NEVER a file.
# The token self-contains client_id/secret/refresh_token, so it is all the
# runtime needs (gmail_cleanup.auth reads $GMAIL_TOKEN_JSON in memory). The
# env var dies with the process; there is nothing on disk to scrub.
load_gmail_token() {
  GMAIL_TOKEN_JSON=$(ssm "$SSM_PREFIX/gmail-token-json")
  export GMAIL_TOKEN_JSON
  [ -n "$GMAIL_TOKEN_JSON" ] || die "empty gmail-token-json from SSM"
}

# --- Phases ----------------------------------------------------------------
cmd_scan() {
  # Gmail token lives only in this process's environment (from SSM), never on
  # disk. The refine step deliberately runs without it; unset before returning
  # so it cannot leak into a later in-process phase during `all`.
  load_gmail_token
  trap 'unset GMAIL_TOKEN_JSON' RETURN

  "$PYTHON" -m gmail_cleanup feedback-scan --output "$FEEDBACK_FILE" --exit-zero-on-empty
  local count
  count=$("$PYTHON" -c "import json,sys; print(len(json.load(open('$FEEDBACK_FILE'))['markers']))")
  log "markers=$count"
  if [ "$count" -gt 0 ]; then
    HAS_MARKERS=true
    set_output has_markers true
    # Build the regression corpus (sampled from the live mailbox) so refine can
    # verify -X survivors and corpus-regression (constraints #3/#4). Only on
    # marker runs, to bound Gmail sampling cost. Non-fatal: if it fails, refine
    # still runs (and will bail on a -X it can't verify, as before).
    log "Building regression corpus (per-label=$CORPUS_PER_LABEL)..."
    "$PYTHON" -m gmail_cleanup corpus-build --per-label "$CORPUS_PER_LABEL" \
      || log "corpus-build failed — refine will run without a corpus"
  else
    HAS_MARKERS=false
    set_output has_markers false
  fi
}

cmd_refine() {
  # Claude authenticates against the user's Max SUBSCRIPTION via a long-lived
  # OAuth token (CLAUDE_CODE_OAUTH_TOKEN), pulled from SSM — NOT a per-token API
  # key. ANTHROPIC_API_KEY takes precedence inside Claude Code and would silently
  # bill the API, so refuse to run if it is set rather than bill the wrong way.
  [ -z "${ANTHROPIC_API_KEY:-}" ] || \
    die "ANTHROPIC_API_KEY is set — refusing to run so usage bills the subscription, not the API. Unset it."
  # No Gmail creds in this phase. Drop the token when this function returns so it
  # cannot linger into a later in-process phase during `all`.
  trap 'unset CLAUDE_CODE_OAUTH_TOKEN' RETURN
  local token
  token=$(ssm "$SSM_PREFIX/claude-code-oauth-token")
  mask "$token"
  [ -n "$token" ] || die "empty claude-code-oauth-token from SSM"
  export CLAUDE_CODE_OAUTH_TOKEN="$token"

  local branch="${BRANCH_NAME}"
  if [ -z "$branch" ]; then
    branch="loop/feedback-$(date -u +%Y%m%d-%H%M%S)"
  fi
  git config user.name "feedback-loop-bot"
  git config user.email "feedback-loop@noreply.local"
  git checkout -b "$branch" 2>/dev/null || git checkout "$branch"
  BRANCH_NAME="$branch"
  set_output branch "$branch"
  local base_sha
  base_sha=$(git rev-parse HEAD)

  # Start from an empty resolved-markers manifest so entries already consumed by
  # a prior merged run cannot re-fire in cleanup-markers (which reads this file
  # on every merged loop PR). Claude appends only THIS run's resolutions.
  printf '[]\n' > "$RESOLVED_FILE"

  [ -s "$PROMPT_FILE" ] || die "prompt file not found: $PROMPT_FILE"
  log "Running Claude against $PROMPT_FILE on branch $branch"
  # Claude edits and commits only — withhold push/PR credentials from its
  # environment (containment: it must not be able to reach GitHub). The harness
  # does the deterministic push + PR below.
  env -u GH_TOKEN -u GITHUB_TOKEN claude -p "$(cat "$PROMPT_FILE")" \
    --permission-mode acceptEdits \
    --allowed-tools "Bash Edit Read Write Glob Grep"

  # Backstop: make sure Claude's edits are committed so there is something to push.
  if [ -n "$(git status --porcelain)" ]; then
    git add -A
    git commit -m "feedback-loop: rule refinements" >/dev/null
  fi

  # PR body = Claude's commit reasoning for this run (Claude can't open the PR
  # itself — it has no GitHub creds — so the harness surfaces its rationale).
  local pr_body
  pr_body=$(git log "${base_sha}..HEAD" --format='%B' 2>/dev/null)
  [ -n "$pr_body" ] || pr_body="Autonomous refinement from feedback-loop.sh."

  # A marker is "bailed" when the scan found it but Claude did not resolve it
  # (it's absent from feedback_resolved.json). Any bail → needs-human.
  local bailed="false" n_found="0" n_resolved="0"
  if [ -f "$FEEDBACK_FILE" ]; then
    n_found=$("$PYTHON" -c "import json;print(len(json.load(open('$FEEDBACK_FILE')).get('markers',[])))" 2>/dev/null || echo 0)
  fi
  if [ -f "$RESOLVED_FILE" ]; then
    n_resolved=$("$PYTHON" -c "import json;print(len(json.load(open('$RESOLVED_FILE'))))" 2>/dev/null || echo 0)
  fi
  [ "${n_resolved:-0}" -lt "${n_found:-0}" ] && bailed="true"

  guarded push_branch "$branch"

  # Open or update the PR.
  local existing
  existing=$(gh pr list --head "$branch" --json number -q '.[0].number' 2>/dev/null || echo "")
  if [ -z "$existing" ]; then
    if [ "$DRY_RUN" = "true" ]; then
      log "[dry-run] gh pr create --head $branch --label loop-autonomous (bailed=$bailed)"
      PR_NUMBER="dry-run"
    else
      local url
      url=$(gh pr create \
        --title "feedback-loop: $(date -u +%Y-%m-%d) refinement" \
        --body "$pr_body" \
        --label loop-autonomous)
      PR_NUMBER="${url##*/}"
    fi
  else
    PR_NUMBER="$existing"
  fi

  # Flag bailed runs for a human (resolved < found). Create the label if absent.
  if [ "$bailed" = "true" ] && [ "$DRY_RUN" != "true" ] && [ -n "$PR_NUMBER" ]; then
    gh label create needs-human --color FBCA04 --description "Loop bailed on a marker; needs a human decision" 2>/dev/null || true
    gh pr edit "$PR_NUMBER" --add-label needs-human
    log "marked PR #$PR_NUMBER needs-human ($n_resolved/$n_found markers resolved)"
  fi

  set_output pr_number "$PR_NUMBER"
  log "pr_number=$PR_NUMBER bailed=$bailed"
}

cmd_verify() {
  local touched violations=""
  touched=$(git diff --name-only "$BASE_REF"...HEAD)
  log "Touched files:"
  log "$touched"
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    if ! printf '%s' "$f" | grep -qE "$ALLOWED_RE"; then
      violations="$violations $f"
    fi
  done <<< "$touched"

  if [ -n "$violations" ]; then
    log "Loop escape — files outside the allow-list:$violations"
    if [ -n "$PR_NUMBER" ]; then
      guarded gh pr edit "$PR_NUMBER" --add-label loop-escape
      guarded gh pr comment "$PR_NUMBER" --body "Loop escape detected — Claude wrote to files outside the allow-list:$violations. This PR is being closed automatically."
      guarded gh pr close "$PR_NUMBER"
    fi
    guarded gh issue create \
      --title "loop-escape: feedback-loop wrote to disallowed files" \
      --label loop-broken \
      --body "PR #${PR_NUMBER:-?} touched off-list files:$violations"
    return 1
  fi

  if [ "$LOOP_AUTO_MERGE" = "true" ]; then
    [ -n "$PR_NUMBER" ] || die "LOOP_AUTO_MERGE=true but PR_NUMBER is empty"
    guarded gh pr merge "$PR_NUMBER" --auto --squash
  fi
}

cmd_heartbeat() {
  guarded gh issue create \
    --title "feedback-loop run failed" \
    --label loop-broken \
    --body "scan=${SCAN_RESULT} refine=${REFINE_RESULT} verify=${VERIFY_RESULT}

Run: ${RUN_URL}"
}

cmd_all() {
  cmd_scan
  if [ "${HAS_MARKERS:-false}" = "true" ]; then
    cmd_refine
    cmd_verify
  else
    log "No markers — nothing to refine."
  fi
}

# --- Dispatch --------------------------------------------------------------
main() {
  local sub="${1:-all}"
  case "$sub" in
    scan)      cmd_scan ;;
    refine)    cmd_refine ;;
    verify)    cmd_verify ;;
    heartbeat) cmd_heartbeat ;;
    all)       cmd_all ;;
    -h|--help|help)
      sed -n '2,33p' "$0" | sed 's/^# \{0,1\}//'
      ;;
    *)
      log "unknown subcommand: $sub"
      log "usage: feedback-loop.sh {scan|refine|verify|heartbeat|all}"
      exit 2
      ;;
  esac
}

main "$@"

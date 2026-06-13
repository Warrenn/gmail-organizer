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
#   feedback-loop.sh refine     pull Anthropic key, branch, run Claude, push, PR
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
: "${BRANCH_NAME:=}"                                   # refine computes one if empty
: "${PR_NUMBER:=}"
: "${GH_TOKEN:=}"
: "${RUN_URL:=local-run}"
: "${SCAN_RESULT:=}" ; : "${REFINE_RESULT:=}" ; : "${VERIFY_RESULT:=}"

# Files Claude is permitted to modify. The verify phase rejects anything else.
ALLOWED_RE='^(gmail_cleanup/rules\.yaml|tests/(corpus|corpus_disagreements)\.json|apps-script/(Rules|Classifier)\.gs|feedback_resolved\.json)$'

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
  else
    HAS_MARKERS=false
    set_output has_markers false
  fi
}

cmd_refine() {
  # Anthropic key ONLY — no Gmail creds in this phase's environment. Drop the
  # key when this function returns so it cannot linger into a later in-process
  # phase during `all`.
  trap 'unset ANTHROPIC_API_KEY' RETURN
  local key
  key=$(ssm "$SSM_PREFIX/anthropic-api-key")
  mask "$key"
  export ANTHROPIC_API_KEY="$key"

  local branch="${BRANCH_NAME}"
  if [ -z "$branch" ]; then
    branch="loop/feedback-$(date -u +%Y%m%d-%H%M%S)"
  fi
  git config user.name "feedback-loop-bot"
  git config user.email "feedback-loop@noreply.local"
  git checkout -b "$branch" 2>/dev/null || git checkout "$branch"
  BRANCH_NAME="$branch"
  set_output branch "$branch"

  [ -s "$PROMPT_FILE" ] || die "prompt file not found: $PROMPT_FILE"
  log "Running Claude against $PROMPT_FILE on branch $branch"
  claude -p "$(cat "$PROMPT_FILE")" \
    --permission-mode acceptEdits \
    --allowed-tools "Bash Edit Read Write Glob Grep"

  # Push — authenticate via GH_TOKEN only if provided (CI); else local git auth.
  if [ -n "$GH_TOKEN" ]; then
    guarded git -c http.extraheader="AUTHORIZATION: bearer ${GH_TOKEN}" push -u origin "$branch"
  else
    guarded git push -u origin "$branch"
  fi

  # Open or update the PR.
  local existing
  existing=$(gh pr list --head "$branch" --json number -q '.[0].number' 2>/dev/null || echo "")
  if [ -z "$existing" ]; then
    if [ "$DRY_RUN" = "true" ]; then
      log "[dry-run] gh pr create --head $branch --label loop-autonomous"
      PR_NUMBER="dry-run"
    else
      local url
      url=$(gh pr create \
        --title "feedback-loop: $(date -u +%Y-%m-%d) refinement" \
        --body "Autonomous refinement from \`feedback-loop.sh\`. See commits for per-marker reasoning. Triage: corpus regression + property tests are CI-gated." \
        --label loop-autonomous)
      PR_NUMBER="${url##*/}"
    fi
  else
    PR_NUMBER="$existing"
  fi
  set_output pr_number "$PR_NUMBER"
  log "pr_number=$PR_NUMBER"
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

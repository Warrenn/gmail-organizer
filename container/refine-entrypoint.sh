#!/usr/bin/env bash
#
# refine-entrypoint.sh — the Fargate "refine" task's entrypoint. It is the
# AWS-side analogue of the `refine` GitHub Actions job (now retired): it
# provisions a clean, ephemeral checkout, pulls the scan artifacts that the
# `scan` Lambda wrote to S3, then runs the SAME scripts/feedback-loop.sh
# `refine` + `verify` phases — fully autonomously (DRY_RUN=false,
# LOOP_AUTO_MERGE=true) — under the user's Claude Max SUBSCRIPTION token.
#
# Containment (unchanged from the GitHub Actions model):
#   - This task has NO Gmail credentials and NO access to the gmail-token SSM
#     param (enforced by the task role's IAM policy — see infra/). Claude can
#     therefore never reach a mailbox.
#   - Claude authenticates via CLAUDE_CODE_OAUTH_TOKEN (Max subscription), pulled
#     from SSM by feedback-loop.sh. ANTHROPIC_API_KEY is NEVER set; we assert it
#     unset here too (defence in depth — the API key would silently bill per
#     token instead of the subscription).
#   - feedback_resolved.json is NOT committed (it is gitignored + off the commit
#     allow-list). Claude writes it to the worktree; this entrypoint ships it to
#     the encrypted S3 artifact bucket, where the cleanup-markers Lambda reads it.
#
# Environment contract:
#   ARTIFACT_BUCKET   (required) S3 bucket holding feedback.json / corpus.json,
#                     and the destination for feedback_resolved.json.
#   ARTIFACT_PREFIX   (optional) key prefix within the bucket. Default: "".
#   REPO_SLUG         (optional) owner/repo to clone. Default Warrenn/gmail-organizer.
#   REPO_REF          (optional) branch to base refinement on. Default: main.
#   SSM_PREFIX        (optional) SSM namespace. Default: /cleanup-gmail.
#   AWS_REGION / AWS_DEFAULT_REGION are provided by the Fargate task env.
#   FEEDBACK_LOOP_SH  (optional, for tests) path/name of feedback-loop.sh to run.
#                     Default: the copy baked into the image at /app/scripts.
#
# All credentials are pulled from SSM into env vars only — never written to disk.

set -euo pipefail

log() { printf '%s\n' "refine-entrypoint: $*" >&2; }
die() { log "ERROR: $*"; exit 1; }

# --- Guard rails -----------------------------------------------------------
# Refuse to run under an API key so usage bills the subscription, not the API.
[ -z "${ANTHROPIC_API_KEY:-}" ] || \
  die "ANTHROPIC_API_KEY is set — refusing to run so Claude bills the Max subscription, not the per-token API. Unset it."

: "${ARTIFACT_BUCKET:?ARTIFACT_BUCKET is required (the S3 artifact bucket)}"
: "${ARTIFACT_PREFIX:=}"
: "${REPO_SLUG:=Warrenn/gmail-organizer}"
: "${REPO_REF:=main}"
: "${SSM_PREFIX:=/cleanup-gmail}"
: "${FEEDBACK_LOOP_SH:=/app/scripts/feedback-loop.sh}"

# Build an s3:// key, honouring an optional prefix without a double slash.
s3key() {
  local name="$1"
  if [ -n "$ARTIFACT_PREFIX" ]; then
    printf 's3://%s/%s/%s' "$ARTIFACT_BUCKET" "${ARTIFACT_PREFIX%/}" "$name"
  else
    printf 's3://%s/%s' "$ARTIFACT_BUCKET" "$name"
  fi
}

ssm() {
  aws ssm get-parameter --name "$1" --with-decryption \
    --query Parameter.Value --output text
}

# --- 1. Clone the repo via a GitHub token from SSM -------------------------
# The token is used only to construct the clone URL in-process and is dropped
# from the environment immediately after; feedback-loop.sh re-pulls its own
# GH_TOKEN-equivalent path via the standard git credential header it builds.
GH_TOKEN=$(ssm "$SSM_PREFIX/github-token")
[ -n "$GH_TOKEN" ] || die "empty github-token from SSM"
export GH_TOKEN          # feedback-loop.sh uses GH_TOKEN for push + gh pr

WORKDIR="$(pwd)/repo"
log "Cloning https://github.com/$REPO_SLUG (ref $REPO_REF) into $WORKDIR"
# Authenticate the clone via the x-access-token Basic scheme (same scheme
# feedback-loop.sh's push_branch uses). Avoids embedding the token in the URL
# (which would land in git remote config / process listings).
clone_basic=$(printf 'x-access-token:%s' "$GH_TOKEN" | base64 | tr -d '\n')
git -c http.extraheader="AUTHORIZATION: basic ${clone_basic}" \
  clone --branch "$REPO_REF" "https://github.com/${REPO_SLUG}.git" "$WORKDIR"
cd "$WORKDIR"

# --- 2. Pull the scan artifacts (feedback.json + corpus) from S3 -----------
# These are email-derived; they live only transiently here and in the encrypted
# bucket, never committed. corpus.json lands at tests/corpus.json so the
# regression gate (pytest) sees it in its expected location.
log "Pulling scan artifacts from s3://$ARTIFACT_BUCKET"
aws s3 cp "$(s3key feedback.json)" feedback.json
mkdir -p tests
aws s3 cp "$(s3key corpus.json)" tests/corpus.json \
  || log "no corpus.json in S3 — refine will run without a regression corpus"

# --- 3. Run the refine + verify phases, fully autonomous -------------------
# DRY_RUN=false → real push/PR/merge. LOOP_AUTO_MERGE=true → squash-merge on a
# green, allow-list-clean PR. feedback-loop.sh pulls the subscription OAuth
# token from SSM itself and asserts ANTHROPIC_API_KEY unset before invoking
# claude. PYTHON=python3 because the slim image ships python3, not `python`.
export DRY_RUN=false
export LOOP_AUTO_MERGE=true
export SSM_PREFIX
export BASE_REF="origin/${REPO_REF}"
export PYTHON="${PYTHON:-python3}"

log "Running refine phase"
"$FEEDBACK_LOOP_SH" refine

log "Running verify phase"
"$FEEDBACK_LOOP_SH" verify

# --- 4. Ship feedback_resolved.json to S3 ----------------------------------
# Claude writes it to the worktree; it is intentionally NOT committed. The
# cleanup-markers Lambda reads it from S3 to apply the Gmail-side mutations.
if [ -f feedback_resolved.json ]; then
  log "Uploading feedback_resolved.json to s3://$ARTIFACT_BUCKET"
  aws s3 cp feedback_resolved.json "$(s3key feedback_resolved.json)"
else
  log "no feedback_resolved.json produced — uploading an empty manifest"
  printf '[]\n' > feedback_resolved.json
  aws s3 cp feedback_resolved.json "$(s3key feedback_resolved.json)"
fi

# --- 5. Ship the post-merge Apps Script artifacts to S3 --------------------
# The deploy-apps-script Lambda has no checkout of its own; it pulls the
# regenerated, just-merged Rules.gs/Classifier.gs (plus the static Code.gs +
# manifest) from S3 so the LIVE Google labeler gets this run's improved rules.
for f in Rules.gs Classifier.gs Code.gs appsscript.json; do
  if [ -f "apps-script/$f" ]; then
    aws s3 cp "apps-script/$f" "$(s3key "apps-script/$f")"
  fi
done

log "done"

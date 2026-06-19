# AWS bootstrap — the scheduled feedback-loop pipeline

The autonomous `+X` / `-X` feedback loop runs entirely on a **6-hourly AWS
pipeline** — there is no longer any GitHub Actions involvement. This file is
the one-time setup: create the SSM secrets, mint the Claude subscription token,
deploy the CloudFormation stack, and (optionally) tear it all down.

## Architecture at a glance

```
EventBridge Scheduler (every 6h, af-south-1)
      │
      ▼
Step Functions: feedback-loop
      ├─ (1) Lambda  scan     — Gmail token from SSM → feedback-scan + corpus-build
      │                          → upload feedback.json/corpus.json to S3
      │                          → returns hasMarkers (Choice: stop if false)
      ├─ (2) Fargate refine    — Claude (Max subscription) refines rules, opens +
      │                          auto-merges the PR; uploads feedback_resolved.json
      │                          and the regenerated apps-script files to S3
      ├─ (3a) Lambda deploy     — pushes the refreshed Rules.gs/Classifier.gs to the
      │                          live Google Apps Script labeler
      └─ (3b) Lambda cleanup    — applies the resolved +/- markers to Gmail, deletes
                                 marker labels (reads feedback_resolved.json from S3)
```

**Cost:** Fargate bills per-second only while the (short) refine task runs;
Lambda / Step Functions / EventBridge / S3 are free-tier or pennies; the only
standing cost is the ECR image (~$0.10/GB-mo). **No NAT gateway** (the refine
task runs in a public subnet with a public IP). Claude is **$0 extra** — it
bills against your existing Max subscription, not the per-token API.

**Secrets:** all credentials are SSM SecureStrings, injected as runtime
environment variables — never written to disk, never committed. Email-derived
artifacts (`feedback.json`, `corpus.json`, `feedback_resolved.json`) live only
transiently in an encrypted S3 bucket and are never committed to the repo.

---

## What you'll create

1. **SSM SecureString parameters** under `/cleanup-gmail/`:
   - `gmail-token-json` — Gmail OAuth token (scan + cleanup).
   - `apps-script-token-json` — Apps Script OAuth token, scope `script.projects`
     (deploy).
   - `claude-code-oauth-token` — **NEW.** Claude Max subscription token (refine).
   - `github-token` — **NEW.** A GitHub token the refine task uses to clone,
     push the branch, and open + auto-merge the PR.
   - `anthropic-api-key` is **RETIRED** — see "Retiring the API key" below.
2. An **ECR repository** + the built **refine container image**.
3. The **CloudFormation stack** (`infra/`) that creates the S3 bucket, the three
   Lambdas, the ECS cluster + Fargate task, the Step Functions state machine,
   the EventBridge schedule, the IAM roles, and the CloudWatch log groups +
   failure alarm.

All steps assume region `af-south-1` and account ID `<YOUR_ACCOUNT_ID>` —
substitute your values. The `/cleanup-gmail/` SSM namespace is referenced by the
stack parameters; keep it (or override `SsmPrefix`).

---

## Step 1 — Populate Parameter Store

### `/cleanup-gmail/gmail-token-json`

The authorized-user Gmail token (scopes `gmail.modify`, `gmail.labels`). This
is the **only** Gmail secret the runtime needs — it self-contains the client
id/secret and refresh token. **Credentials are never written to disk**: the
`mint-token` command runs the OAuth consent flow and prints the token to stdout,
which you pipe straight into SSM.

You need a **Desktop** OAuth client JSON from Google Cloud Console (APIs &
Services → Credentials). Then, in a checkout with the venv active:

```sh
python -m gmail_cleanup mint-token \
    --client-secret ~/Downloads/client_secret_*.json \
  | aws ssm put-parameter \
      --name /cleanup-gmail/gmail-token-json \
      --type SecureString \
      --value file:///dev/stdin
```

> OAuth refresh tokens generally don't rotate, but Google can invalidate them on
> a security review or if you revoke the grant. If that happens, re-run the
> `mint-token | put-parameter --overwrite` pipeline. The per-run access-token
> refresh is in-memory only and is never persisted.

### `/cleanup-gmail/apps-script-token-json`

A second OAuth token scoped **only** to `script.projects`, used by the deploy
Lambda to push the regenerated Apps Script via the API (no clasp, no files):

```sh
python -m gmail_cleanup mint-token --scopes apps-script \
    --client-secret ~/Downloads/<desktop-client>.json \
  | aws ssm put-parameter --name /cleanup-gmail/apps-script-token-json \
      --type SecureString --value file:///dev/stdin --overwrite
```

Prerequisites for the Apps Script API (both required, as the script's owner):
- Enable the **Apps Script API**:
  `https://console.cloud.google.com/apis/library/script.googleapis.com?project=<PROJECT_ID>`
- Turn on the per-user toggle: `https://script.google.com/home/usersettings`

### `/cleanup-gmail/claude-code-oauth-token`  (NEW — the subscription token)

This is what makes Claude refine **free** under your Max subscription instead of
billing the per-token API. Generate it with the Claude Code CLI on your own
machine (it opens a browser to authorize against your subscription):

```sh
# One-time, interactive. Prints a long-lived OAuth token to stdout.
claude setup-token
```

Pipe (or paste) the resulting token straight into SSM — never save it to a file:

```sh
claude setup-token \
  | aws ssm put-parameter \
      --name /cleanup-gmail/claude-code-oauth-token \
      --type SecureString \
      --value file:///dev/stdin
```

> The refine task asserts `ANTHROPIC_API_KEY` is **unset** before invoking
> `claude` (the API key takes precedence inside Claude Code and would silently
> re-introduce per-token billing). The pipeline never sets it.
>
> Rotate this token roughly **annually** (or whenever Claude Code prompts that
> it has expired): re-run `claude setup-token | put-parameter --overwrite`.

### `/cleanup-gmail/github-token`  (NEW)

A GitHub token the refine task uses to clone the repo, push the refinement
branch, and open + auto-merge the PR. A **fine-grained personal access token**
(or a GitHub App installation token) scoped to `Warrenn/gmail-organizer` with
**Contents: read/write** and **Pull requests: read/write** is sufficient.

```sh
aws ssm put-parameter \
  --name /cleanup-gmail/github-token \
  --type SecureString \
  --value 'github_pat_...' \
  --description 'GitHub token for the Fargate refine task (clone/push/PR/merge)'
```

> This token is granted **only** to the refine task role — not to any Lambda.
> Rotate per your PAT expiry policy with `put-parameter --overwrite`.

### Retiring the API key

The old `/cleanup-gmail/anthropic-api-key` is no longer used by anything. Delete
it so it can't be accidentally reintroduced:

```sh
aws ssm delete-parameter --name /cleanup-gmail/anthropic-api-key
```

---

## Step 2 — Build and push the refine container image

The CloudFormation stack references an ECR image URI. Create the repo, build the
image (from `container/Dockerfile`), and push it.

```sh
ACCOUNT=<YOUR_ACCOUNT_ID>
REGION=af-south-1
REPO=gmail-organizer-refine

aws ecr create-repository --repository-name "$REPO" --region "$REGION"

aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"

# Build for the Fargate CPU architecture you'll run on (X86_64 by default).
docker build --platform linux/amd64 -f container/Dockerfile \
  -t "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest" .

docker push "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/$REPO:latest"
```

> The image contains **no credentials** — it pulls everything from SSM at
> runtime. Rebuild + push when `scripts/feedback-loop.sh`,
> `container/refine-entrypoint.sh`, or the pinned tool versions change.

---

## Step 3 — Deploy the CloudFormation stack

The stack lives in `infra/`. It needs your account/region, the ECR image URI,
the target Apps Script project ID, and the **public subnet(s)** the Fargate task
runs in (any subnet that auto-assigns a public IP / sits behind an internet
gateway — no NAT).

```sh
aws cloudformation deploy \
  --region af-south-1 \
  --stack-name gmail-organizer-loop \
  --template-file infra/feedback-loop.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      ImageUri="$ACCOUNT.dkr.ecr.af-south-1.amazonaws.com/gmail-organizer-refine:latest" \
      AppsScriptId=<APPS_SCRIPT_PROJECT_ID> \
      SubnetIds=subnet-aaaa,subnet-bbbb \
      RepoSlug=Warrenn/gmail-organizer
```

Validate / dry-run before deploying:

```sh
aws cloudformation validate-template --template-body file://infra/feedback-loop.yaml
cfn-lint infra/feedback-loop.yaml
```

See `infra/README.md` for the full parameter list and the IAM least-privilege
notes (in particular: the refine task role gets the OAuth + GitHub + S3 access
but **no** Gmail / `gmail-token` access — Claude can never reach a mailbox).

---

## Step 4 — Smoke test

Trigger one Step Functions execution manually instead of waiting for the
schedule:

```sh
aws stepfunctions start-execution \
  --state-machine-arn <arn-from-stack-outputs>
```

With no `+X` / `-X` markers in your mailbox, the `scan` step returns
`hasMarkers: false` and the Choice stops the execution cleanly — no refine, no
Fargate cost. To exercise the full chain, apply a `+sometestlabel` to a thread,
then start an execution and watch:

1. `scan` uploads `feedback.json` + `corpus.json` to the S3 bucket.
2. `refine` (Fargate) opens and auto-merges a PR, uploads
   `feedback_resolved.json`.
3. `deploy` pushes the refreshed rules to the live Apps Script labeler.
4. `cleanup` applies the resolved marker to Gmail and deletes the marker label.

If anything fails, the state machine surfaces the failing step and the
CloudWatch failure alarm fires. Logs are in the per-component CloudWatch log
groups (see stack outputs).

---

## Teardown

To remove everything:

```sh
# 1. Empty + delete the artifact bucket's objects first (CloudFormation won't
#    delete a non-empty bucket).
aws s3 rm s3://<artifact-bucket-name> --recursive

# 2. Delete the stack (removes Lambdas, ECS, Step Functions, schedule, IAM,
#    log groups, the bucket, the failure alarm).
aws cloudformation delete-stack --stack-name gmail-organizer-loop
aws cloudformation wait stack-delete-complete --stack-name gmail-organizer-loop

# 3. Delete the ECR repo (images are not managed by the stack).
aws ecr delete-repository --repository-name gmail-organizer-refine --force

# 4. (Optional) Remove the SSM secrets if you're fully decommissioning.
for p in gmail-token-json apps-script-token-json claude-code-oauth-token github-token; do
  aws ssm delete-parameter --name "/cleanup-gmail/$p"
done
```

---

## Future maintenance

- **Rotate the Claude subscription token** (~annually): `claude setup-token |
  aws ssm put-parameter --name /cleanup-gmail/claude-code-oauth-token
  --type SecureString --value file:///dev/stdin --overwrite`.
- **Rotate the GitHub token**: `put-parameter --overwrite` with a fresh PAT.
- **Rotate Gmail / Apps Script OAuth**: re-mint and `put-parameter --overwrite`.
- **Update the refine image**: rebuild from `container/Dockerfile` and push to
  ECR (`:latest`); the next scheduled run picks it up.
- **Audit access**: CloudTrail logs every `ssm:GetParameter` with the calling
  role's session name. Filter on `eventSource = ssm.amazonaws.com` plus the
  role name to see exactly which component read which secret.

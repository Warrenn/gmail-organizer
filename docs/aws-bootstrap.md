# AWS bootstrap — one-time setup for the feedback-loop workflows

The autonomous feedback loop runs in GitHub Actions and pulls its
credentials from AWS Systems Manager Parameter Store via short-lived
OIDC credentials. This file walks you through the one-time setup. Once
done, the workflow runs without any further AWS work from you.

## What you'll create

1. A GitHub OIDC **IAM identity provider** in your AWS account (one per
   account, reusable across all your GitHub repos).
2. An assumable **IAM role** scoped to this repo, with permission to
   read the Parameter Store params under `/cleanup-gmail/`.
3. **SecureString** parameters under `/cleanup-gmail/`: `anthropic-api-key`
   and `gmail-token-json` (required by the feedback-loop), plus `clasp-rc-json`
   (only for `deploy.yml`). Credentials live in SSM only — never in files.

All steps below assume the AWS region `eu-west-1` and account ID
`<YOUR_ACCOUNT_ID>` — substitute your values. The Parameter Store
namespace `/cleanup-gmail/` is hardcoded into the workflow YAMLs, so
keep it.

---

## Step 1 — Create the GitHub OIDC identity provider

Skip this step if you've already set up GitHub OIDC for another repo in
the same AWS account; the provider is account-wide.

### Console path

1. AWS Console → **IAM** → **Identity providers** → **Add provider**.
2. Provider type: **OpenID Connect**.
3. Provider URL: `https://token.actions.githubusercontent.com`. Click
   **Get thumbprint**.
4. Audience: `sts.amazonaws.com`.
5. Click **Add provider**.

### CLI alternative

```sh
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```

(The thumbprint is GitHub's well-known OIDC certificate fingerprint; it
may rotate — fetch the latest from
https://github.blog/changelog/2022-01-13-github-actions-update-on-oidc-based-deployments-to-aws/
or compute via `openssl s_client`.)

---

## Step 2 — Create the assumable IAM role

This role is what the GitHub Action assumes. Trust policy limits which
repo (and which workflows) can assume it; permission policy limits
what it can do.

### Trust policy (`trust-policy.json`)

Save this locally; you'll attach it on role creation. Substitute
`<YOUR_ACCOUNT_ID>`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::<YOUR_ACCOUNT_ID>:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
        },
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:Warrenn/gmail-organizer:*"
        }
      }
    }
  ]
}
```

The `StringLike` on `sub` restricts assumption to workflows running in
the `Warrenn/gmail-organizer` repo (any branch, any workflow). If you
want to scope it further to a specific workflow, replace the wildcard
with `repo:Warrenn/gmail-organizer:ref:refs/heads/main` or similar.

### Permission policy (`permission-policy.json`)

Substitute `<YOUR_ACCOUNT_ID>` and `<YOUR_REGION>` (e.g. `eu-west-1`).

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ssm:GetParameter", "ssm:GetParameters"],
      "Resource": [
        "arn:aws:ssm:<YOUR_REGION>:<YOUR_ACCOUNT_ID>:parameter/cleanup-gmail/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["kms:Decrypt"],
      "Resource": "*",
      "Condition": {
        "StringLike": {
          "kms:EncryptionContext:PARAMETER_ARN": "arn:aws:ssm:<YOUR_REGION>:<YOUR_ACCOUNT_ID>:parameter/cleanup-gmail/*"
        }
      }
    }
  ]
}
```

The KMS clause lets the role decrypt SecureString parameters; the
condition scopes it to our namespace only.

### Create the role

```sh
aws iam create-role \
  --role-name gmail-organizer-loop \
  --assume-role-policy-document file://trust-policy.json

aws iam put-role-policy \
  --role-name gmail-organizer-loop \
  --policy-name gmail-organizer-loop-policy \
  --policy-document file://permission-policy.json
```

Note the resulting role ARN — you'll paste it into the workflow
YAMLs (or set it as a GitHub repo variable, see below).

---

## Step 3 — Populate Parameter Store

SecureString params under `/cleanup-gmail/`. The feedback-loop needs
`anthropic-api-key` and `gmail-token-json`; `clasp-rc-json` is only for
`deploy.yml`. There is no `gmail-credentials-json` param — credentials are
never persisted to a file.

### `/cleanup-gmail/anthropic-api-key`

Your Anthropic API key. Create one at
https://console.anthropic.com/settings/keys.

```sh
aws ssm put-parameter \
  --name /cleanup-gmail/anthropic-api-key \
  --value 'sk-ant-...' \
  --type SecureString \
  --description 'Anthropic API key for the feedback-loop GitHub Action'
```

### `/cleanup-gmail/gmail-token-json`

The authorized-user token. This is the **only** Gmail secret the runtime
needs — it self-contains the client id/secret and refresh token. **Credentials
are never written to disk**: the `mint-token` command runs the OAuth consent
flow and prints the token to stdout, which you pipe straight into SSM. Nothing
touches the filesystem.

You need a **Desktop** OAuth client JSON downloaded from Google Cloud Console
(APIs & Services → Credentials). Then, in a checkout with the venv active:

```sh
# Reads the downloaded client config in memory, runs the browser consent,
# and streams the resulting token straight into SSM — no token file is created.
python -m gmail_cleanup mint-token \
    --client-secret ~/Downloads/client_secret_*.json \
  | aws ssm put-parameter \
      --name /cleanup-gmail/gmail-token-json \
      --type SecureString \
      --value file:///dev/stdin
```

> **OAuth refresh tokens generally don't rotate**, but Google can
> invalidate them if the account does a security review or if the user
> revokes the grant. If that happens, the workflow fails with a 401;
> re-run the `mint-token | put-parameter --overwrite` pipeline above to
> refresh the SSM value. The access-token refresh that happens on every
> run is in-memory only and is never persisted.

> **No `gmail-credentials-json` parameter is required.** The OAuth client
> config is only needed at mint time (passed via `--client-secret`); the
> runtime never uses it. Delete the downloaded client JSON afterwards if you
> want nothing sensitive left on disk.

### `/cleanup-gmail/clasp-rc-json`

Contents of your local `~/.clasprc.json` (clasp's saved auth state).

```sh
aws ssm put-parameter \
  --name /cleanup-gmail/clasp-rc-json \
  --value "$(cat ~/.clasprc.json)" \
  --type SecureString
```

---

## Step 4 — Configure GitHub repo

Three repository variables and zero secrets (everything sensitive lives
in AWS now).

In `Settings → Secrets and variables → Actions → Variables`:

| Variable name           | Value                                                                  |
|-------------------------|------------------------------------------------------------------------|
| `AWS_ROLE_TO_ASSUME`    | The role ARN from Step 2 (e.g. `arn:aws:iam::123456789012:role/gmail-organizer-loop`) |
| `AWS_REGION`            | e.g. `eu-west-1`                                                       |
| `LOOP_AUTO_MERGE`       | `false` for soft launch. Set to `true` later to enable auto-merge.     |

Workflow files reference these via `${{ vars.AWS_ROLE_TO_ASSUME }}` etc.
— no rotation needed and they're public-readable, which is fine since
they're just ARNs and region strings.

---

## Step 5 — Smoke test

Manually trigger the feedback-loop workflow (Actions tab → feedback-loop
→ Run workflow → main branch). The `scan` job should:

1. Successfully assume the role via OIDC (look for `Configure AWS
   credentials` step success).
2. Pull `gmail-credentials-json` and `gmail-token-json`, write them to
   the runner, and run `python -m gmail_cleanup feedback-scan`.
3. Exit cleanly with `feedback: 0 markers, 0 threads → feedback.json`
   (because you haven't placed any `+X` / `-X` labels yet).

The `refine` job is skipped when there are no markers. The workflow run
should be all green.

If anything fails:
- **OIDC error**: check the trust policy's `sub` claim matches the repo
  exactly; check the OIDC provider exists.
- **AccessDenied on SSM**: check the role's permission policy ARN
  patterns; check the param exists under the exact name.
- **`token.json` 401**: refresh as noted in Step 3.

---

## Future maintenance

- **Rotate the Anthropic API key**: create a new key in the Anthropic
  console, `put-parameter --overwrite` the SSM param, the next workflow
  run picks it up. No GitHub-side change.
- **Rotate Gmail OAuth**: re-grant locally, re-put `gmail-token-json`.
- **Rotate clasp**: `clasp logout && clasp login`, re-put `clasp-rc-json`.
- **Audit access**: AWS CloudTrail logs every `ssm:GetParameter` with
  the role's session name (set by the Action). Filter on
  `eventSource = ssm.amazonaws.com` + the role name.

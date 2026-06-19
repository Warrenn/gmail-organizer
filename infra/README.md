# infra/ — CloudFormation for the feedback-loop pipeline

`feedback-loop.yaml` is the single stack that provisions the whole scheduled
pipeline:

```
EventBridge Scheduler (6h) → Step Functions → scan Lambda
   → (hasMarkers?) → Fargate refine task → deploy Lambda → cleanup Lambda
```

plus the encrypted S3 artifact bucket, per-component IAM roles, CloudWatch log
groups, and an SNS failure alarm.

## Validate

```sh
cfn-lint infra/feedback-loop.yaml
aws cloudformation validate-template \
  --region af-south-1 --template-body file://infra/feedback-loop.yaml
```

`cfn-lint` is the offline gate (run it in CI / pre-commit). `validate-template`
needs AWS credentials + a region, so run it as part of the deploy.

## Parameters

| Parameter | Default | Notes |
|-----------|---------|-------|
| `ImageUri` | — (required) | ECR URI of the refine image built from `container/Dockerfile`. |
| `AppsScriptId` | — (required) | Apps Script project the deploy Lambda pushes to. |
| `SubnetIds` | — (required) | **Public** subnet(s) for the Fargate task. Must reach the internet via an IGW — **no NAT**. |
| `RepoSlug` | `Warrenn/gmail-organizer` | owner/repo the refine task clones/pushes/PRs. |
| `RepoRef` | `main` | Branch refinements are based on. |
| `SsmPrefix` | `/cleanup-gmail` | SSM namespace holding the secrets. |
| `CorpusPerLabel` | `3` | Threads/label the scan Lambda samples for the regression corpus. |
| `ScheduleExpression` | `rate(6 hours)` | EventBridge cadence. |
| `ScheduleEnabled` | `ENABLED` | Set `DISABLED` for a dormant deploy. |
| `LambdaCodeBucket` | `""` | Bucket holding the Lambda zips. Empty ⇒ use the artifact bucket this stack creates. |
| `Lambda{Scan,Deploy,Cleanup}Key` | `lambdas/<name>.zip` | S3 keys of the zips. |
| `LogRetentionDays` | `30` | CloudWatch retention. |
| `AlarmEmail` | `""` | Optional email subscribed to the failure SNS topic. |

## Deploy

```sh
aws cloudformation deploy \
  --region af-south-1 \
  --stack-name gmail-organizer-loop \
  --template-file infra/feedback-loop.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      ImageUri=<acct>.dkr.ecr.af-south-1.amazonaws.com/gmail-organizer-refine:latest \
      AppsScriptId=<APPS_SCRIPT_PROJECT_ID> \
      SubnetIds=subnet-aaaa,subnet-bbbb
```

`CAPABILITY_NAMED_IAM` is required because the roles use explicit `RoleName`s.

## IAM least-privilege (the containment boundary)

Each component gets only what it needs:

| Component | SSM secrets | S3 | Notes |
|-----------|-------------|----|-------|
| `scan` Lambda | `gmail-token-json` (read) | put | Builds feedback.json + corpus. |
| `refine` Fargate **task role** | `claude-code-oauth-token`, `github-token` (read) | get/put | **No Gmail / gmail-token access.** Claude can never reach a mailbox or Google. |
| `deploy` Lambda | `apps-script-token-json` (read) | get | Pushes rules to Apps Script. |
| `cleanup` Lambda | `gmail-token-json` (read) | get | Applies the resolved markers to Gmail. |

The refine task's `TaskRoleArn` is the strict containment boundary — it is the
one place Claude's container identity is defined, and it deliberately excludes
every Gmail credential. (The Fargate **execution** role is separate and only
pulls the image + writes logs.)

`kms:Decrypt` is scoped to the `alias/aws/ssm` key (the default SecureString
key). If you encrypt the params under a customer-managed key, swap that ARN.

## Lambda packaging (important)

The Lambda `Handler`s are `lambdas.<name>.handler.handler`, so each zip must
contain, at its root:

- the `lambdas/` package (`__init__.py`, `common.py`, and the function's
  `<name>/handler.py`),
- the `gmail_cleanup/` package (the handlers import its command logic),
- the **vendored Python dependencies** the handlers pull in:
  `google-api-python-client`, `google-auth`, `google-auth-oauthlib`,
  `google-auth-httplib2`, `pyyaml`. (`boto3`/`botocore` are provided by the
  Lambda runtime — do not vendor them.)
- for the **scan** Lambda only: a copy of `gmail_cleanup/rules.yaml` is needed
  for the corpus agreement filter; it resolves via the package, so shipping
  `gmail_cleanup/` covers it.
- for the **deploy** Lambda: the static `apps-script/Code.gs` +
  `appsscript.json` may optionally be baked under `lambdas/deploy/apps-script/`
  as a fallback; the post-merge `Rules.gs`/`Classifier.gs` are pulled from S3 at
  runtime (uploaded by the refine task), so a bake is not strictly required.

Example build (run from the repo root, per function):

```sh
pkg=build/scan && rm -rf "$pkg" && mkdir -p "$pkg"
cp -r lambdas gmail_cleanup "$pkg"/
pip install --target "$pkg" \
  google-api-python-client google-auth google-auth-oauthlib \
  google-auth-httplib2 pyyaml
( cd "$pkg" && zip -qr ../scan.zip . )
aws s3 cp build/scan.zip s3://<code-or-artifact-bucket>/lambdas/scan.zip
```

Then deploy/update the stack so the functions point at the uploaded zips. (A
small `make`/script to build all three is a reasonable follow-up; left out here
to avoid prescribing a build tool.)

## On-demand run / teardown

See `docs/aws-bootstrap.md` for the manual `start-execution` smoke test and the
full teardown sequence.

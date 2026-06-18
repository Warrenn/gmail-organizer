# STRATEGY — Migrate the feedback loop off GitHub Actions to a scheduled AWS pipeline (subscription-billed Claude)

Status: **DRAFT — awaiting approval.** No implementation code until this is approved.

## Goal

Move the autonomous `+X` / `-X` feedback loop off GitHub Actions and onto a **6-hourly AWS pipeline**, and switch the Claude refine step from the **pay-per-token API** (`ANTHROPIC_API_KEY`) to the user's **existing Claude Max subscription** (`CLAUDE_CODE_OAUTH_TOKEN`) so there is **no additional Claude or API cost**.

### Requirements
1. Runs on a 6-hour cadence with no GitHub Actions involvement.
2. Claude refine billed against the Max subscription, not the API. Confirmed mechanism: `claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN`; supported under ToS; free under the subscription today. The pipeline must **not** set `ANTHROPIC_API_KEY` (it takes precedence and would re-introduce billing).
3. Preserve the existing safety properties: allow-list-gated file edits, pytest regression gate, git/PR audit trail, and the containment model (the Claude step has no Gmail credentials).
4. Keep AWS infra cost negligible (target: only the 4 short Fargate runs/day; **no NAT gateway**).

### Non-goals
- Changing the classification logic, the rule format, or `.github/prompts/feedback-loop.md` behaviour.
- Moving the git repository off GitHub (only the *compute* leaves GitHub; the repo + PRs stay on GitHub).
- Touching the production Apps Script hourly path.

## Approach

EventBridge Scheduler fires a Step Functions state machine every 6 hours:

```
EventBridge Scheduler (rate: 6 hours, eu-west-1)
      │
      ▼
Step Functions: feedback-loop
      │
      ├─(1) Lambda  scan            (Python; default network egress, no VPC)
      │        load /cleanup-gmail/gmail-token-json from SSM
      │        python -m gmail_cleanup feedback-scan  → feedback.json
      │        python -m gmail_cleanup corpus-build   → corpus
      │        upload artifacts to S3; return hasMarkers (Choice: stop if false)
      │
      ├─(2) Fargate task  refine    (container; public subnet + public IP, NO NAT)
      │        load /cleanup-gmail/claude-code-oauth-token from SSM → CLAUDE_CODE_OAUTH_TOKEN
      │        (ANTHROPIC_API_KEY is never set — asserted unset before running claude)
      │        git clone repo; pull feedback.json/corpus from S3
      │        claude -p "$(cat .github/prompts/feedback-loop.md)" --permission-mode acceptEdits
      │        verify allow-list  +  pytest   (reuse scripts/feedback-loop.sh logic)
      │        commit → push branch → open PR → auto-merge on green
      │        write feedback_resolved.json → S3
      │
      ├─(3a) Lambda  deploy-apps-script (Python; default egress, no VPC)
      │        load /cleanup-gmail/apps-script-token-json from SSM (scope: script.projects)
      │        python -m gmail_cleanup deploy-apps-script
      │        (push regenerated Rules.gs/Classifier.gs to the LIVE Google Apps Script labeler
      │         so improved rules take effect — replaces deploy.yml)
      │
      └─(3b) Lambda  cleanup-markers (Python; default network egress, no VPC)
               load gmail-token-json from SSM
               read feedback_resolved.json (S3)
               python -m gmail_cleanup cleanup-markers  (apply +/- to Gmail, delete markers)
```

### Cost & secrets guarantees (explicit, per user requirements)
- **No idle/server cost.** Fargate bills per-second only while a task runs ($0 when idle); the ECS cluster is free; Lambda/Step Functions/EventBridge/S3 are free-tier/pennies; the only standing cost is the ECR image (~$0.10/GB-mo). **No NAT gateway** (public subnet + public IP) — avoids the ~$32/mo idle cost. Target: < $1/mo, realistically cents. Claude is $0 extra (Max subscription).
- **No secrets on disk or in the repo.** All credentials are SSM SecureStrings (`gmail-token-json`, `apps-script-token-json`, `claude-code-oauth-token`), injected as runtime env vars (ECS Secrets / SSM fetch), never written to disk or committed. Fargate's repo clone is ephemeral. Email-content artifacts (`feedback.json`, `corpus.json`) live only transiently in an encrypted S3 bucket, never committed. `anthropic-api-key` is retired from SSM.

### Key decisions (and rationale) — please confirm or adjust

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | Where the Claude refine runs | **ECS Fargate task** | Approved earlier. No 15-min Lambda ceiling for the agentic session; clean container packaging of node+claude+git+gh+python. |
| D2 | Auth | **`CLAUDE_CODE_OAUTH_TOKEN` in SSM** (`/cleanup-gmail/claude-code-oauth-token`), `ANTHROPIC_API_KEY` removed | Subscription billing, no per-token charge. API key removed to avoid the precedence gotcha. |
| D3 | IaC tool | **CloudFormation** (new `infra/` dir, YAML templates) — *user choice* | Native to AWS, no extra tooling or state store. `aws cloudformation validate-template` + `cfn-lint` are the TDD substitute for infra (per global CLAUDE.md). |
| D4 | Safety gate | **Approved — fully autonomous: open PR + auto-merge on green**, then proceed to deploy + cleanup (reuse `LOOP_AUTO_MERGE`) | Keeps the git/PR audit trail and the allow-list+pytest gates while staying fully scheduled. |
| D8 | Apps Script deploy | **Migrate `deploy.yml` → `deploy-apps-script` Lambda** in the pipeline | Without it, improved rules never reach the live Google-side labeler. Reuses existing `gmail_cleanup deploy-apps-script` + SSM `apps-script-token-json` (already disk-free). |
| D5 | Orchestration | **Step Functions** | Native Lambda→Fargate→Lambda sequencing, the `hasMarkers` Choice/skip, retries, and failure alarms — cleaner than chaining inside one container. |
| D6 | Networking / cost | **Public subnet + public IP for Fargate; Lambdas outside any VPC** | Both need outbound internet (GitHub, Anthropic, Gmail, pip). Avoids a NAT gateway (~$32/mo) — keeps the "no extra cost" promise; AWS infra cost for 4 short runs/day is pennies. |
| D7 | Repo host | **Stays GitHub** | Fargate uses `git`+`gh` against `github.com/Warrenn/gmail-organizer`. Only the compute leaves GitHub Actions. |

### Parallelism assessment
Decomposable into ≥2 file-disjoint units (container image, Lambda handlers, Terraform, docs are largely disjoint). See `## Parallel Decomposition`. Terraform (Unit C) depends on the artifacts of A/B being defined (image name, handler names) but not their internals, so A/B/D proceed in parallel and C integrates.

## Parallel Decomposition

### Work Units
| Unit | Files Owned | Shared Files Owned | Depends On |
|------|-------------|--------------------|-----------|
| A — Fargate refine container | `container/Dockerfile`, `container/refine-entrypoint.sh`, `tests/test_refine_entrypoint.*` | — | — |
| B — Lambda handlers | `lambdas/scan/handler.py`, `lambdas/deploy/handler.py`, `lambdas/cleanup/handler.py`, `tests/test_lambda_*` | — | — |
| C — CloudFormation infra | `infra/*.yaml`, `infra/README.md` | — | A, B (names only) |
| D — Docs + GH-Actions removal | `docs/aws-bootstrap.md`, `README.md`, delete `.github/workflows/feedback-loop.yml` + `cleanup-markers.yml` | — | — |

### Shared File Registry
| File | Owner | Others assume |
|------|-------|---------------|
| `scripts/feedback-loop.sh` | Unit A (extracts refine/verify into the container entrypoint; may keep a thin local-dev shim) | unchanged public phases |
| SSM namespace `/cleanup-gmail/` | Unit D (docs) + Unit C (Terraform data sources) | `claude-code-oauth-token` exists; `anthropic-api-key` retired |

### Merge Order
1. Unit A, B, D in parallel (file-disjoint).
2. Unit C (Terraform) integrates, referencing A/B artifact names.
3. Serial final pass: wire SSM param + end-to-end `terraform plan` dry run.

## Implementation Steps
1. **Container (Unit A):** Dockerfile (node + Claude Code + git + gh + python + repo tooling); `refine-entrypoint.sh` adapting the `refine`+`verify` phases of `scripts/feedback-loop.sh`, using `CLAUDE_CODE_OAUTH_TOKEN`, hard-asserting `ANTHROPIC_API_KEY` unset before invoking `claude`. Validation: `shellcheck`, `docker build`, `hadolint`.
2. **Lambdas (Unit B):** three thin Python handlers — `scan` (wraps `feedback-scan` + `corpus-build`), `deploy-apps-script` (wraps `deploy-apps-script`), `cleanup-markers` (wraps `cleanup-markers`) — reading SSM + S3. TDD with pytest + moto (mock SSM/S3) and the existing Gmail fakes.
3. **CloudFormation (Unit C):** ECR, encrypted S3 artifact bucket, three Lambdas, ECS cluster + Fargate task def, Step Functions state machine, EventBridge schedule, IAM roles (least-privilege; refine task role has **no** Gmail/SSM-gmail access), CloudWatch log groups + a failure alarm. Validation: `aws cloudformation validate-template`, `cfn-lint`.
4. **Docs + teardown (Unit D):** rewrite `docs/aws-bootstrap.md` for the new resources + `claude setup-token` flow; update `README.md`; delete all **three** GitHub Actions workflows (`feedback-loop.yml`, `cleanup-markers.yml`, `deploy.yml`); document SSM `anthropic-api-key` retirement + annual `claude-code-oauth-token` rotation.
5. **Serial final pass:** add `/cleanup-gmail/claude-code-oauth-token` to SSM (user action), retire `anthropic-api-key`, deploy the CloudFormation stack, one manual Step Functions execution end-to-end against a seeded test marker.

## Test Strategy
- **Lambdas:** pytest + `moto` for SSM/S3, reuse existing Gmail API fakes from `tests/`. Assert scan emits correct artifacts + `hasMarkers`, and cleanup applies the right add/remove/delete calls.
- **Container entrypoint:** shellcheck + a bats/pytest harness using a stub `claude` on PATH (the existing `test_feedback_loop_script.py` pattern) to assert: refuses to run if `ANTHROPIC_API_KEY` is set, uses `CLAUDE_CODE_OAUTH_TOKEN`, enforces the allow-list, runs pytest, auto-merges only on green.
- **CloudFormation:** `aws cloudformation validate-template` + `cfn-lint` on every template; `create-change-set` dry run before deploy.
- **Regression:** existing `pytest` suite must stay green; no changes to `gmail_cleanup/` classification modules.
- **End-to-end:** one manual Step Functions run with a seeded marker in a test label, verifying the artifact → PR → merge → Gmail-apply chain.

## Progress
- [x] Step 1 — Fargate refine container (Unit A) — completed 2026-06-18 (Dockerfile + refine-entrypoint.sh + Q2 git rm/gitignore/allow-list; shellcheck + docker build + 7 entrypoint tests green)
- [x] Step 2 — Lambda handlers: scan + deploy-apps-script + cleanup-markers (Unit B) — completed 2026-06-18 (lambdas/{common,scan,deploy,cleanup}; pytest+moto, 8 tests green)
- [x] Step 3 — CloudFormation infra (Unit C) — completed 2026-06-18 (infra/feedback-loop.yaml + infra/README.md; cfn-lint clean; aws validate-template pending creds)
- [x] Step 4 — Docs rewrite + removal of all 3 GitHub Actions workflows (Unit D) — completed 2026-06-18 (aws-bootstrap.md rewrite, README section, 3 workflows deleted)
- [ ] Step 5 — Serial final pass: SSM param mint/retire, deploy stack, end-to-end test run (USER-GATED — token mint + AWS deploy)

## Decisions locked
- D4 fully autonomous auto-merge · D3 CloudFormation · D8 migrate `deploy.yml` into the pipeline · retire SSM `anthropic-api-key`.
- **Q1 → YES:** migrate all three workflows (`feedback-loop`, `cleanup-markers`, `deploy.yml`) so improved rules go live in Google Apps Script.
- **Q2 → S3:** `feedback_resolved.json` moves to the encrypted S3 artifact bucket — **nothing email-derived is committed to the repo**. Implications: (a) `git rm` the tracked `feedback_resolved.json` + add to `.gitignore`; (b) remove it from the refine commit allow-list; (c) refine entrypoint uploads it to S3 (Claude still writes it to the worktree, entrypoint ships it + keeps it out of the commit); (d) cleanup-markers Lambda reads it from S3; (e) minimal note in `.github/prompts/feedback-loop.md` that the file is no longer committed (the only sanctioned prompt edit).

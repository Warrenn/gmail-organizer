# scripts/

## `feedback-loop.sh`

The **single source of truth** for the autonomous label-rule refinement loop.
The GitHub Actions workflow (`.github/workflows/feedback-loop.yml`) and local
runs invoke this same script — neither holds a copy of the logic, so what you
test locally is exactly what runs in CI.

GitHub Actions only provides what a shell script genuinely cannot:
OIDC→AWS authentication, `checkout`, runtime provisioning (Python + the
`claude` CLI), and the cross-job `feedback.json` artifact hop. Everything else
— SSM credential pull, scan, Claude refinement, `git`, `gh` — is in the script.

### Credentials are SSM-only — never files

No credential is ever written to disk, locally or in CI. The Gmail token and
Anthropic key are pulled from SSM **into environment variables** that die with
the process (`GMAIL_TOKEN_JSON`, `ANTHROPIC_API_KEY`). The Gmail token
self-contains its client id/secret/refresh token, so it is all the runtime
needs; access-token refresh happens in memory and is not persisted.

**One-time token bootstrap** (also fileless) — run the OAuth grant and stream
the result straight into SSM:

```sh
python -m gmail_cleanup mint-token --client-secret ~/Downloads/client_secret_*.json \
  | aws ssm put-parameter --name /cleanup-gmail/gmail-token-json \
      --type SecureString --value file:///dev/stdin
```

### Subcommands

| Command | What it does | Creds it pulls |
|---------|--------------|----------------|
| `scan`      | Pull Gmail creds, run `feedback-scan`, count `+X`/`-X` markers, scrub creds | Gmail only |
| `refine`    | Pull Anthropic key, create `loop/feedback-<UTC>` branch, run Claude headless against `.github/prompts/feedback-loop.md`, push, open/update PR | Anthropic only |
| `verify`    | Reject any diff outside the file allow-list (escape → close PR + file issue), optionally auto-merge | none |
| `heartbeat` | File a `loop-broken` issue for a failed run | none |
| `all`       | `scan`; if markers found, `refine` then `verify` (the local entrypoint) | as above |

The phase split mirrors CI's three jobs, which exist to keep **credential
isolation**: the `refine`/Claude step never shares an environment that holds
Gmail credentials or a push token. Even in local `all` mode, `scan` scrubs the
Gmail creds before `refine` runs.

### Running locally

```bash
# 1. Authenticate to AWS (the only thing CI does that you must replicate)
aws sso login            # or export a profile / static creds

# 2. Make sure prerequisites are present (see below), then:
PYTHON=./.venv/bin/python ./scripts/feedback-loop.sh all
```

By default `DRY_RUN=true` locally, so the push, `gh pr create`/`merge`, and
issue-create steps are **logged, not executed** — safe to run repeatedly.
Drop `DRY_RUN=false` only when you intend to create a real branch/PR.

**Prerequisites for a local run:**

- `aws` CLI authenticated with access to the `/cleanup-gmail/*` parameters
- `gh` CLI authenticated (used for PR/issue operations; skipped under dry-run)
- The `claude` CLI installed (`npm install -g @anthropic-ai/claude-code`)
- Python with project deps — pass `PYTHON=./.venv/bin/python` (macOS often has
  no bare `python`); CI uses `python` from `setup-python`
- `git`

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DRY_RUN` | `true` | When `true`, side effects are logged not run. CI sets `false`. |
| `PYTHON` | `python` | Interpreter to use. Set `./.venv/bin/python` locally on macOS. |
| `SSM_PREFIX` | `/cleanup-gmail` | Parameter Store namespace for creds. |
| `FEEDBACK_FILE` | `feedback.json` | Scan output / refine input. |
| `RESOLVED_FILE` | `feedback_resolved.json` | Resolved-markers manifest (read by `cleanup-markers`). |
| `PROMPT_FILE` | `.github/prompts/feedback-loop.md` | Prompt file the Claude refine step runs with. |
| `BASE_REF` | `origin/main` | Base for the `verify` allow-list diff. |
| `LOOP_AUTO_MERGE` | `false` | `true` → `verify` auto-merges the PR. |
| `BRANCH_NAME` | _(computed)_ | Override the refinement branch name. |
| `PR_NUMBER` | _(empty)_ | PR for `verify`/escape handling. |
| `GH_TOKEN` | _(empty)_ | If set, push authenticates with it; else local git auth. |
| `RUN_URL`, `SCAN_RESULT`, `REFINE_RESULT`, `VERIFY_RESULT` | | Heartbeat issue body. |

`$GITHUB_OUTPUT` and `$GITHUB_ACTIONS` are honored when present (step outputs,
secret masking) and silently ignored when absent — that's how the same script
works in both places.

### Tests

`tests/test_feedback_loop_script.py` drives the script with stub
`aws`/`gh`/`claude`/`python` executables and a throwaway git repo, so the loop's
behaviour is verified with no real credentials:

```bash
./.venv/bin/python -m pytest tests/test_feedback_loop_script.py -q
shellcheck scripts/feedback-loop.sh
```

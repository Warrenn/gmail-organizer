# STRATEGY — Self-refining label rules via Gmail `+`/`-` markers

## Goal

Build an autonomous feedback loop where the user marks misclassified mail
in Gmail with `+label` (missed label) or `-label` (wrong label), and a
scheduled GitHub Actions workflow has Claude refine the project's rules
to make the future classifier handle those threads correctly — without
regressing existing labels. Apps Script then redeploys via `clasp push`.

## Requirements

1. **Signal mechanism.** A user-applied Gmail label whose name begins with
   `+` or `-` is a training signal:
   - `+X` on thread T → introduce or refine rules so future mail like T
     receives label `x`. If `x` is new to the convention set, create it.
   - `-X` on thread T → narrow existing rules so future mail like T does
     NOT receive `x`. Existing threads currently labeled `x` must
     remain `x`.

2. **Discriminator sophistication.** Refinements may be sender-based
   (rules in `label_queries.json`) OR content/subject-based (rules in
   `classify_rules.py`). Claude chooses the right discriminator per case.

3. **Regression safety.** A fixture corpus (~300 stratified threads
   with their current labels) is the guardrail. Any rule change must
   produce identical classifier output for every corpus entry except
   the targeted threads. CI fails the PR on regression.

4. **Source-of-truth refactor.** `label_queries.json` (already exists)
   and a new structured rule spec for content classification become the
   single source of truth. `Rules.gs` and `Classifier.gs` are
   **generated artifacts** — never edited by hand.

5. **Runtime placement.** Fully autonomous, off the user's machine.
   GitHub Actions cron, every 6 hours. Secrets live in AWS Parameter
   Store; the Action uses GitHub OIDC to assume an AWS role and pull
   them at run time. **Credentials are split across workflows by
   blast radius** (see "Containment architecture" below) so Claude's
   session never holds Gmail or Apps Script credentials.

6. **Trust ramp.** Phase 1 launches in **soft mode** — Claude opens a
   PR, the user merges manually. After N stable cycles, a single
   workflow-config flip enables `--auto-merge`.

7. **Ambiguous cases.** If Claude can't find a confident refinement,
   the PR is opened with a `needs-human` label and a comment summarizing
   what was tried. No auto-merge. User picks up the branch in an
   interactive `claude` session locally.

8. **Marker cleanup.** After PR merge + deploy, a separate workflow job
   removes the `+X`/`-X` markers from the source threads and applies
   the resolved label (`x` for `+`, removes `x` for `-`).

9. **Containment.** Claude's session in the feedback-loop workflow is
   intentionally constrained to source-rule edits only — see
   "Containment architecture" below.

## Containment architecture

Three separate workflows, each scoped to the smallest credential it
needs. Claude only runs in one of them, and that one has no Gmail or
Apps Script credentials.

| Workflow                  | Trigger                       | Credentials in scope                              | Runs Claude? |
|---------------------------|-------------------------------|---------------------------------------------------|--------------|
| `feedback-loop.yml`       | cron every 6h                 | Anthropic API key only                            | Yes          |
| `deploy.yml`              | push to main                  | clasp `.clasprc.json`                             | No           |
| `cleanup-markers.yml`     | workflow_run: deploy success  | Gmail OAuth (`gmail.modify` for label-on-thread)  | No           |

`feedback-loop.yml` runs in two jobs:

1. **`scan` job** — has Gmail OAuth (read-only Gmail label list + thread
   metadata), runs `python -m gmail_cleanup feedback-scan`, writes
   `feedback.json` as an artifact, then the job ends. The token is gone.
2. **`refine` job** — depends on `scan`. Downloads `feedback.json`,
   invokes `claude-code-action` with the Anthropic API key. **No
   Gmail token, no clasp token in this job.** Claude's runtime
   authority is limited to:
   - Reading the repo + the `feedback.json` artifact
   - Editing source files in the explicit allow-list
   - Running `python -m gmail_cleanup generate-apps-script`,
     `python -m pytest tests/`, `git`, `gh`
   - Nothing network-facing beyond what `git`/`gh`/`pip` need
3. **`verify` job** — depends on `refine`. Runs `git diff --name-only
   main...HEAD` and rejects any files outside the allow-list. If
   Claude touched anything off-list, the PR is force-closed and an
   issue is filed.

The deploy and cleanup workflows are pre-baked scripts — no LLM
involvement. Their behavior is fixed at workflow-merge time.

This means even if Claude's prompt got compromised (e.g., a malicious
email subject smuggled in instructions via `feedback.json`), the worst
it could do is corrupt the rule sources. It cannot delete mail,
exfiltrate the mailbox, or push to Apps Script directly — those
credentials are physically absent from its job.

## Approach

The work splits into two big phases that can ship as separate PRs.

### Phase 0 — Foundation (must complete before Phase 1)

- **Refactor classifier to data-driven spec.** `classify_rules.py`
  currently uses raw `if from_has(...)` conditionals. Convert to a
  YAML rule spec interpreted by a small Python evaluator. The same
  spec generates `Classifier.gs`. Single source of truth for both
  Python (dev/tests) and Apps Script (production). Spec file
  (`gmail_cleanup/rules.yaml`) carries a top-level `version: 1`
  field; spec migrations are separate, dedicated PRs.
- **Rule semantics.** Each rule has an explicit `additive: bool` flag.
  `additive: false` (default) means first-match-wins (the rule
  terminates classification when matched). `additive: true` means
  the rule's labels layer on top of any prior match without
  terminating. This is the only way to express cases like "Stripe
  payouts get `[finance, stripe, receipts]`" where the sender rule
  produces `[finance, stripe]` and a layered rule adds `[receipts]`.
- **Generator CLI.** `python -m gmail_cleanup generate-apps-script`
  emits `apps-script/Rules.gs` (from `label_queries.json`) and
  `apps-script/Classifier.gs` (from the new content-rule spec). The
  emitted files include a "DO NOT EDIT" banner pointing to the source.
- **Regression corpus.** `python -m gmail_cleanup corpus-build` samples
  ~300 threads stratified across all current user labels, writes
  `tests/corpus.json` with `{thread_id, sender, subject, snippet,
  current_labels}`. Pytest asserts the Python interpreter produces
  identical labels for every corpus entry.
- **Property tests on top of the corpus** to catch creative bad rules
  the corpus can't:
  - No rule may match >30% of any single sender's mail (proxy for
    "rule is too broad")
  - No regex/wildcard equivalent to `.*` allowed
  - No rule's label list may shrink an existing convention label's
    population by >5% when run over the full mailbox sample

### Phase 1 — The loop

- **`feedback-scan` CLI.** Lists labels matching `^[+-]`, fetches
  threads under each, dumps `feedback.json` with `{markers, threads,
  sample_metadata}`.
- **AWS Parameter Store provisioning.** SecureString params under
  `/cleanup-gmail/`:
  - `anthropic-api-key`
  - `gmail-credentials-json` (contents of `credentials.json`)
  - `gmail-token-json` (contents of `token.json`)
  - `clasp-rc-json` (contents of `~/.clasprc.json`)
- **AWS IAM OIDC role.** Trust policy allows the
  `Warrenn/gmail-organizer` repo's Action to assume it; permission
  policy grants `ssm:GetParameter` on `/cleanup-gmail/*` only.
- **`.github/workflows/feedback-loop.yml`** (cron every 6h),
  three jobs per the containment architecture:
  1. **`scan`** — AWS OIDC + Gmail OAuth → run `feedback-scan` →
     upload `feedback.json` artifact → token discarded with job end.
  2. **`refine`** (`needs: scan`) — AWS OIDC + Anthropic API key only.
     Downloads `feedback.json`. Invokes `claude-code-action` with the
     `.github/prompts/feedback-loop.md` template. On success, Claude
     commits, pushes branch, opens PR with `loop-autonomous` label.
     On low confidence per marker, adds `needs-human` label and
     `## Unresolved markers` section.
  3. **`verify`** (`needs: refine`) — pure `gh` + `git`. Diffs the
     PR against the allow-list (rule sources + corpus + generated GS
     files). Any off-list file change → PR closed, issue filed
     `loop-escape`, run fails.
  4. **Auto-merge gate** — the `verify` job's final step reads the
     repository variable `vars.LOOP_AUTO_MERGE`. When false (soft
     launch default), the job ends after passing the diff check.
     When true, the job runs `gh pr merge --auto --squash`. Switching
     modes is a one-toggle change in the GitHub repo Settings →
     Variables UI; no workflow edit needed.
- **`.github/workflows/deploy.yml`** (trigger: push to main):
  1. Configure AWS via OIDC, pull `clasp-rc-json`
  2. `clasp push` from `apps-script/`
- **`.github/workflows/cleanup-markers.yml`** (trigger: workflow_run
  of deploy.yml succeeded):
  1. Configure AWS via OIDC, pull Gmail token
  2. For every `+X`/`-X` label from the just-resolved PR:
     - Add label `x` to the source threads (if `+`)
     - Remove label `x` from the source threads (if `-`)
     - Remove the `+X`/`-X` label from threads
     - If `+X` was the marker, delete the `+X` label entirely
- **Heartbeat / alerting.** If the cron workflow fails for any
  reason (auth expired, Claude API error, AWS auth fail),
  notify_on_failure step opens a GitHub issue tagged `loop-broken`.

### Parallelism assessment

Single agent. Phase 0 layers are tightly sequenced (spec → interpreter →
generator → tests; corpus depends on a working interpreter). Phase 1
components are interrelated (the workflow exercises the spec from Phase 0,
the cleanup workflow consumes the marker state set up by feedback-scan).
File-disjoint decomposition possible in theory (e.g., codegen vs.
corpus vs. AWS setup) but the dependency graph makes serial work
cleaner and the user has expressed a preference for sequential
walkthrough.

## Numbered implementation steps

### Phase 0 — Foundation

1. **Design the content-rule spec.** Document the rule schema
   (operators: `from_any`, `from_not_contains`, `subject_contains_any`,
   `text_contains_any`, `snippet_contains_any`, etc.) in
   `docs/rule-spec.md`. Decide ordering semantics (first-match-wins +
   additive subject rules).
2. **Write tests for the Python rule interpreter** — table-driven
   tests with hand-crafted spec snippets, assert classifier output.
3. **Implement the Python rule interpreter** that consumes the spec
   and produces label arrays.
4. **Port `classify_rules.py` logic to the new spec.** Replace
   conditional code with `rules.yaml` (or `.json`). Existing
   `classify_rules.py` becomes a thin wrapper around the interpreter.
5. **Write tests for the Apps Script generator** — for a known spec,
   assert the generated `Classifier.gs` contains expected patterns
   (e.g., specific function calls, label-array references).
6. **Implement the generator** (`python -m gmail_cleanup
   generate-apps-script`). Emits `Rules.gs` from `label_queries.json`
   and `Classifier.gs` from `rules.yaml`. Adds "DO NOT EDIT" banner.
7. **Build the regression corpus.** `python -m gmail_cleanup
   corpus-build` samples threads stratified per label, writes
   `tests/corpus.json`. Add gitignore for sensitive content if needed.
8. **Add corpus regression test** — `tests/test_corpus.py` iterates
   the corpus, classifies each entry via the new interpreter, asserts
   labels match. CI runs this on every PR.
9. **Add property tests** for rule sanity (matches-too-many-senders,
   `.*`-equivalent regex, shrink-blast guard).
10. **Verify generated GS files match current `Classifier.gs` /
    `Rules.gs` behavior** by spot-checking a few cases. Replace the
    hand-written versions with generated ones in a single commit.

### Phase 1 — The loop

11. **Write tests for `feedback-scan`** (mocked Gmail service:
    labels with `^[+-]` prefixes, threads under them).
12. **Implement `feedback-scan` CLI** and add to `__main__.py`.
13. **Provision AWS** — IAM identity provider for GitHub OIDC, role
    with trust policy + SSM permissions, populate Parameter Store
    params. Document the bootstrap in `docs/aws-bootstrap.md`.
14. **Write `.github/workflows/feedback-loop.yml`** in soft mode.
15. **Write the Claude prompt template** that the Action passes to
    `claude-code-action`. Versioned in the repo so it can be iterated.
16. **Write `.github/workflows/deploy.yml`** for `clasp push` on
    main merges.
17. **Write `.github/workflows/cleanup-markers.yml`** for post-deploy
    marker removal.
18. **Add heartbeat / failure-issue creation step.**
19. **End-to-end dry-run.** Manually add a single `+test-label`
    marker on a thread; let the workflow fire; verify PR opens with
    correct refinement; merge manually; verify deploy + cleanup
    both run; check the marker is gone and `test-label` is applied.
20. **Soft launch.** Run for ~2 weeks of real signals.
21. **Switch to auto-merge.** One-line edit to `feedback-loop.yml`.

## Test strategy

- **Python unit tests** (pytest) for interpreter, generator, feedback-scan,
  property tests. Following the existing project pattern.
- **Apps Script self-tests** — extend `_runSelfTests()` to cover any
  new generated logic in `Classifier.gs`.
- **Corpus regression** — `tests/test_corpus.py` is the keystone.
  Runs on every PR; blocks merges that change existing labels.
- **End-to-end dry-run** at step 19 — the only test of the full loop
  against real Gmail + real Apps Script + real AWS.

## Progress

### Phase 0 — Foundation
- [x] Step 1 — design content-rule spec (docs/rule-spec.md) — completed 2026-05-27
- [x] Step 2 — tests for Python rule interpreter — completed 2026-05-27
- [x] Step 3 — implement Python rule interpreter — completed 2026-05-27
- [x] Step 4 — port classify_rules.py to spec; thin wrapper — completed 2026-05-27
- [x] Step 5 — tests for Apps Script generator — completed 2026-05-27
- [x] Step 6 — implement generator (`generate-apps-script` CLI) — completed 2026-05-27
- [x] Step 7 — build regression corpus (`corpus-build` CLI) — completed 2026-05-27
- [x] Step 8 — corpus regression pytest — completed 2026-05-27
- [x] Step 9 — property tests — completed 2026-05-27
- [x] Step 10 — verify + replace hand-written GS with generated — completed 2026-05-27

### Phase 1 — The loop
- [x] Step 11 — tests for feedback-scan — completed 2026-05-27
- [x] Step 12 — implement feedback-scan CLI — completed 2026-05-27
- [x] Step 13 — AWS bootstrap docs (docs/aws-bootstrap.md) — completed 2026-05-27 (user-side AWS console work still needed)
- [x] Step 14 — feedback-loop.yml (soft mode) — completed 2026-05-27
- [x] Step 15 — Claude prompt template (extended with feedback_resolved.json requirement) — completed 2026-05-27
- [x] Step 16 — deploy.yml — completed 2026-05-27
- [x] Step 17 — cleanup-markers.yml (+ cleanup.py module + cleanup-markers CLI) — completed 2026-05-27
- [x] Step 18 — heartbeat / failure-issue (embedded in each workflow) — completed 2026-05-27
- [ ] Step 19 — end-to-end dry-run with a real `+test-label` (REQUIRES USER — needs AWS bootstrap done first per docs/aws-bootstrap.md)
- [ ] Step 20 — soft launch ~2 weeks
- [ ] Step 21 — flip `vars.LOOP_AUTO_MERGE` to `true` once trust is established

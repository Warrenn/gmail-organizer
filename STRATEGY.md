# STRATEGY — Rename labels to a convention

## Goal

Add a `rename-labels` CLI command to `gmail_cleanup` that normalizes Gmail
label names to a strict convention, handling collisions as merges.

## Requirements

1. **Normalization rules** (applied in order):
   1. If the label starts with `_`, leave it untouched.
   2. If the label is in the excluded set (Outlook sync folders) or in
      the user-supplied `--exclude` list, leave it untouched.
   3. Trim leading/trailing whitespace.
   4. Lowercase.
   5. Replace internal whitespace runs with a single `-` (the multi-word
      rule, e.g. `Mac in cloud` → `mac-in-cloud`).
   6. Remove any character not in `[a-z0-9_-]`.

2. **Default exclusions (Outlook sync folders):**
   `Notes`, `Deleted Items`, `Sent Items`, `Junk E-mail`, `Sync Issues`,
   `Conflicts`, `Local Failures`, `Server Failures`. Hardcoded in
   `normalize.py` as a module constant. Additional exclusions can be added
   via `--exclude NAME` (repeatable) on the CLI.

3. **Collision = merge.** If a label's normalized name matches the name of
   another existing label, the source label is merged into the target:
   re-label every thread under the source onto the target, then delete the
   source label. (Same surface area for general collisions and the known
   `[Notion]` → `Notion` case.)

4. **Dry-run by default.** Running without `--apply` prints the diff
   (renames, merges, skipped) and exits without modifying Gmail. `--apply`
   executes the plan.

5. **Idempotent.** Running `--apply` twice is safe: already-conforming
   labels are no-ops; merged labels no longer exist on the second pass.

## Approach

The work decomposes into:

- **Pure normalization layer** (`normalize.py`): exclusion check + name
  transform. Pure functions, fully unit-testable, no Gmail API surface.
- **Planning layer** (`rename.py` — `plan_renames`): given the live label
  list, produce a structured plan (`renames`, `merges`, `skipped`).
  Pure function, fully unit-testable.
- **Execution layer** (`rename.py` — `apply_plan`): given a plan and a
  Gmail service, perform the API calls in order. Mocked in tests, real
  call once at the end.
- **CLI layer** (`__main__.py`): subcommand wiring, dry-run print, prompt
  for confirmation before mutations.

**Key decision — separate "skip" from "normalize":** `normalize_label`
is a pure transform that ignores exclusion rules; `should_skip` checks
exclusions. Caller composes them. This keeps each function single-purpose
and easy to test.

**Key decision — implement merge generically.** The `[Notion]` case is
not special-cased; the planner detects any normalized-name collision with
an existing label and emits a merge entry. Future renames are handled
without code changes.

**Parallelism assessment:** Single agent. Scope is ~4 small files
(`normalize.py`, `rename.py`, additions to `labels.py`, additions to
`__main__.py`) that are tightly coupled — each layer depends on the one
below. No useful file-disjoint decomposition.

## Numbered implementation steps

1. **Write tests for `normalize.py`** — cover every rule and every edge
   case from the agreed diff (underscore, Outlook excludes, all-lowercase
   pass-through, mixed-case, internal whitespace, brackets/periods,
   double normalization is a no-op).
2. **Implement `normalize.py`** — `EXCLUDED_LABELS` constant,
   `should_skip(name, extra=...)`, `normalize_label(name)`.
3. **Write tests for `labels.py` additions** — `update_label`,
   `delete_label`, both mocked.
4. **Implement `update_label` and `delete_label`** in `labels.py`.
5. **Write tests for `rename.plan_renames`** — given a fake label list,
   produce expected `{renames, merges, skipped}` output. Covers:
   - already-conforming label → skipped
   - mixed-case label → rename
   - multi-word → rename with hyphen
   - underscore-prefixed → skipped
   - Outlook label → skipped
   - extra exclude → skipped
   - `[Notion]` collides with `Notion` → merge
6. **Implement `rename.plan_renames`.**
7. **Write tests for `rename.apply_plan`** — mocked service. Verifies:
   - each rename calls `update_label` with the right id+name
   - each merge calls `search_threads`, `label_thread` for each, then
     `delete_label`
   - dry-run skipped entries are no-ops
   - errors are collected per item, not fatal
8. **Implement `rename.apply_plan`.**
9. **Wire CLI subcommand** in `__main__.py`: `cmd_rename_labels`,
   subparser with `--apply`, `--exclude` (repeatable), `--yes`.
10. **Run the full test suite** — `python -m pytest tests/` — and ensure
    no existing tests broke.
11. **Dry-run against real Gmail** — `python -m gmail_cleanup
    rename-labels` — review the printed diff; confirm it matches the
    agreed plan (92 renames + 1 merge of `[Notion]` into `Notion`).
12. **Apply against real Gmail** — `python -m gmail_cleanup
    rename-labels --apply --yes` — execute.
13. **Verify** — re-list labels and confirm the diff is what we expected;
    no `[Notion]`; everything lowercased and hyphenated.

## Test strategy

- **Unit tests** with `pytest`, following the existing pattern in
  `tests/test_labels.py`-style modules. Mock the Gmail service with a
  hand-rolled fake (matches existing `tests/test_apply.py` style — no
  `unittest.mock` magic needed).
- **Coverage targets:**
  - `normalize.py` — exhaustive: every rule, every edge case.
  - `rename.plan_renames` — every classification (skip / rename / merge),
    incl. the collision case.
  - `rename.apply_plan` — every action path, plus error collection.
- **End-to-end validation** is the dry-run + apply pass at steps 11–13,
  against the real account.

## Progress

- [x] Step 1 — tests for normalize.py — completed 2026-05-27
- [x] Step 2 — implement normalize.py — completed 2026-05-27
- [x] Step 3 — tests for labels.update_label, labels.delete_label — completed 2026-05-27
- [x] Step 4 — implement labels.update_label, labels.delete_label — completed 2026-05-27
- [x] Step 5 — tests for rename.plan_renames — completed 2026-05-27
- [x] Step 6 — implement rename.plan_renames — completed 2026-05-27
- [x] Step 7 — tests for rename.apply_plan — completed 2026-05-27
- [x] Step 8 — implement rename.apply_plan — completed 2026-05-27
- [x] Step 9 — wire CLI subcommand — completed 2026-05-27
- [x] Step 10 — full test suite passes (136 tests, 0 failures) — completed 2026-05-27
- [x] Step 11 — dry-run against real Gmail; verify diff (97 renames + 1 merge) — completed 2026-05-27
- [x] Step 12 — `--apply` against real Gmail (97 renames + 1 merge, 0 errors) — completed 2026-05-27
- [x] Step 13 — verify post-state via list_labels (idempotent rerun, all targets correct) — completed 2026-05-27

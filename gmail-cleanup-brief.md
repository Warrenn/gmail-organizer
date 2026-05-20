# Gmail organization — handoff brief for Claude Code

Paste this entire file into a fresh Claude Code session on the Mac. Run it from a working directory you're comfortable with (e.g. `~/gmail-cleanup`). The Gmail account to operate on is **warrenne@gmail.com**.

---

## Goal

A four-phase, human-in-the-loop cleanup of the user's entire Gmail mailbox:

1. **Discover** — sample broadly across the entire mailbox (read + unread, all time, including archived) and propose a label tree.
2. **Refine** — show the proposed labels to the user, accept edits, lock the final list.
3. **Apply** — label all messages in the mailbox according to the agreed tree, in batches.
4. **Delete-by-label** — for labels the user marks for cleanup, move matching messages to Trash (NOT permanent delete) with per-batch confirmation.

## User's chosen settings (do not re-ask)

- **Scope:** entire mailbox, all time, read and unread, including archived.
- **Label style:** hybrid — top-level topic categories (Finance, Travel, Shopping, Newsletters, Personal, Work, Receipts, Subscriptions, etc.) with sub-labels for high-volume senders (e.g. `Finance/Chase`, `Newsletters/Substack`). Gmail represents nested labels with `/` in the name.
- **Sampling strategy:** representative sample of ~300–500 threads across senders and time slices. Not every message.
- **Delete safety:** per-batch confirmation. Show the user a count and a sample of subjects before each delete batch; wait for explicit "go".
- **Delete mode:** **Move to Trash, not permanent delete.** Use `users.messages.trash` or `batchModify` to add `TRASH`. Do **not** use `batchDelete`. This means you only need the `gmail.modify` + `gmail.labels` scopes; do NOT request `https://mail.google.com/`.

## Tech stack

Use Python with `google-api-python-client` and `google-auth-oauthlib`. Standard installed-app OAuth flow — first run opens a browser, user grants consent, cache the refresh token in `token.json` in the working directory. Do NOT commit `credentials.json` or `token.json` anywhere.

Required scopes:
- `https://www.googleapis.com/auth/gmail.modify`
- `https://www.googleapis.com/auth/gmail.labels`

If the user doesn't yet have a Google Cloud OAuth client, walk them through creating one:
1. https://console.cloud.google.com/ → new project (or reuse one)
2. Enable Gmail API
3. APIs & Services → OAuth consent screen → External, add the user's own email as a test user
4. Credentials → Create Credentials → OAuth client ID → Desktop app → download `credentials.json` to the working directory

## Phase-by-phase execution

### Phase 1 — Discover

1. Call `users.labels.list` to inventory existing labels — surface them to the user so we don't duplicate.
2. Build a representative sample:
   - Use `users.messages.list` with `q=""` plus date slices: e.g. one batch per year going back as far as the mailbox goes (`after:2015/01/01 before:2016/01/01`, etc.). Cap the per-slice pull (e.g. 100 messages per year).
   - Separately, identify top senders: hit `users.messages.list` with `in:anywhere` plus a couple of broad time windows, page through enough message IDs (a few thousand) and tally `From:` headers. You can fetch headers cheaply via `users.messages.get` with `format=metadata&metadataHeaders=From,Subject,Date,List-Unsubscribe`.
   - Aim for ~300–500 unique threads in the final sample, weighted to cover both volume (top senders) and breadth (long tail).
3. From the sample, propose a hybrid label tree. Group by topical category; under each, list the top senders that justify a sub-label.
4. Present the proposed tree to the user as a clean nested list. Do NOT create labels yet.

### Phase 2 — Refine

1. Show the proposed tree.
2. Take edits — adds, removes, renames, merges.
3. Confirm the final tree explicitly with the user ("Locking this in — yes/no?").
4. Only after confirmation: call `users.labels.create` for any labels that don't already exist. Preserve `messageListVisibility=show`, `labelListVisibility=labelShow` so they appear in the UI.

### Phase 3 — Apply labels

For each leaf label in the agreed tree, define a Gmail search query that selects matching messages. Examples:

- `Finance/Chase` → `from:(chase.com OR chasebank.com)`
- `Newsletters/Substack` → `from:substack.com OR list:(*.substack.com)`
- `Receipts` → `subject:(receipt OR invoice OR "order confirmation") -from:noreply@example.com`

Then for each label:

1. `users.messages.list` with the query, paginating through all message IDs.
2. Chunk IDs into batches of 1,000.
3. Call `users.messages.batchModify` with `addLabelIds=[labelId]` per batch. Quota cost is 50 units per call; per-user limit is 6,000/min, so pace yourself at <120 batchModify/min (well under).
4. Log each batch (label name, message count, time).
5. After each label finishes, print a one-line summary to the user.

Edge cases:
- A message can have multiple labels. That's fine and desirable.
- For messages that match no defined query, leave them unlabeled. Optionally surface a count at the end and ask if the user wants to define a catch-all rule.

### Phase 4 — Delete-by-label (move to Trash)

1. Ask the user which labels they want cleared.
2. For each chosen label:
   a. `users.messages.list` with `q="label:<labelName>"`.
   b. Show the user the total count and a random sample of ~10 subjects + senders.
   c. Wait for explicit "go".
   d. Chunk IDs into 1,000s. Use `users.messages.batchModify` with `addLabelIds=["TRASH"]` (this is move-to-Trash, reversible for 30 days). Do NOT call `batchDelete`.
   e. Log batch counts and report total moved to Trash.
3. Remind the user: Trash auto-empties after 30 days, or they can empty it manually in Gmail web UI.

## Error handling

- Backoff on `429` and `5xx` with exponential delay (1s → 2s → 4s → 8s, max 5 retries).
- If quota is exceeded for the day, save progress (a JSON file with `{label: completed_message_ids}`) and tell the user to resume tomorrow.

## Deliverables back to the user

- A `gmail-cleanup-report.md` in the working directory with: existing labels, sample size, proposed tree, final tree, per-label counts labeled, per-label counts trashed, timestamps.
- The `token.json` file (kept locally — do NOT share, do NOT commit).

## Don'ts

- Do not use `batchDelete` (permanent). User explicitly chose Trash.
- Do not request `https://mail.google.com/` scope.
- Do not silently create labels in Phase 1.
- Do not skip the per-batch confirmation in Phase 4.

---

## Quick-start prompt for Claude Code

> "Read `gmail-cleanup-brief.md` in this directory and execute it. Stop and ask me before any step that creates labels, applies labels in bulk, or moves messages to Trash. Walk me through OAuth setup if `credentials.json` isn't here."

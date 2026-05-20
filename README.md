# gmail-organizer

Automatically label new Gmail messages on a schedule. Built around a hybrid
approach: deterministic sender-based rules plus a fallback content classifier
for senders the rules don't recognize.

There are **two implementations** in this repo:

- **`apps-script/`** — **production**. Google Apps Script that runs hourly
  inside Google's infrastructure, applies the rules in `Rules.gs` plus the
  fallback classifier in `Classifier.gs`. No tokens, no servers, no laptop
  dependency. **Use this.**
- **`gmail_cleanup/`** — Python CLI used for the initial bulk-labeling and
  experimentation. Useful for re-running discovery, one-off classification
  passes, or testing rule changes locally. Requires OAuth and runs only as
  long as your refresh token is valid.

---

## How it works

1. `Rules.gs` defines ~80 sender-based rules: each maps a Gmail search query
   (e.g. `from:fnb.co.za`) to one or more labels (e.g. `['Finance', 'FNB']`).
2. `Code.gs > organizeInbox()` searches Gmail every hour for threads that
   have no user labels yet, and applies matching rules.
3. `Classifier.gs > classifyThread_()` is a fallback for threads no rule
   matched. It inspects the sender, subject, and body snippet and assigns
   1-3 labels based on heuristics ported from `classify_rules.py`.
4. Subject-pattern rules (`Receipts`, `Notifications`) layer additively over
   sender-based labels — a receipt from JetBrains gets both `Receipts` and
   `Jetbrains`.

The label tree is **flat** (no nested labels). What used to be
`Newsletters/Medium` is now two separate flat labels (`Newsletters` and
`medium`), both applied to each matching message.

---

## Apps Script deployment

### One-time setup

1. **Enable the Apps Script API** for your Google account:
   https://script.google.com/home/usersettings → toggle **on**.
2. **Install `clasp`** (the Apps Script CLI):
   ```sh
   npm install -g @google/clasp
   ```
3. **Log in to clasp**:
   ```sh
   clasp login
   ```
4. **Create the Apps Script project**:
   ```sh
   cd apps-script
   clasp create --type standalone --title "Gmail Organizer"
   clasp push
   ```
5. **Install the hourly trigger**: open the script at https://script.google.com,
   select function `setupTriggers`, and click **Run**. Grant the OAuth scopes
   it asks for (`gmail.modify`, `gmail.labels`, `script.scriptapp`).
6. (Optional) Run `organizeInbox` once manually to smoke-test.

### Day-to-day

The script runs every hour automatically. To see what it's doing, open
the script editor → **Executions** tab.

### To stop the automation

Run `removeTriggers()` from the script editor, or delete the trigger via
**Triggers** in the left side-nav.

### To update rules

Edit `apps-script/Rules.gs`, then:
```sh
cd apps-script
clasp push
```

---

## Python CLI (reference / dev tool)

The Python package supports the original full lifecycle:

- `python -m gmail_cleanup discover` — sample the mailbox, build a sender
  histogram.
- `python -m gmail_cleanup propose` — synthesize a candidate label tree.
- `python -m gmail_cleanup create-labels` — create new labels.
- `python -m gmail_cleanup apply` — bulk-apply labels via `batchModify`.
- `python -m gmail_cleanup flatten` — convert nested labels to flat.
- `python -m gmail_cleanup classify-export` — export unlabeled messages
  with metadata + snippets for AI classification.
- `python -m gmail_cleanup classify-apply` — apply a pre-built
  classification.json.

### Setup

1. Create a Google Cloud OAuth client (Desktop type), download
   `credentials.json` into the project root.
2. `python -m venv .venv && source .venv/bin/activate`
3. `pip install google-api-python-client google-auth-oauthlib google-auth-httplib2 pytest`
4. `python -m gmail_cleanup discover --account you@example.com` (first run
   opens browser for OAuth consent).

### Test

```sh
python -m pytest tests/
```

---

## Repo layout

```
.
├── README.md                       # this file
├── apps-script/                    # production Apps Script (deployed via clasp)
│   ├── appsscript.json             # manifest + OAuth scopes
│   ├── Code.gs                     # organizeInbox() + setupTriggers()
│   ├── Rules.gs                    # ~80 sender → labels rules
│   └── Classifier.gs               # fallback content classifier
├── gmail_cleanup/                  # Python package (dev / historical)
│   ├── auth.py                     # OAuth flow
│   ├── sampling.py                 # per-year date-slice query builder
│   ├── discover.py                 # Phase 1 — sample + tally
│   ├── propose.py                  # Phase 2 — synthesize tree
│   ├── labels.py                   # users.labels.create wrapper
│   ├── apply.py                    # Phase 3 — batchModify orchestrator
│   ├── flatten.py                  # nested → flat label restructure
│   ├── classify.py                 # export-for-AI + apply-classification
│   └── __main__.py                 # CLI
├── tests/                          # pytest tests (77 tests)
├── classify_rules.py               # one-shot rule-based classifier
├── label_queries.json              # source of truth for sender rules
├── final_tree.json                 # original locked label tree
├── pyproject.toml
├── gmail-cleanup-brief.md          # original project brief
└── gmail-cleanup-report.md         # full session report
```

Files **not** tracked (see `.gitignore`):
- `credentials.json`, `token.json` — OAuth secrets
- `unlabeled_messages.json`, `classification.json`, `discover*.json`,
  `progress.json`, etc. — personal mailbox data dumps

---

## What this won't do

- **Sort old mail you've already labeled.** Both implementations operate
  only on threads with no user labels (`-has:userlabels`). Threads you've
  manually labeled are untouched.
- **Move to Trash.** Labels are additive and reversible. The original brief
  excluded Phase 4 (trash). To clean up, label messages, review them in
  Gmail, and trash manually.
- **Handle multiple accounts.** The Apps Script runs for the Google account
  it was created under. For other accounts, deploy a separate copy.

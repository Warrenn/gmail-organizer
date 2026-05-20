# Gmail Cleanup — Phases 1–3 Report

**Account:** `warrenn@busyweb.co.za` (also receives mail for `warrenne@gmail.com` — see Mailbox composition below)
**Session date:** 2026-05-19
**Phases completed:** 1 (Discover) + 2 (Refine / Label-tree lock-in) + 3 (Apply labels at scale)
**Phases deferred:** 4 (trash) — out of scope.

## Mailbox composition

The busyweb.co.za account is the consolidated store for both addresses:

| Recipient | Message count |
|---|---:|
| Addressed to `warrenne@gmail.com` | 14,641 |
| Addressed to `warrenn@busyweb.co.za` | 2,259 |
| Total messages in mailbox | **14,943** |

The label tree applies to all of it regardless of which address received the mail (queries are sender-based, not recipient-based).

---

## Phase 1 — Discover

| Metric | Value |
|---|---|
| Mailbox year range (detected) | 2013–2026 |
| Total threads sampled | 941 |
| Unique senders identified | 238 |
| Existing user-created labels | 55 |
| Sample run timestamp | 2026-05-19T11:14:20Z |

### Per-year sample volume

| Year | Messages sampled |
|---|---|
| 2013 | 1 |
| 2014–2016 | 0 (no mail in these years) |
| 2017 | 40 |
| 2018 | 100 |
| 2019 | 100 |
| 2020 | 100 |
| 2021 | 100 |
| 2022 | 100 |
| 2023 | 100 |
| 2024 | 100 |
| 2025 | 100 |
| 2026 | 100 |

### Top 20 senders by volume (in sample)

| Count | Sender |
|---:|---|
| 136 | noreply@medium.com |
|  71 | account@seekingalpha.com |
|  47 | support@flippa.com |
|  26 | communication.vpm@telkomsa.net |
|  18 | alerts@japanesepod101.com |
|  17 | team@emails.evernote.com |
|  15 | newsletters@medium.com |
|  15 | warrenn@busyweb.co.za |
|  14 | noreply@google.com |
|  13 | warrenne@gmail.com |
|  12 | fnbcardemail1@fnbstatements.co.za |
|  12 | no-reply@m.mail.coursera.org |
|  12 | officialemail@absa.co.za |
|  11 | coursera@email.coursera.org |
|  11 | members@medium.com |
|   9 | noreply@mail.wirexapp.com |
|   8 | hello@justinwelsh.me |
|   8 | mare@vpmteam.co.za |
|   7 | do_not_reply@mailer.mexc.sg |
|   7 | fnbcheque@fnbstatements.co.za |

Full sender histogram in `discover.json`.

### Existing labels (preserved, untouched)

`Notes`, `Amazon`, `1Life`, `1Grid`, `ABSA`, `Figma`, `Pakt`, `mrdelivery`, `codejam`, `FNB`, `blockgeeks`, `Buffel`, `Security`, `Nedbank`, `todo`, `Deleted Items`, `Bybit`, `_Archive`, `Medium`, `Qwiklab`, `Bit`, `cloud-platform`, `LinkedIn`, `[Notion]`, `Wave`, `Offerzen`, `_Outbox`, `Habitica`, `Mac in cloud`, `Google payments`, `Sent Items`, `Cloud academy`, `Evernote`, `Datacamp`, `Tools`, `Junk E-mail`, `Meetup`, `Sync Issues`, `Trello`, `whereabouts`, `Google calendar`, `Google alerts`, `Quora`, `Google maps`, `Sync Issues/Conflicts`, `Google apps`, `HashCode`, `Zoho`, `Pnet`, `shared location`, `Sync Issues/Local Failures`, `Analytics`, `Sync Issues/Server Failures`, `Coding Game`, `Postman`

---

## Phase 2 — Refine + lock-in

### Proposed tree (auto-generated)

Categories with sub-labels driven by sender-domain heuristics + subject keywords + `List-Unsubscribe` header. See `proposed_tree.json`.

### Edits applied during refinement

- Added new top-level **`Bills`** for utility/ISP mail (Telkom).
- Merged `Finance/Fnbstatements` + `Finance/Fnb` → **`Finance/FNB`** (ALL CAPS).
- Merged `Finance/Absa` + `Finance/Absacapital` → **`Finance/ABSA`** (ALL CAPS).
- Reassigned `Other/Telkomsa` → `Bills/Telkom`.
- Reassigned `Other/Wirexapp` → `Finance/Wirex`.
- Reassigned `Other/Istore` → `Shopping/iStore`.
- Reassigned `Other/Vpmteam` → `Work/VPM`.
- Reassigned `Other/Busyweb` → `Work/Busyweb`.
- Dropped the `Other` bucket — unmatched messages stay unlabeled (review at end of Phase 3).
- Dropped `Receipts/Telkom` — Telkom mail goes to `Bills/Telkom`; can additionally pick up `Receipts` via multi-label in Phase 3.
- **Notifications** kept at top level; sub-labels `Apple` and `Google` only. Subject-pattern routing for transactional notices (login alerts, purchase confirmations, account-access warnings, trade confirmations) will be defined in Phase 3.

### Final tree (locked + created in Gmail)

29 new labels created. Full list:

```
Bills
Bills/Telkom

Finance
Finance/ABSA
Finance/FNB
Finance/Stripe
Finance/Wirex

Newsletters
Newsletters/Coursera
Newsletters/Flippa
Newsletters/Japanesepod101
Newsletters/Medium
Newsletters/Seekingalpha

Notifications
Notifications/Apple
Notifications/Google

Personal
Personal/Gmail
Personal/Hotmail

Receipts
Receipts/Acloud
Receipts/Jetbrains

Shopping
Shopping/iStore

Social
Social/LinkedIn

Work
Work/Busyweb
Work/VPM
```

### Category definitions

| Label | Meaning |
|---|---|
| `Bills` | Recurring utility/ISP invoices |
| `Finance` | Bank statements, payment processors, crypto wallets |
| `Newsletters` | Mailing lists / digests (`List-Unsubscribe` present, or known newsletter platform) |
| `Notifications` | Event/activity notices: login alerts ("login from…", "new sign-in"), purchase confirmations ("purchase for $X"), account-access warnings ("someone from X is accessing your account"), trade confirmations ("your trade for $X succeeded"). **Distinct from `Receipts`:** notifications = security/activity; receipts = commerce documents. |
| `Personal` | Mail from individual humans (gmail/hotmail/icloud) |
| `Receipts` | Order confirmations, invoices, payment receipts from commerce |
| `Shopping` | E-commerce promotional + order tracking (iStore = Apple Store SA) |
| `Social` | Social-platform notifications (LinkedIn, etc.) |
| `Work` | Work senders: VPM (vpmteam.co.za), Busyweb (own work domain) |

### Labeling-policy decisions

- **Approach A** chosen: adopt nested tree fresh; existing 55 flat labels untouched.
- Future migration of old flat → new nested (e.g. `ABSA` → `Finance/ABSA`) is **deferred to a later session**.

---

## Label creation results

| Metric | Value |
|---|---|
| Created | 29 |
| Already existed (skipped) | 0 |
| Errors | 0 |
| Timestamp | 2026-05-19 |

Details in `label_create_summary.json`.

---

## Artifacts on disk

| File | Contents | Safe to commit? |
|---|---|---|
| `credentials.json` | OAuth client secret | **No** — in `.gitignore` |
| `token.json` | Refresh token for warrenn@busyweb.co.za | **No** — in `.gitignore` |
| `discover.json` | Phase 1 sample + histogram | No (contains email metadata) |
| `proposed_tree.json` | Auto-generated tree | No (references metadata) |
| `final_tree.json` | Locked tree + category notes + edits log | No (organizational decisions, not secrets, but optional) |
| `label_create_summary.json` | Created-label IDs | No |
| `gmail-cleanup-report.md` | This file | Optional |
| `STRATEGY.md` | Session plan + progress | Optional |
| `pyproject.toml` / `gmail_cleanup/` / `tests/` | Code + tests | Yes |

---

---

## Phase 3 — Apply labels at scale

**Run timestamp:** 2026-05-19
**Plan size:** 22 labels (20 sender-based leaves + 2 subject-pattern top-levels)
**Approach:** for each sender-based leaf, apply both the leaf label AND its parent in the same `batchModify` call. Subject-pattern labels (`Receipts`, `Notifications`) layer additively. Batched 1,000 IDs per call. Resumable via `progress.json`.

### Per-label message counts

| Label | Messages labeled |
|---|---:|
| Newsletters/Seekingalpha | 2,507 |
| Newsletters/Medium | 2,285 |
| Newsletters/Flippa | 1,055 |
| Personal/Gmail | 462 |
| Receipts (subject-driven) | 419 |
| Newsletters/Coursera | 335 |
| Finance/Wirex | 306 |
| Finance/FNB | 302 |
| Notifications/Google | 264 |
| Work/VPM | 166 |
| Work/Busyweb | 134 |
| Social/LinkedIn | 133 |
| Receipts/Acloud | 106 |
| Bills/Telkom | 79 |
| Finance/ABSA | 72 |
| Notifications/Apple | 57 |
| Newsletters/Japanesepod101 | 53 |
| Notifications (subject-driven) | 34 |
| Receipts/Jetbrains | 28 |
| Finance/Stripe | 26 |
| Personal/Hotmail | 24 |
| Shopping/iStore | 18 |
| **Total label-applications** | **8,865** |

### Coverage after Phase 3 v1 (sender-based top-N + subject patterns)

| Metric | Value |
|---|---:|
| Total messages in mailbox | 14,943 |
| Unique messages with ≥1 new label | 6,235 (42%) |
| Unique messages still unlabeled | 8,708 (58%) |
| Average new labels per matched message | 1.42 |

### Unmatched long-tail

8,708 messages didn't match any of the 22 queries. These are senders in the long tail of the histogram — outside the top-N per category. Common reasons:
- Personal senders at domains other than gmail.com / hotmail.com (yahoo, outlook, icloud, work domains, etc.)
- Promotional / newsletter senders below the volume threshold
- Service notifications from senders not in DOMAIN_CATEGORIES (e.g. crypto exchanges other than Wirex, smaller ZA services)
- One-off transactional mail

To label these, a future session can:
1. Re-run `discover` with a larger sample (or a sample of *only* unlabeled messages: `q="-(label:Bills OR label:Finance OR ...)"`)
2. Surface the top senders of the unlabeled set
3. Add new sub-labels to `final_tree.json` + queries to `label_queries.json`
4. Re-run `apply` — resumability skips the 22 already done; only new entries run.

### Artifacts

| File | Contents |
|---|---|
| `label_queries.json` | Per-leaf-label search queries (editable) |
| `progress.json` | Per-label completion + counts + timestamps (resumability state) |
| `apply_summary.json` | Final run summary |

---

## Phase 3 v2 — long-tail extension

Driven by user request to address the 8,708 unmatched messages from v1.

**Approach:** added a `--query` flag to `discover` so we could sample only messages without any v1 top-level label. Sampled 1,613 messages from the 441 unmatched senders. Ran `propose` to get candidate sub-labels. Reviewed each candidate's actual subject content and reclassified where the auto-categorizer was wrong (crypto exchanges promo content → Newsletters not Finance; Amazon emails → Work/AWS not Shopping; Slack/Youtube → Notifications based on auth/ToS content).

### 19 new sub-labels added

| Label | Messages labeled |
|---|---:|
| Newsletters/Okx | 795 |
| Newsletters/Mexc | 585 |
| Newsletters/Gate | 372 |
| Newsletters/Quora | 275 |
| Newsletters/Tutorialsdojo | 165 |
| Newsletters/Meetup | 151 |
| Newsletters/Stackshare | 146 |
| Newsletters/Offerzen | 136 |
| Notifications/Bybit | 90 |
| Newsletters/Wordpress | 75 |
| Work/Github | 73 |
| Newsletters/Evernote | 60 |
| Newsletters/Plus500 | 54 |
| Notifications/Slack | 47 |
| Finance/Wise | 43 |
| Work/AWS | 32 |
| Newsletters/Livescribe | 30 |
| Personal/iCloud | 25 |
| Notifications/Youtube | 9 |
| **v2 sub-label total** | **3,163** |

### Coverage after v2

| Metric | Value |
|---|---:|
| Total messages in mailbox | 14,943 |
| Unique messages with ≥1 new label | 9,380 (62.8%) |
| Unique messages still unlabeled | 5,563 (37.2%) |

### Reclassification notes from content review

- **Crypto exchanges (Mexc, Okx, Gate, Plus500):** initially proposed as Finance/* by domain heuristics. Subject review showed 100% promotional content ("Exclusive Bonus Rewards", "Holiday Bonanza", "Risers and Fallers", "USDT Lend & Earn"). Reclassified to Newsletters/*.
- **Bybit:** all subjects are "[Testnet-Bybit] Liquidation Notice / Repayment / Upgrade Completed" — transactional/account-activity from a testnet account. Classified as Notifications/Bybit (not Finance).
- **Wise (kept Finance):** subjects like "Transfer sent", "X paid you" — genuine transactional money-movement.
- **Amazon → Work/AWS:** all 12 amazon.com messages are AWS training, account verification, case follow-ups. This user uses Amazon for AWS services, not retail. Shopping/Amazon would have been wrong.
- **Slack → Notifications/Slack:** subjects are "Slack confirmation code", "Sign in from new device", "New Account Details" — auth/account events.
- **Youtube → Notifications/Youtube:** subjects are "Changes to YouTube's Terms of Service" — service announcements.

### Tooling change

`discover` gained a `--query` flag (`gmail_cleanup/discover.py:compose_year_query`) — prefixes user-supplied Gmail search to each per-year sample query. Lets us sample subsets like "unlabeled-only" without code changes. 3 new tests in `tests/test_discover.py`.

---

---

## Phase 3 v3 — push deeper into the long-tail

Sampled the remaining 5,563 unmatched messages: 2,082 threads / 509 unique senders. Lowered min-count threshold to 3. Reviewed candidate subjects to reclassify Notifications vs Newsletters vs Work.

### Bugfix during v3

- **Retry didn't catch network-level timeouts.** First v3 discover crashed on `TimeoutError` (SSL socket read timeout) — my retry wrapper only caught `HttpError`. Broadened both `discover._retry` and `apply._retry` to also retry on `(TimeoutError, ConnectionError, OSError)` with exponential backoff.
- **Travel top-level was missing.** v3 introduced `Travel/Booking` but I forgot to include the `Travel` parent. Gmail accepted creating the child without the parent — but our apply code requires both ancestors in `name_to_id`, so `Travel/Booking` was silently skipped (`[skip] label not found: Travel`). Fixed by creating the Travel parent and re-running.

### 26 new sub-labels added (v3)

| Label | Messages labeled |
|---|---:|
| Notifications/Mexc | 516 |
| Newsletters/Gate (extended query) | +62 over v2 |
| Notifications/Coinex | 377 |
| Newsletters/Bitget | 329 |
| Work/PathosEthos | 216 |
| Work/Surgenly | 139 |
| Newsletters/Justinwelsh | 126 |
| Newsletters/Wallmine | 123 |
| Newsletters/Ideabrowser | 113 |
| Work/Verity | 89 |
| Newsletters/Maxmahershow | 85 |
| Newsletters/Jobleads | 81 |
| Newsletters/Etoro | 64 |
| Newsletters/Scrimba | 45 |
| Notifications/Binance | 42 |
| Bills/Vodacom | 32 |
| Newsletters/Lumosity | 32 |
| Newsletters/Linuxacademy | 30 |
| Newsletters/Openai | 29 |
| Notifications/Remote | 28 |
| Finance/XM | 27 |
| Work/Notion | 22 |
| Finance/Discovery | 21 |
| Work/Relevant | 20 |
| Personal/Yahoo | 19 |
| Travel/Booking | 18 |
| Work/Trello | 10 |
| **v3 total new applications** | **~2,690** |

### Content-driven reclassifications (v3)

- **Mexc:** split across two labels by content. `Newsletters/Mexc` continues to catch `mexc.sg`/`mexc.com` (promo). New `Notifications/Mexc` covers `mexc.link` (trading-trigger transactional alerts: "Trailing Stop Order Triggered Successfully").
- **Coinex / Binance:** transactional-only ("Notification on Approved Withdrawal", "Information Required to Maintain Account Access") → Notifications, not Newsletters.
- **Bitget / Etoro:** all marketing ("Win 10 USDT", "Trade from just $10") → Newsletters.
- **Gate:** existing v2 query was `from:gate.io`. Sample showed `from:gate.com` was a separate Gate.io subdomain (30 more messages). Extended to `from:(gate.io OR gate.com)` — caught 62 additional messages on re-run.
- **PathosEthos / Surgenly / Verity / Relevant:** all turned out to be work-contracting projects (cron jobs, AWS configuration, system platform emails). Created flat `Work/{Client}` sub-labels for each.
- **`absa.africa` false-positive:** heuristic suggested Finance/ABSA based on domain. Subjects revealed these are forwarded work conversations from ex-colleagues' corporate ABSA emails ("FW: 2019 State of DevOps Report", "Re: Dell laptop stopped working"), not bank notifications. Skipped — left unlabeled. Important lesson: a `from:` domain that overlaps with a known brand doesn't mean the message is from that brand.

### Coverage after v3

| Metric | Value |
|---|---:|
| Total messages in mailbox | 14,944 |
| Unique messages with ≥1 new label | 12,068 (80.8%) |
| Unique messages still unlabeled | 2,876 (19.2%) |

---

## Phase 3 v4 — deep long-tail with --min-count 1

Sampled remaining 2,876 unmatched messages (2,301 threads / 632 unique senders). Ran propose with `--min-count 1 --top-n 50` to surface every sender. Triaged to **22 new labels + 2 query extensions** at a ≥15-sample-count threshold. Skipped 60+ smaller candidates (5–14 sample messages) for diminishing return on sidebar clutter.

### 22 new sub-labels + 2 extensions

| Label | Messages labeled |
|---|---:|
| Newsletters/Pnet | 235 (job-board promos — biggest v4) |
| Notifications/Coinbase | 161 |
| Newsletters/Patreon | 124 |
| Bills/SARS | 117 (SA Revenue Service — tax) |
| Notifications/Cex | 93 |
| Newsletters/Xt | 75 |
| Newsletters/Cal | 67 |
| Newsletters/Kraken | 58 |
| Newsletters/Tradingview | 56 |
| Notifications/Docusign | 51 |
| Newsletters/Discourse | 43 |
| Newsletters/Replit | 41 |
| Notifications/Payoneer | 38 |
| Newsletters/Juliangoldie | 37 |
| Bills/Liberty | 32 |
| Newsletters/Ein-Itin | 31 |
| Bills/Kingprice | 30 |
| Work/Datachef | 30 |
| Work/Simola | 29 |
| Notifications/Luno | 27 |
| Work/IOCO | 23 |
| Work/AWSIQ | 22 |
| Bills/Telkom (extension `telkomsa.net OR telkom.co.za`) | +59 |
| Finance/XM (extension `xm.com OR xmglobal.com`) | +25 |
| **v4 total new applications** | **~1,141** |

### Content-driven reclassifications (v4)

- **Coinbase, Cex, Docusign, Payoneer, Luno** — verified by subject content as Notifications (verify ID, sign-in alerts, payment confirmations) not Newsletters.
- **Kraken, Xt, Microsoft (e-mails.*), Patreon** — verified as Newsletters (marketing) despite "notification" appearing in domain names.
- **SARS** (sars.gov.za) — South African tax authority. Classified as `Bills/SARS` for tax filings/statements (closest existing parent category).
- **Liberty (liberty.co.za) and Kingprice (kingprice.co.za)** — insurance providers. Classified as Bills (recurring premiums + statements).
- **Telkom extension** — `telkomsa.net` vs `telkom.co.za` are both Telkom but different domains. Single query covering both.

### Coverage after v4

| Metric | Value |
|---|---:|
| Total messages in mailbox | 14,944 |
| Unique messages with ≥1 new label | **13,031 (87.2%)** |
| Unique messages still unlabeled | **1,913 (12.8%)** |

### Coverage progression across all iterations

| Iteration | Labels in tree | Coverage |
|---|---:|---:|
| Pre-Phase 3 (label tree locked but no apply) | 29 | 0% |
| v1 | 29 (sender-based top-N + 2 subject) | 42.0% |
| v2 | 48 | 62.8% |
| v3 | 74 | 80.8% |
| v4 | 96 | 87.2% |
| **v5 (added `Other` catch-all)** | **97** | **100.00%** |

---

## Phase 3 v5 — 100% coverage via single catch-all

User goal: every email must have at least one label, using the minimum number of additional labels.

Solution: one new top-level label `Other`. Applied via a single `batchModify` pass to all 1,913 remaining unmatched messages.

| Metric | Value |
|---|---:|
| Total messages in mailbox | 14,944 |
| Messages with at least one label | **14,944 (100.00%)** |
| Labels added this iteration | **1** (`Other`) |

The `Other` label is the fallback bucket for senders that didn't form a coherent pattern across 4 iterations. The user can browse `Other` in Gmail's sidebar and manually re-categorize anything they later decide deserves its own sub-label — but the goal of "every email is labeled" is now met.

---

## Phase 4 (deferred)

Out of scope per user. If revisited: would label messages for cleanup (e.g. `_ToTrash`) and `batchModify` add `TRASH` (never `batchDelete`). Per-batch confirmation. Trash auto-empties after 30 days.

---

## Phase 3 \"Next-session\" notes (kept for reference)

Original Phase 3 prep notes from the earlier version of this report:

1. Read `STRATEGY.md` and `final_tree.json` — the locked tree is the spec.
2. Build per-leaf-label search queries (mapping from `category_notes` + sample histogram):
   - `Finance/FNB` → `from:(fnbstatements.co.za OR fnb.co.za)`
   - `Finance/ABSA` → `from:(absa.co.za OR absacapital.com)`
   - `Finance/Stripe` → `from:stripe.com`
   - `Finance/Wirex` → `from:wirexapp.com`
   - `Newsletters/Medium` → `from:(medium.com OR mail.medium.com)`
   - `Newsletters/Seekingalpha` → `from:seekingalpha.com`
   - `Newsletters/Flippa` → `from:flippa.com`
   - `Newsletters/Coursera` → `from:(coursera.org OR email.coursera.org OR mail.coursera.org)`
   - `Newsletters/Japanesepod101` → `from:japanesepod101.com`
   - `Notifications/Apple` → `from:apple.com`
   - `Notifications/Google` → `from:noreply@google.com`
   - `Notifications` (top-level, subject-driven): `subject:("login from" OR "new sign-in" OR "your trade" OR "purchase for" OR "someone is accessing")`
   - `Bills/Telkom` → `from:telkomsa.net`
   - `Receipts/Acloud` → `from:acloud.guru`
   - `Receipts/Jetbrains` → `from:jetbrains.com`
   - `Receipts` (top-level, subject-driven): `subject:(receipt OR invoice OR "order confirmation" OR "your order")`
   - `Shopping/iStore` → `from:istore.co.za`
   - `Social/LinkedIn` → `from:linkedin.com`
   - `Work/VPM` → `from:vpmteam.co.za`
   - `Work/Busyweb` → `from:busyweb.co.za`
   - `Personal/Gmail` → `from:gmail.com`
   - `Personal/Hotmail` → `from:hotmail.com`
3. Wire `gmail_cleanup/apply.py` (new module) using `users.messages.batchModify` with `addLabelIds=[labelId]`, 1000 IDs per batch.
4. Pace at <120 batchModify/min (quota safe).
5. Per-label: list IDs → batch-modify → log count.
6. At the end, surface count of unlabeled messages and ask user about a catch-all.

Phase 4 (trash) remains out of scope per user.

---

## Don'ts honored

- ✅ No `https://mail.google.com/` scope requested.
- ✅ No `batchDelete` call anywhere in the code.
- ✅ No labels created until explicit user lock-in confirmation.
- ✅ Token + credentials in `.gitignore`.

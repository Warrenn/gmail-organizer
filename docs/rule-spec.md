# Rule specification — `gmail_cleanup/rules.yaml`

The single source of truth for label-classification logic. Used by:

- The Python rule interpreter (`gmail_cleanup/rule_interpreter.py`),
  which is what the corpus regression tests run against
- The Apps Script generator (`python -m gmail_cleanup generate-apps-script`),
  which emits `apps-script/Rules.gs` (sender + subject rules) and
  `apps-script/Classifier.gs` (fallback rules)

You should not edit `apps-script/Rules.gs` or `apps-script/Classifier.gs`
directly. They are regenerated artifacts.

---

## File structure

```yaml
version: 1

sender_rules:        # Phase 1 — terminal. First sender_rule that matches wins.
  - id: ...
    match: ...
    labels: [...]

additive_subject_rules:  # Phase 2 — layer on top of phase 1 (or stand alone).
  - id: ...
    match: ...
    labels: [...]

fallback_rules:      # Phase 3 — terminal. Only runs if neither phase 1 nor phase 2 matched.
  - id: ...
    match: ...
    labels: [...]
```

Order within each section matters: within `sender_rules` and `fallback_rules`,
the first matching rule wins. Within `additive_subject_rules`, every matching
rule contributes its labels.

The last rule in `fallback_rules` should have no `match` (or an
always-true match) — this is the project's default catch-all.

---

## Resolution algorithm

Given a thread with `(from, subject, snippet)`:

1. **Phase 1** — iterate `sender_rules` in order. For the first rule whose
   `match` evaluates true, set `labels = rule.labels`. Stop iterating phase 1.
2. **Phase 2** — iterate `additive_subject_rules` in order. For each rule
   whose `match` evaluates true, set `labels = labels ∪ rule.labels` (set
   union, dedup, preserve insertion order).
3. **Phase 3** — if and only if `labels` is still empty (neither phase 1 nor
   phase 2 matched anything), iterate `fallback_rules` in order. For the
   first rule whose `match` evaluates true, set `labels = rule.labels`.
4. Return `labels` as a list, deduplicated, in insertion order.

Worth knowing:

- Phase 2's labels layer additively over phase 1, but phase 3 is skipped
  if phase 2 produced any labels. This faithfully mirrors the current
  Apps Script behavior (where `phase 3 = -has:userlabels search` and a
  phase-2 label disqualifies a thread from phase 3).
- All string comparisons inside a `match` are case-insensitive (the
  interpreter lowercases inputs before applying operators).

---

## Rule fields

Every rule object has these fields:

| Field         | Type           | Required | Notes |
|---------------|----------------|----------|-------|
| `id`          | string         | yes      | Stable identifier. Used in commit messages, PR comments, and corpus references. Kebab-case. Unique across the whole file. |
| `description` | string         | no       | One-liner. Optional but encouraged for non-obvious rules. |
| `match`       | match-object   | usually  | The condition. Omitted only on the trailing default `fallback_rule`. |
| `labels`      | list[string]   | yes      | Convention labels (lowercase, hyphenated). At least one. |

---

## Match object — operators

A match-object is a dict where every top-level key is implicitly AND-ed.
At least one operator key must be present (otherwise it's always-true,
which is only allowed for the trailing default fallback).

### Sender (from header) operators

| Operator                    | Type           | Meaning |
|-----------------------------|----------------|---------|
| `from_contains`             | string         | substring is present in `from` (lowercased) |
| `from_contains_any`         | list[string]   | at least one substring is present in `from` |
| `from_not_contains_any`     | list[string]   | none of these substrings are present in `from` |

### Subject operators

| Operator                       | Type           | Meaning |
|--------------------------------|----------------|---------|
| `subject_contains`             | string         | substring is present in `subject` |
| `subject_contains_any`         | list[string]   | at least one substring is present in `subject` |
| `subject_not_contains_any`     | list[string]   | none of these substrings are present in `subject` |
| `subject_starts_with_any`      | list[string]   | `subject.strip()` starts with at least one |
| `subject_matches_regex`        | string         | Python regex `re.search` matches `subject`. Only allowed for non-trivial patterns the human-readable operators can't express (e.g. hash detection). The property tests reject regexes equivalent to `.*`. |

### Snippet (body excerpt) operators

| Operator                | Type           | Meaning |
|-------------------------|----------------|---------|
| `snippet_contains`      | string         | substring is present in `snippet` (lowercased, first 300 chars of body) |
| `snippet_contains_any`  | list[string]   | at least one substring |

### Cross-field operators

| Operator                | Type           | Meaning |
|-------------------------|----------------|---------|
| `text_contains_any`     | list[string]   | at least one substring is present in `from + " \|\| " + subject + " \|\| " + snippet` (lowercased). Used by junk-pattern matchers. |

### Logical composition

| Operator   | Type                  | Meaning |
|------------|-----------------------|---------|
| `any_of`   | list[match-object]    | at least one nested match-object is true |
| `all_of`   | list[match-object]    | all nested match-objects are true (rarely useful since the outer keys are already AND'd; mostly for grouping inside `any_of`) |

---

## Sender rules — special note

A `sender_rule`'s `match` is restricted to **sender operators only**
(`from_contains`, `from_contains_any`, `from_not_contains_any`), with
no `any_of` / `all_of` composition. This is so the generator can compile
each rule to a Gmail search query string for use by Apps Script's
server-side `GmailApp.search()`. If you want a content-based condition
(subject, snippet, text), or any nested logical composition, put the
rule in `additive_subject_rules` or `fallback_rules` instead.

A future spec version may add the ability to compile subject conditions
or nested logical groups into sender-rule queries (Gmail's `subject:`
operator + parenthesised OR groups), but v1 keeps it strict.

---

## Examples

```yaml
version: 1

sender_rules:
  - id: telkom-bills
    description: Telkom SA telecom invoices
    match:
      from_contains_any: [telkomsa.net, telkom.co.za]
    labels: [bills, telkom]

  - id: stripe-finance
    match:
      from_contains: stripe.com
    labels: [finance, stripe]

  - id: absa-work-colleagues
    description: ABSA work-colleague mail; exclude bank-system addresses
    match:
      from_contains: absa.africa
      from_not_contains_any: [cardnotification, officialemail]
    labels: [work, absa]

additive_subject_rules:
  - id: subject-receipts
    match:
      subject_contains_any:
        - receipt
        - invoice
        - "order confirmation"
        - "your order"
        - "thank you for your order"
        - "thank you for your purchase"
    labels: [receipts]

  - id: subject-otp
    match:
      subject_contains_any:
        - "verification code"
        - OTP
        - "one-time password"
        - "your code"
        - "login code"
        - "security code"
    labels: [otp]

  - id: stripe-payouts-as-receipts
    description: A Stripe payout is also a receipt
    match:
      from_contains: stripe.com
      subject_contains_any: ["your stripe payout", "payout of"]
    labels: [receipts]

fallback_rules:
  - id: junk-patterns
    match:
      text_contains_any:
        - lhspla.net
        - elogica.com.br
        - onlyfans
        - "geek squad"
        - "norton internet security expired"
    labels: [junk-e-mail]

  - id: noreply-as-notifications
    match:
      from_contains_any: [noreply, no-reply, donotreply]
    labels: [notifications]

  - id: default
    labels: [newsletters]
```

---

## Versioning

The top-level `version: 1` field locks the spec semantics.

When the spec evolves (new operators, structural changes, removed
features), the version bumps and a migration must be provided
alongside. The interpreter rejects unknown versions with a clear error.

Spec migrations are out of scope for the feedback-loop autonomy — they
require a dedicated human-reviewed PR.

---

## Conventions

- **Labels** in `labels:` lists must follow the project convention:
  lowercase, hyphenated, only `[a-z0-9_-]` characters. The exceptions are
  underscore-prefixed labels (`_Outbox`, etc.) and the 8 Outlook sync
  folders (`Junk E-mail`, `Notes`, etc.) — these match
  `gmail_cleanup/normalize.py::EXCLUDED_LABELS` exactly.
- **IDs** are kebab-case, unique, descriptive. Good: `stripe-payouts-as-receipts`.
  Bad: `rule-42`, `stripe`.
- **Comments** (`#`) are allowed throughout the YAML. Use them when a
  rule's purpose isn't self-evident from the id + match.

---

## See also

- `STRATEGY.md` — feedback-loop project plan (Phase 0 + Phase 1)
- `.github/prompts/feedback-loop.md` — the runtime prompt Claude
  receives in the autonomous workflow; references this spec

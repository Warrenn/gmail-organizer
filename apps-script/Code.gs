/**
 * Gmail Organizer — Apps Script
 *
 * Runs on a schedule (default: hourly) to label new mail according to RULES
 * (defined in Rules.gs) and a fallback content classifier (Classifier.gs).
 *
 * Setup (one-time, after `clasp push`):
 *   1. Open the project at https://script.google.com
 *   2. Run `setupTriggers()` once and grant the requested permissions.
 *   3. (Optional) Run `organizeInbox()` once manually to verify labels apply.
 *
 * To stop the automation:
 *   - Run `removeTriggers()` or delete the trigger in the web UI.
 */

const MAX_THREADS_PER_RULE = 50;
const MAX_FALLBACK_THREADS = 100;
const DRY_RUN = false; // set true to log decisions without applying labels


/**
 * Entry point — invoked by the time-driven trigger.
 */
function organizeInbox() {
  const start = Date.now();
  const counts = {};
  let labeledRules = 0;
  let labeledFallback = 0;

  // 1. Apply leaf-rules to threads that have no user labels yet
  for (const rule of RULES) {
    const q = rule.query + ' -has:userlabels';
    let threads;
    try {
      threads = GmailApp.search(q, 0, MAX_THREADS_PER_RULE);
    } catch (e) {
      console.warn('[organizeInbox] search failed for rule:', rule.query, e);
      continue;
    }
    if (!threads || threads.length === 0) continue;

    if (DRY_RUN) {
      console.log(`[dry-run] ${threads.length} threads would get ${JSON.stringify(rule.labels)} from rule: ${rule.query}`);
      threads.forEach(() => rule.labels.forEach(name => { counts[name] = (counts[name] || 0) + 1; }));
      labeledRules += threads.length;
      continue;
    }

    const labels = rule.labels.map(getOrCreateLabel_);
    threads.forEach(thread => {
      labels.forEach(lbl => lbl.addToThread(thread));
    });
    rule.labels.forEach(name => {
      counts[name] = (counts[name] || 0) + threads.length;
    });
    labeledRules += threads.length;
  }

  // 2. Subject-pattern rules (Receipts, Notifications) — additive over leaf labels
  for (const rule of SUBJECT_RULES) {
    const q = rule.query + ' -label:' + rule.labels[0];
    let threads;
    try {
      threads = GmailApp.search(q, 0, MAX_THREADS_PER_RULE);
    } catch (e) {
      console.warn('[organizeInbox] subject-rule search failed:', rule.query, e);
      continue;
    }
    if (!threads || threads.length === 0) continue;

    if (DRY_RUN) {
      console.log(`[dry-run] ${threads.length} threads would get ${JSON.stringify(rule.labels)} from subject rule: ${rule.query}`);
      rule.labels.forEach(name => { counts[name] = (counts[name] || 0) + threads.length; });
      continue;
    }

    const labels = rule.labels.map(getOrCreateLabel_);
    threads.forEach(thread => {
      labels.forEach(lbl => lbl.addToThread(thread));
    });
    rule.labels.forEach(name => {
      counts[name] = (counts[name] || 0) + threads.length;
    });
  }

  // 3. Fallback: still-unlabeled threads get classified by sender/subject patterns
  let stillUnlabeled;
  try {
    stillUnlabeled = GmailApp.search('-has:userlabels', 0, MAX_FALLBACK_THREADS);
  } catch (e) {
    console.warn('[organizeInbox] fallback search failed:', e);
    stillUnlabeled = [];
  }

  stillUnlabeled.forEach(thread => {
    const labels = classifyThread_(thread);
    if (!labels || labels.length === 0) return;
    if (DRY_RUN) {
      console.log(`[dry-run] fallback would apply ${JSON.stringify(labels)} to thread "${thread.getFirstMessageSubject()}"`);
      labels.forEach(name => { counts[name] = (counts[name] || 0) + 1; });
      labeledFallback += 1;
      return;
    }
    labels.forEach(name => {
      const lbl = getOrCreateLabel_(name);
      lbl.addToThread(thread);
      counts[name] = (counts[name] || 0) + 1;
    });
    labeledFallback += 1;
  });

  const elapsedSec = Math.round((Date.now() - start) / 1000);
  console.log(`[organizeInbox] done in ${elapsedSec}s. Rules-labeled: ${labeledRules}, fallback-labeled: ${labeledFallback}. Per-label:`, counts);
}


/**
 * Install the hourly trigger. Run once after deploying.
 */
function setupTriggers() {
  removeTriggers();
  ScriptApp.newTrigger('organizeInbox')
    .timeBased()
    .everyHours(1)
    .create();
  console.log('Installed hourly trigger for organizeInbox().');
}


/**
 * Remove all triggers for organizeInbox(). Call before changing schedule
 * or to stop the automation.
 */
function removeTriggers() {
  let removed = 0;
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'organizeInbox') {
      ScriptApp.deleteTrigger(t);
      removed++;
    }
  });
  console.log(`Removed ${removed} trigger(s) for organizeInbox.`);
}


/**
 * Idempotently fetch (or create) a Gmail user label by name.
 *
 * Names are normalized to the project convention (lowercase, hyphenated,
 * no non-alphanumeric chars) before lookup/creation, EXCEPT for:
 *   - underscore-prefixed labels (e.g. _Archive, _Outbox)
 *   - Outlook sync folders (Notes, Deleted Items, Sent Items, Junk E-mail,
 *     Sync Issues, Conflicts, Local Failures, Server Failures)
 * These are passed through unchanged. This is a safeguard against future
 * rule edits that forget the convention — the runtime normalizer catches
 * non-conforming names and routes them to the correct existing label.
 */
function getOrCreateLabel_(name) {
  const finalName = shouldSkipName_(name) ? name : normalizeLabelName_(name);
  let label = GmailApp.getUserLabelByName(finalName);
  if (!label) {
    label = GmailApp.createLabel(finalName);
    console.log(`[label] created new label: ${finalName}`);
  }
  return label;
}


const EXCLUDED_LABELS = [
  'Notes', 'Deleted Items', 'Sent Items', 'Junk E-mail',
  'Sync Issues', 'Conflicts', 'Local Failures', 'Server Failures',
];


function shouldSkipName_(name) {
  if (name.startsWith('_')) return true;
  return EXCLUDED_LABELS.indexOf(name) !== -1;
}


function normalizeLabelName_(name) {
  return name.trim().toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9_-]/g, '');
}


/**
 * Self-tests for the label-name normalizer. Invoke manually from the
 * Apps Script editor (Run → _runSelfTests). Logs PASS / FAIL per case.
 * No deps, no Gmail mutations — safe to run anytime.
 */
function _runSelfTests() {
  let pass = 0, fail = 0;
  const check = (label, got, expected) => {
    if (JSON.stringify(got) === JSON.stringify(expected)) {
      pass++;
      console.log(`  PASS  ${label}`);
    } else {
      fail++;
      console.warn(`  FAIL  ${label} — got ${JSON.stringify(got)}, expected ${JSON.stringify(expected)}`);
    }
  };

  const normalizeCases = [
    ['Amazon', 'amazon'],
    ['AWS', 'aws'],
    ['scribd', 'scribd'],
    ['Mac in cloud', 'mac-in-cloud'],
    ['[Notion]', 'notion'],
    ['docuwriter.ai', 'docuwriterai'],
    ['Ein-Itin', 'ein-itin'],
    ['Junk E-mail', 'junk-e-mail'],
    ['  whitespace  ', 'whitespace'],
    ['Mac  in   cloud', 'mac-in-cloud'],
  ];
  normalizeCases.forEach(([input, expected]) => {
    check(`normalizeLabelName_("${input}") === "${expected}"`, normalizeLabelName_(input), expected);
  });

  const skipCases = [
    ['_Outbox', true],
    ['_Archive', true],
    ['Junk E-mail', true],
    ['Notes', true],
    ['Sync Issues', true],
    ['amazon', false],
    ['notion', false],
    ['Amazon', false],
  ];
  skipCases.forEach(([input, expected]) => {
    check(`shouldSkipName_("${input}") === ${expected}`, shouldSkipName_(input), expected);
  });

  console.log(`\nSelf-tests: ${pass} pass, ${fail} fail`);
  if (fail > 0) throw new Error(`${fail} self-test(s) failed — see log`);
}

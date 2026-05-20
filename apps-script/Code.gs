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
 */
function getOrCreateLabel_(name) {
  let label = GmailApp.getUserLabelByName(name);
  if (!label) {
    label = GmailApp.createLabel(name);
    console.log(`[label] created new label: ${name}`);
  }
  return label;
}

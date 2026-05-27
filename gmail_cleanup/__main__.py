from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gmail_cleanup import apply, auth, classify, cleanup as cleanup_markers, corpus, discover, feedback, flatten, generate, labels, propose, rename, rule_interpreter


def cmd_discover(args: argparse.Namespace) -> int:
    service = auth.get_service(Path(args.credentials), Path(args.token))
    discover.run_discover(
        service,
        output_path=Path(args.output),
        account=args.account,
        per_year_cap=args.per_year_cap,
        max_total=args.max_total,
        extra_query=args.query,
    )
    return 0


def cmd_propose(args: argparse.Namespace) -> int:
    tree = propose.run_propose(
        discover_path=Path(args.input),
        output_path=Path(args.output),
        top_n=args.top_n,
        min_count=args.min_count,
    )
    print(propose.render_tree(tree))
    print(f"\n→ wrote {args.output}")
    return 0


def cmd_create_labels(args: argparse.Namespace) -> int:
    tree = json.loads(Path(args.input).read_text())
    target = tree["labels"]
    print(f"will create up to {len(target)} labels (existing ones are skipped)")
    print("labels to ensure:")
    for l in target:
        print(f"  • {l}")
    if not args.yes:
        confirm = input("\nProceed? type 'yes' to confirm: ").strip().lower()
        if confirm != "yes":
            print("aborted")
            return 1
    service = auth.get_service(Path(args.credentials), Path(args.token))
    summary = labels.create_missing_labels(service, target)
    print("\n=== summary ===")
    print(f"created: {len(summary['created'])}")
    print(f"already existed: {len(summary['skipped'])}")
    print(f"errors: {len(summary['errors'])}")
    Path(args.output).write_text(json.dumps(summary, indent=2))
    print(f"→ wrote {args.output}")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    queries_file = json.loads(Path(args.queries).read_text())
    leaf_queries = queries_file.get("leaf_label_queries", {})
    subject_queries = queries_file.get("subject_pattern_queries", {})
    label_summary = json.loads(Path(args.label_summary).read_text())
    name_to_id = {entry["name"]: entry["id"] for entry in label_summary.get("created", [])}

    service = auth.get_service(Path(args.credentials), Path(args.token))
    existing = labels.list_existing_label_names(service)
    for name, id_ in existing.items():
        name_to_id.setdefault(name, id_)

    plan = apply.compile_label_plan(leaf_queries, subject_queries, name_to_id)
    print(f"compiled plan: {len(plan)} labels to apply")
    for item in plan:
        print(f"  • {item['label_name']:30s}  →  {item['query']}")

    if not args.yes:
        confirm = input("\nProceed? type 'yes' to confirm: ").strip().lower()
        if confirm != "yes":
            print("aborted")
            return 1

    summary = apply.run_apply(service, plan, Path(args.progress))
    print("\n=== Phase 3 apply summary ===")
    print(f"labels processed this run: {summary['labels_processed']}")
    print(f"labels skipped (already done): {summary['labels_skipped_already_done']}")
    print(f"total messages labeled this run: {summary['total_messages_labeled_this_run']}")
    print("\nper-label totals:")
    for name in sorted(summary["per_label"]):
        print(f"  {summary['per_label'][name]:7d}  {name}")
    Path(args.output).write_text(json.dumps(summary, indent=2))
    print(f"\n→ wrote {args.output}")
    return 0


def cmd_classify_export(args: argparse.Namespace) -> int:
    service = auth.get_service(Path(args.credentials), Path(args.token))
    classify.export_for_classification(service, Path(args.output))
    return 0


def cmd_classify_apply(args: argparse.Namespace) -> int:
    service = auth.get_service(Path(args.credentials), Path(args.token))
    summary = classify.apply_classification(
        service,
        Path(args.classification),
        Path(args.dump),
    )
    print("\n=== classify-apply summary ===")
    print(f"messages classified: {summary['messages_classified']}")
    print(f"messages invalid (skipped): {summary['messages_invalid']}")
    print(f"distinct label combinations: {summary['groups']}")
    print("\nper-label totals:")
    for name in sorted(summary["label_application_counts"]):
        print(f"  {summary['label_application_counts'][name]:5d}  {name}")
    Path(args.output).write_text(json.dumps(summary, indent=2))
    print(f"\n→ wrote {args.output}")
    return 0


def cmd_flatten(args: argparse.Namespace) -> int:
    service = auth.get_service(Path(args.credentials), Path(args.token))
    all_labels = flatten.list_all_labels(service)
    user_labels = [l for l in all_labels if l.get("type") == "user"]
    nested = [l for l in user_labels if "/" in l.get("name", "")]
    flat = [l for l in user_labels if "/" not in l.get("name", "")]

    print(f"plan: flatten {len(nested)} nested labels into flat leaves")
    print(f"existing flat user labels: {len(flat)}")

    collisions = flatten.identify_leaf_collisions(nested)
    if collisions:
        print("\nleaf-name collisions (merge into single flat):")
        for leaf, names in collisions.items():
            print(f"  {leaf}: {names}")

    overlaps = flatten.identify_existing_flat_overlaps(nested, {l["name"] for l in flat})
    if overlaps:
        print(f"\noverlaps with existing flat labels ({len(overlaps)} — will merge):")
        for leaf in sorted(overlaps):
            print(f"  {leaf}")

    print(f"\nnested labels to be flattened:")
    for l in sorted(nested, key=lambda x: x["name"]):
        print(f"  {l['name']}")

    if not args.yes:
        print("\nThis is destructive (nested labels will be deleted after their messages are relabeled to flat leaves).")
        confirm = input("type 'yes' to proceed: ").strip().lower()
        if confirm != "yes":
            print("aborted")
            return 1

    summary = flatten.run_flatten(service)
    print("\n=== flatten summary ===")
    print(f"nested labels processed: {len(summary['nested_labels_processed'])}")
    print(f"new flat labels created: {len(summary['flat_labels_created'])}")
    print(f"total messages relabeled: {summary['messages_relabeled_total']}")
    Path(args.output).write_text(json.dumps(summary, indent=2))
    print(f"→ wrote {args.output}")
    return 0


def cmd_rename_labels(args: argparse.Namespace) -> int:
    service = auth.get_service(Path(args.credentials), Path(args.token))
    all_labels = flatten.list_all_labels(service)
    user_labels = [
        {"id": l["id"], "name": l["name"]}
        for l in all_labels
        if l.get("type") == "user"
    ]

    extra = frozenset(args.exclude or [])
    plan = rename.plan_renames(user_labels, extra_excludes=extra)

    print("=== rename-labels plan ===")
    print(f"  renames: {len(plan['renames'])}")
    print(f"  merges:  {len(plan['merges'])}")
    print(f"  skipped: {len(plan['skipped'])}")

    if plan["merges"]:
        print("\nmerges (source label deleted after relabeling its threads onto target):")
        for m in plan["merges"]:
            print(f"  {m['source_name']!r}  →  into  {m['target_name']!r}")

    if plan["renames"]:
        print("\nrenames:")
        for r in plan["renames"]:
            print(f"  {r['old_name']:30s}  →  {r['new_name']}")

    by_reason: dict[str, list[str]] = {}
    for s in plan["skipped"]:
        by_reason.setdefault(s["reason"], []).append(s["name"])
    if by_reason:
        print("\nskipped:")
        for reason in sorted(by_reason):
            names = sorted(by_reason[reason])
            print(f"  {reason} ({len(names)}):")
            for n in names:
                print(f"    {n}")

    if not args.apply:
        print("\n(dry-run; pass --apply to execute)")
        return 0

    if not plan["renames"] and not plan["merges"]:
        print("\nnothing to do.")
        return 0

    if not args.yes:
        confirm = input("\nProceed with these changes? type 'yes' to confirm: ").strip().lower()
        if confirm != "yes":
            print("aborted")
            return 1

    summary = rename.apply_plan(service, plan)
    print("\n=== apply summary ===")
    print(f"  renames applied: {summary['renames_applied']}")
    print(f"  merges applied:  {summary['merges_applied']}")
    print(f"  errors:          {len(summary['errors'])}")
    for e in summary["errors"]:
        print(f"    ERROR ({e['operation']}): {e}")

    if args.output:
        Path(args.output).write_text(json.dumps(summary, indent=2))
        print(f"→ wrote {args.output}")

    return 0 if not summary["errors"] else 2


def cmd_cleanup_markers(args: argparse.Namespace) -> int:
    resolved_path = Path(args.input)
    if not resolved_path.exists():
        print(f"no resolved-markers file at {resolved_path}; nothing to do")
        return 0
    resolved = json.loads(resolved_path.read_text())
    if not resolved:
        print("resolved-markers file is empty; nothing to do")
        return 0
    service = auth.get_service(Path(args.credentials), Path(args.token))
    summary = cleanup_markers.cleanup_resolved_markers(service, resolved)
    print(json.dumps(summary, indent=2))
    return 0 if not summary["errors"] else 2


def cmd_feedback_scan(args: argparse.Namespace) -> int:
    service = auth.get_service(Path(args.credentials), Path(args.token))
    result = feedback.scan_for_markers(service)
    Path(args.output).write_text(json.dumps(result, indent=2))
    n_markers = len(result["markers"])
    n_threads = sum(len(m["threads"]) for m in result["markers"])
    print(f"feedback: {n_markers} markers, {n_threads} threads → {args.output}")
    if args.exit_zero_on_empty and n_markers == 0:
        return 0
    return 0 if n_markers > 0 else 78  # 78 == EX_CONFIG; signals "no work" to workflow


def cmd_corpus_build(args: argparse.Namespace) -> int:
    service = auth.get_service(Path(args.credentials), Path(args.token))
    raw = corpus.build_corpus(
        service,
        per_label_sample_size=args.per_label,
        exclude_labels=set(args.exclude or []),
    )
    raw_count = len(raw["threads"])

    if args.no_filter:
        Path(args.output).write_text(json.dumps(raw, indent=2))
        print(f"corpus (unfiltered): {raw_count} threads → {args.output}")
        return 0

    spec = rule_interpreter.load_rules(Path(args.rules))
    filtered, disagreements = corpus.filter_to_agreement(raw, spec)
    Path(args.output).write_text(json.dumps(filtered, indent=2))
    print(f"corpus: {len(filtered['threads'])} agreeing threads → {args.output}")
    print(f"  ({raw_count - len(filtered['threads'])} threads dropped as disagreements)")
    if args.disagreements_output:
        Path(args.disagreements_output).write_text(json.dumps({
            "version": 1,
            "generated_at": raw["generated_at"],
            "disagreements": disagreements,
        }, indent=2))
        print(f"  disagreements → {args.disagreements_output}")
    return 0


def cmd_generate_apps_script(args: argparse.Namespace) -> int:
    rules_path = Path(args.rules)
    output_dir = Path(args.output_dir)
    if not output_dir.exists():
        print(f"output dir does not exist: {output_dir}", file=sys.stderr)
        return 1
    spec = rule_interpreter.load_rules(rules_path)
    summary = generate.write_apps_script(spec, output_dir)
    print(f"wrote {summary['rules_gs']} ({summary['rules_bytes']} bytes)")
    print(f"wrote {summary['classifier_gs']} ({summary['classifier_bytes']} bytes)")
    print(
        f"sender_rules={len(spec['sender_rules'])} "
        f"additive_subject_rules={len(spec['additive_subject_rules'])} "
        f"fallback_rules={len(spec['fallback_rules'])}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gmail_cleanup", description="Gmail mailbox cleanup helper")
    p.add_argument("--credentials", default="credentials.json")
    p.add_argument("--token", default="token.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover", help="Phase 1 — sample mailbox, dump discover.json")
    d.add_argument("--account", required=True, help="Email address being operated on (for the report)")
    d.add_argument("--output", default="discover.json")
    d.add_argument("--per-year-cap", type=int, default=100)
    d.add_argument("--max-total", type=int, default=1500)
    d.add_argument("--query", default="", help="Extra Gmail search query to constrain sample (e.g. '-label:Foo')")
    d.set_defaults(func=cmd_discover)

    pr = sub.add_parser("propose", help="Phase 2 — synthesize label tree from discover.json")
    pr.add_argument("--input", default="discover.json")
    pr.add_argument("--output", default="proposed_tree.json")
    pr.add_argument("--top-n", type=int, default=5, help="Max sub-labels per category")
    pr.add_argument("--min-count", type=int, default=3, help="Minimum messages from a single sender to earn a sub-label")
    pr.set_defaults(func=cmd_propose)

    cl = sub.add_parser("create-labels", help="Phase 2 lock-in — create missing labels in Gmail")
    cl.add_argument("--input", default="final_tree.json")
    cl.add_argument("--output", default="label_create_summary.json")
    cl.add_argument("--yes", action="store_true", help="Skip interactive confirmation")
    cl.set_defaults(func=cmd_create_labels)

    ap = sub.add_parser("apply", help="Phase 3 — apply labels at scale via batchModify")
    ap.add_argument("--queries", default="label_queries.json")
    ap.add_argument("--label-summary", default="label_create_summary.json")
    ap.add_argument("--progress", default="progress.json")
    ap.add_argument("--output", default="apply_summary.json")
    ap.add_argument("--yes", action="store_true")
    ap.set_defaults(func=cmd_apply)

    fl = sub.add_parser("flatten", help="Flatten all nested labels into flat leaves (destructive)")
    fl.add_argument("--output", default="flatten_summary.json")
    fl.add_argument("--yes", action="store_true")
    fl.set_defaults(func=cmd_flatten)

    ce = sub.add_parser("classify-export", help="Export unlabeled messages with subject+from+snippet for AI classification")
    ce.add_argument("--output", default="unlabeled_messages.json")
    ce.set_defaults(func=cmd_classify_export)

    ca = sub.add_parser("classify-apply", help="Apply a classification.json (produced from the export) via batchModify")
    ca.add_argument("--classification", required=True, help="Path to classification JSON: {message_id: [label_names]}")
    ca.add_argument("--dump", default="unlabeled_messages.json")
    ca.add_argument("--output", default="classify_apply_summary.json")
    ca.set_defaults(func=cmd_classify_apply)

    cm = sub.add_parser("cleanup-markers", help="Apply resolved +X/-X markers from feedback_resolved.json — adds/removes target labels, deletes marker labels")
    cm.add_argument("--input", default="feedback_resolved.json")
    cm.set_defaults(func=cmd_cleanup_markers)

    fs = sub.add_parser("feedback-scan", help="Scan Gmail for +X/-X marker labels and dump feedback.json for the autonomous loop")
    fs.add_argument("--output", default="feedback.json")
    fs.add_argument("--exit-zero-on-empty", action="store_true", help="Exit 0 (instead of 78) when no markers are found")
    fs.set_defaults(func=cmd_feedback_scan)

    cb = sub.add_parser("corpus-build", help="Sample stratified threads per user label, filter to interpreter-agreement, write the regression corpus JSON")
    cb.add_argument("--per-label", type=int, default=5, help="Number of threads to sample per label (default: 5)")
    cb.add_argument("--exclude", action="append", default=[], help="Additional label name to exclude from sampling (repeatable)")
    cb.add_argument("--output", default="tests/corpus.json")
    cb.add_argument("--rules", default="gmail_cleanup/rules.yaml", help="Rules YAML used for the agreement filter")
    cb.add_argument("--no-filter", action="store_true", help="Skip the interpreter-agreement filter (debug/inspection)")
    cb.add_argument("--disagreements-output", default="tests/corpus_disagreements.json", help="If set, also dump non-agreeing threads here for refinement work")
    cb.set_defaults(func=cmd_corpus_build)

    ga = sub.add_parser("generate-apps-script", help="Regenerate apps-script/Rules.gs and Classifier.gs from gmail_cleanup/rules.yaml")
    ga.add_argument("--rules", default="gmail_cleanup/rules.yaml")
    ga.add_argument("--output-dir", default="apps-script")
    ga.set_defaults(func=cmd_generate_apps_script)

    rl = sub.add_parser("rename-labels", help="Normalize label names to convention (lowercase, hyphenated, no punctuation)")
    rl.add_argument("--apply", action="store_true", help="Execute the plan (default: dry-run)")
    rl.add_argument("--yes", action="store_true", help="Skip interactive confirmation")
    rl.add_argument("--exclude", action="append", default=[], help="Additional label name to exclude from rename (repeatable)")
    rl.add_argument("--output", default=None, help="Write apply summary JSON to this path")
    rl.set_defaults(func=cmd_rename_labels)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

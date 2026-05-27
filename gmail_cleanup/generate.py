from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# Gmail search-query compilation (for Rules.gs)
# ---------------------------------------------------------------------------


def compile_gmail_query(match: dict) -> str:
    parts: list[str] = []
    for op, value in match.items():
        compiled = _compile_query_operator(op, value)
        if compiled:
            parts.append(compiled)
    return " ".join(parts)


def _compile_query_operator(op: str, value) -> str:
    if op == "from_contains":
        return f"from:{value}"
    if op == "from_contains_any":
        return _or_group("from", value)
    if op == "from_not_contains_any":
        return " ".join(f"-from:{v}" for v in value)
    if op == "subject_contains":
        return f"subject:{_quote_if_phrase(value)}"
    if op == "subject_contains_any":
        return _or_group("subject", value, quote_phrases=True)
    raise ValueError(f"operator {op!r} cannot be compiled to a Gmail query")


def _or_group(field: str, items, *, quote_phrases: bool = False) -> str:
    items = list(items)
    if len(items) == 1:
        v = _quote_if_phrase(items[0]) if quote_phrases else items[0]
        return f"{field}:{v}"
    rendered = [
        _quote_if_phrase(v) if quote_phrases else v for v in items
    ]
    return f"{field}:({' OR '.join(rendered)})"


def _quote_if_phrase(value: str) -> str:
    return f'"{value}"' if " " in value else value


# ---------------------------------------------------------------------------
# JS-condition compilation (for Classifier.gs)
# ---------------------------------------------------------------------------


def compile_js_condition(match: dict) -> str:
    parts: list[str] = []
    for op, value in match.items():
        parts.append(_compile_js_operator(op, value))
    if len(parts) == 1:
        return parts[0]
    return " && ".join(parts)


def _compile_js_operator(op: str, value) -> str:
    if op == "from_contains":
        return f"fromHas({_js_str(value)})"
    if op == "from_contains_any":
        return _js_or(f"fromHas", value)
    if op == "from_not_contains_any":
        inner = " && ".join(f"!fromHas({_js_str(v)})" for v in value)
        return f"({inner})"

    if op == "subject_contains":
        return f"subjHas({_js_str(value)})"
    if op == "subject_contains_any":
        return _js_or("subjHas", value)
    if op == "subject_not_contains_any":
        inner = " && ".join(f"!subjHas({_js_str(v)})" for v in value)
        return f"({inner})"
    if op == "subject_starts_with_any":
        if len(value) == 1:
            return f"(subject.trim().toLowerCase().startsWith({_js_str(value[0])}))"
        inner = " || ".join(
            f"subject.trim().toLowerCase().startsWith({_js_str(v)})" for v in value
        )
        return f"({inner})"
    if op == "subject_matches_regex":
        return f"/{value}/.test(subject)"

    if op == "snippet_contains":
        return f"snipHas({_js_str(value)})"
    if op == "snippet_contains_any":
        return _js_or("snipHas", value)

    if op == "text_contains_any":
        if len(value) == 1:
            return f"text.indexOf({_js_str(value[0])}) !== -1"
        inner = " || ".join(f"text.indexOf({_js_str(v)}) !== -1" for v in value)
        return f"({inner})"

    if op == "any_of":
        inner = " || ".join(compile_js_condition(m) for m in value)
        return f"({inner})"
    if op == "all_of":
        inner = " && ".join(compile_js_condition(m) for m in value)
        return f"({inner})"

    raise ValueError(f"operator {op!r} cannot be compiled to a JS condition")


def _js_or(fn: str, values) -> str:
    values = list(values)
    if len(values) == 1:
        return f"{fn}({_js_str(values[0])})"
    inner = " || ".join(f"{fn}({_js_str(v)})" for v in values)
    return f"({inner})"


def _js_str(s: str) -> str:
    escaped = s.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _js_labels_array(labels: list[str]) -> str:
    rendered = ", ".join(_js_str(l) for l in labels)
    return f"[{rendered}]"


# ---------------------------------------------------------------------------
# Full-file emission
# ---------------------------------------------------------------------------


_RULES_GS_BANNER = """\
// DO NOT EDIT — generated from gmail_cleanup/rules.yaml.
// Regenerate with: python -m gmail_cleanup generate-apps-script
//
// RULES — Phase 1 sender-based labelers; each rule's query targets
// `-has:userlabels` threads in organizeInbox().
// SUBJECT_RULES — Phase 2 additive subject overlays.
"""


_CLASSIFIER_GS_BANNER = """\
// DO NOT EDIT — generated from gmail_cleanup/rules.yaml.
// Regenerate with: python -m gmail_cleanup generate-apps-script
//
// Classifier — Phase 3 fallback for threads no sender or subject rule
// labeled. Returns an array of label names (empty = leave alone).
"""


def generate_rules_gs(spec: dict) -> str:
    lines = [_RULES_GS_BANNER, ""]

    lines.append("const RULES = [")
    for rule in spec["sender_rules"]:
        query = compile_gmail_query(rule["match"])
        labels = _js_labels_array(rule["labels"])
        desc = rule.get("description")
        if desc:
            lines.append(f"  // {desc}")
        lines.append(f"  {{ id: {_js_str(rule['id'])}, query: {_js_str(query)}, labels: {labels} }},")
    lines.append("];")
    lines.append("")

    lines.append("const SUBJECT_RULES = [")
    for rule in spec["additive_subject_rules"]:
        query = compile_gmail_query(rule["match"])
        labels = _js_labels_array(rule["labels"])
        desc = rule.get("description")
        if desc:
            lines.append(f"  // {desc}")
        lines.append(f"  {{ id: {_js_str(rule['id'])}, query: {_js_str(query)}, labels: {labels} }},")
    lines.append("];")
    lines.append("")

    return "\n".join(lines)


def generate_classifier_gs(spec: dict) -> str:
    lines = [_CLASSIFIER_GS_BANNER, ""]
    lines.append("function classifyThread_(thread) {")
    lines.append("  let from = '';")
    lines.append("  let subject = '';")
    lines.append("  let snippet = '';")
    lines.append("  try {")
    lines.append("    const msg = thread.getMessages()[0];")
    lines.append("    from = (msg.getFrom() || '').toLowerCase();")
    lines.append("    subject = (msg.getSubject() || '').toLowerCase();")
    lines.append("    snippet = (msg.getPlainBody() || '').slice(0, 300).toLowerCase();")
    lines.append("  } catch (e) {")
    lines.append("    console.warn('[classifyThread_] failed to read thread:', e);")
    lines.append("    return [];")
    lines.append("  }")
    lines.append("")
    lines.append("  const text = from + ' || ' + subject + ' || ' + snippet;")
    lines.append("  const fromHas = s => from.indexOf(s.toLowerCase()) !== -1;")
    lines.append("  const subjHas = s => subject.indexOf(s.toLowerCase()) !== -1;")
    lines.append("  const snipHas = s => snippet.indexOf(s.toLowerCase()) !== -1;")
    lines.append("")

    for rule in spec["fallback_rules"]:
        labels_array = _js_labels_array(rule["labels"])
        desc = rule.get("description")
        if desc:
            lines.append(f"  // {desc}")
        match = rule.get("match")
        if match is None:
            lines.append(f"  return {labels_array};  // {rule['id']}")
        else:
            cond = compile_js_condition(match)
            lines.append(f"  // {rule['id']}")
            lines.append(f"  if ({cond}) return {labels_array};")
        lines.append("")

    # If no trailing default rule, return [] as a safety net.
    if not spec["fallback_rules"] or spec["fallback_rules"][-1].get("match") is not None:
        lines.append("  return [];")

    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def write_apps_script(spec: dict, output_dir: Path) -> dict:
    rules_path = output_dir / "Rules.gs"
    classifier_path = output_dir / "Classifier.gs"
    rules_text = generate_rules_gs(spec)
    classifier_text = generate_classifier_gs(spec)
    rules_path.write_text(rules_text)
    classifier_path.write_text(classifier_text)
    return {
        "rules_gs": str(rules_path),
        "classifier_gs": str(classifier_path),
        "rules_bytes": len(rules_text),
        "classifier_bytes": len(classifier_text),
    }

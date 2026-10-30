#!/usr/bin/env python3
"""PR check (right side): code overlap and scope drift.

Usage:
  pr_check.py --index <dir> --changed <file> --branch <name> [--open-prs <json>]
              [--root .] [--base-root <dir>]

Maps the PR's changed files to index components, then reports:
  - impact records changed in the PR, their validation errors and their register overlaps
  - the components the PR changes, plus unmapped files (never a finding)
  - scope: components outside the story's committed impact record (finding outOfScope),
    or no story id / no impact on record while code changes (finding noImpact)
  - other open PRs that touch the same components

--root is the PR head; changed impacts/*/impact.json files are read from it.
--base-root (default: --root) is the base branch checkout; .ai-framework.json and the
register (scope and overlaps) come from it, so a PR cannot change its own settings or
add a record that covers its own code.

--changed holds repo-relative paths, one per line. --open-prs holds the output of
`gh pr list --json number,headRefName,files`; a missing file means no section.
Finding classes are comments unless .ai-framework.json sets
{"impactChecks": {"noImpact": "fail", "outOfScope": "fail"}}.

Every value taken from input is printed through code_span(), which makes it inert
markdown: one line, bounded length, inside a code span nothing in it can close.

Prints markdown on stdout and writes no files.
Exit codes: 0 ok, 1 a finding set to fail, 2 bad usage.
Stdlib only. Data comes from --root and --base-root; code never does. Offline.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools", "index"))

from register import load_register, overlaps, register_commit, scope  # noqa: E402
from validate import STORY_RE, validate  # noqa: E402
from query import load  # noqa: E402

# Matches only [A-Z][A-Z0-9]*-[0-9]+, so a story id found this way is safe to print as is.
STORY_SEARCH = re.compile(STORY_RE.pattern.lstrip("^").rstrip("$"))
IMPACT_PATH_RE = re.compile(r"^impacts/[^/]+/impact\.json$")
SETTING_KEYS = ("noImpact", "outOfScope")
SETTING_VALUES = ("comment", "fail")
BUNDLE_TYPES = {"lwc": "LightningComponentBundle", "aura": "AuraDefinitionBundle"}
MAX_VALUE = 200
# C0/C1 controls, DEL, and Unicode line/paragraph separators.
_CONTROL_RE = re.compile("[\x00-\x1f\x7f-\x9f  ]+")
_SPACES_RE = re.compile(" {2,}")
_TICKS_RE = re.compile("`+")
JSON_ERRORS = (OSError, ValueError, RecursionError, MemoryError)


def code_span(value):
    """Render an input value as one inert inline code span.

    Control characters (newlines included) become one space, the value is cut to
    MAX_VALUE characters with an ellipsis, and the fence is one backtick longer than the
    longest backtick run inside, so nothing in the value can close the span early.
    Inside a code span, markdown and HTML (`<!--`, `<details>`) are not parsed.
    """
    text = _CONTROL_RE.sub(" ", str(value))
    text = _SPACES_RE.sub(" ", text).strip()
    if len(text) > MAX_VALUE:
        text = text[:MAX_VALUE].rstrip() + "…"
    if not text:
        return "(empty)"
    longest = max((len(m) for m in _TICKS_RE.findall(text)), default=0)
    fence = "`" * (longest + 1)
    if text.startswith("`") or text.endswith("`"):
        text = " %s " % text
    return "%s%s%s" % (fence, text, fence)


def _norm(path):
    return path.strip().replace("\\", "/") if isinstance(path, str) else ""


def _paths(paths):
    out = []
    for p in paths:
        n = _norm(p)
        if n:
            out.append(n)
    return out


def _path_map(idx):
    result = {}
    for api, node in idx.get("nodes", {}).items():
        p = node.get("path") if isinstance(node, dict) else None
        if isinstance(p, str) and p:
            result.setdefault(p, set()).add(api)
    return result


def nodes_for_path(idx, path, _pmap=None):
    """Index node apis for one repo-relative path; an empty set when unmapped."""
    pmap = _pmap if _pmap is not None else _path_map(idx)
    path = _norm(path)
    if path in pmap:
        return set(pmap[path])
    if path.endswith("-meta.xml"):
        stripped = path[: -len("-meta.xml")]
        if stripped in pmap:
            return set(pmap[stripped])
    parts = path.split("/")
    nodes = idx.get("nodes", {})
    for i, part in enumerate(parts):
        if part in BUNDLE_TYPES and i + 2 < len(parts):
            bundle = parts[i + 1]
            node = nodes.get(bundle)
            if not isinstance(node, dict) or node.get("type") != BUNDLE_TYPES[part]:
                continue
            npath = node.get("path")
            if isinstance(npath, str) and path.startswith(npath + "/"):
                return {bundle}
    return set()


def story_from_branch(branch):
    """The first story id in a branch name, or None."""
    m = STORY_SEARCH.search(branch or "")
    return m.group(0) if m else None


def load_settings(root):
    """{"noImpact": ..., "outOfScope": ...}, each comment or fail; ValueError otherwise."""
    settings = {k: "comment" for k in SETTING_KEYS}
    path = os.path.join(root, ".ai-framework.json")
    if not os.path.isfile(path):
        return settings
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (RecursionError, MemoryError) as exc:
        raise ValueError(".ai-framework.json cannot be read: %s" % type(exc).__name__)
    if not isinstance(data, dict):
        raise ValueError(".ai-framework.json is not a JSON object")
    checks = data.get("impactChecks")
    if checks is None:
        return settings
    if not isinstance(checks, dict):
        raise ValueError(".ai-framework.json: impactChecks is not an object")
    for k in SETTING_KEYS:
        if k in checks:
            if checks[k] not in SETTING_VALUES:
                raise ValueError(".ai-framework.json: impactChecks.%s %s is not one of %s"
                                 % (k, code_span(checks[k]), ", ".join(SETTING_VALUES)))
            settings[k] = checks[k]
    return settings


def _apis(apis):
    return ", ".join(code_span(a) for a in sorted(apis))


def _story_entry(s):
    return "%s (squad %s, %s, %s, commit %s)" % (
        code_span(s.get("storyId")), code_span(s.get("squad")), code_span(s.get("changeType")),
        code_span(s.get("status")), code_span(s.get("commit")))


def _impact_section(root, impact_paths, register_impacts):
    lines = []
    for rel in sorted(set(impact_paths)):
        full = os.path.join(root, rel)
        if not os.path.isfile(full):
            lines.append("- %s: removed in this PR" % code_span(rel))
            continue
        try:
            with open(full, encoding="utf-8") as fh:
                doc = json.load(fh)
        except JSON_ERRORS as exc:
            lines.append("- %s: unreadable: %s" % (code_span(rel), code_span(
                "%s: %s" % (type(exc).__name__, exc))))
            continue
        errs = validate(doc, "promoted", root)
        found = overlaps(doc, register_impacts) if isinstance(doc, dict) else []
        story = doc.get("storyId") if isinstance(doc, dict) else None
        lines.append("- %s (story %s)" % (code_span(rel), code_span(story)
                                           if story is not None else "unknown"))
        if errs:
            lines.append("  - Validation errors:")
            lines.extend("    - %s" % code_span(e) for e in errs)
        for o in found:
            others = "; ".join(_story_entry(s) for s in o["stories"])
            lines.append("  - %s: %s (%s) with %s" % (o["kind"], code_span(o["api"]),
                                                      code_span(o["type"]), others))
        if not errs and not found:
            lines.append("  - Valid; no overlaps with the register.")
    return lines


def _pr_number(n):
    return "#%d" % n if isinstance(n, int) and not isinstance(n, bool) else code_span(n)


def _pr_sort_key(pr):
    n = pr.get("number")
    return (0, n, "") if isinstance(n, int) and not isinstance(n, bool) else (1, 0, str(n))


def report(root, idx, changed, branch, open_prs, base_root=None):
    """Return (markdown, fail) for one PR.

    root is the PR head (changed impact records are read from it); base_root, default
    root, supplies .ai-framework.json and the register.
    """
    base = base_root if base_root is not None else root
    settings = load_settings(base)
    reg = load_register(base)
    pmap = _path_map(idx)
    paths = sorted(set(_paths(changed)))

    impact_paths = [p for p in paths if IMPACT_PATH_RE.match(p)]
    touched, unmapped = set(), []
    for p in paths:
        if p in impact_paths:
            continue
        hit = nodes_for_path(idx, p, pmap)
        if hit:
            touched |= hit
        else:
            unmapped.append(p)

    findings = {}
    out = ["## PR impact check", "",
           "Register commit: %s. Index commit: %s. Branch: %s."
           % (code_span(register_commit(base)),
              code_span((idx.get("stamp") or {}).get("commit", "unknown")), code_span(branch))]

    impact_lines = _impact_section(root, impact_paths, reg["impacts"])
    if impact_lines:
        out += ["", "### Impact records in this PR", ""] + impact_lines

    if touched or unmapped:
        out += ["", "### Components this PR changes", ""]
        nodes = idx.get("nodes", {})
        for api in sorted(touched):
            out.append("- %s (%s)" % (code_span(api), code_span(nodes.get(api, {}).get("type"))))
        if unmapped:
            if touched:
                out.append("")
            out.append("Unmapped files (no index component):")
            out.extend("- %s" % code_span(p) for p in unmapped)

    if touched:
        story = story_from_branch(branch)
        out += ["", "### Scope", ""]
        on_record = scope(story, reg["impacts"]) if story else None
        if story is None:
            out.append("No story id in branch %s" % code_span(branch))
            findings["noImpact"] = True
        elif on_record is None:
            out.append("No impact on record for %s" % story)
            findings["noImpact"] = True
        else:
            outside = sorted(touched - set(on_record["components"]))
            out.append("Story %s (squad %s, status %s)."
                       % (story, code_span(on_record["squad"]), code_span(on_record["status"])))
            if outside:
                out.append("")
                out.append("Components outside the impact record for %s:" % story)
                out.extend("- %s" % code_span(a) for a in outside)
                findings["outOfScope"] = True
            else:
                out.append("All components this PR changes are in the impact record for %s."
                           % story)
        for k in SETTING_KEYS:
            if findings.get(k):
                out += ["", "Finding `%s` (set to %s)." % (k, settings[k])]

    pr_lines = []
    for pr in sorted(open_prs or [], key=_pr_sort_key):
        head = pr.get("headRefName")
        head = head if isinstance(head, str) else ""
        if head == branch:
            continue
        theirs = set()
        files = pr.get("files")
        for f in files if isinstance(files, list) else []:
            p = _norm(f.get("path") if isinstance(f, dict) else None)
            if p:
                theirs |= nodes_for_path(idx, p, pmap)
        shared = touched & theirs
        if not shared:
            continue
        sid = story_from_branch(head)
        pr_lines.append("- %s %s (story %s): %s"
                        % (_pr_number(pr.get("number")), code_span(head), sid or "none",
                           _apis(shared)))
    if pr_lines:
        out += ["", "### Other open PRs touching the same components", ""] + pr_lines

    failing = sorted(k for k in SETTING_KEYS if findings.get(k) and settings[k] == "fail")
    out.append("")
    if failing:
        out.append("Set to fail by .ai-framework.json: %s" % ", ".join(failing))
    else:
        out.append("Findings only; a reviewer decides.")
    return "\n".join(out) + "\n", bool(failing)


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv=None):
    ap = argparse.ArgumentParser(description="PR check: code overlap and scope drift.")
    ap.add_argument("--index", required=True)
    ap.add_argument("--changed", required=True)
    ap.add_argument("--branch", required=True)
    ap.add_argument("--open-prs")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--base-root")
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    base_root = args.base_root if args.base_root is not None else args.root
    if not os.path.isdir(base_root):
        print("--base-root %s is not a directory" % base_root, file=sys.stderr)
        return 2
    try:
        idx = load(args.index)
    except JSON_ERRORS as exc:
        print("cannot read index from %s: %s" % (args.index, type(exc).__name__),
              file=sys.stderr)
        return 2
    if not isinstance(idx, dict) or not isinstance(idx.get("nodes"), dict):
        print("%s: index has no nodes object" % args.index, file=sys.stderr)
        return 2
    try:
        with open(args.changed, encoding="utf-8") as fh:
            changed = fh.read().splitlines()
    except (OSError, ValueError) as exc:
        print("cannot read %s: %s" % (args.changed, exc), file=sys.stderr)
        return 2
    open_prs = []
    if args.open_prs and os.path.isfile(args.open_prs):
        try:
            open_prs = _read_json(args.open_prs)
        except JSON_ERRORS as exc:
            print("cannot read JSON from %s: %s" % (args.open_prs, type(exc).__name__),
                  file=sys.stderr)
            return 2
        if not isinstance(open_prs, list) or not all(isinstance(p, dict) for p in open_prs):
            print("%s: not a list of PR objects" % args.open_prs, file=sys.stderr)
            return 2
    try:
        md, fail = report(args.root, idx, changed, args.branch, open_prs, base_root)
    except (OSError, ValueError, RecursionError, MemoryError) as exc:
        print("%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2
    sys.stdout.write(md)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())

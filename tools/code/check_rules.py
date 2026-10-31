#!/usr/bin/env python3
"""Deterministic Apex rule checks, with a baseline that records the findings already in the code.

Usage:
  check_rules.py [--root <repo>] [--source-root <dir>] [--baseline <file>] [--write-baseline]
                 [--compare-baseline <file>]
  check_rules.py --from-config [--baseline <file>] [--write-baseline] [--compare-baseline <file>]

--root defaults to this checkout (computed from this file's location, never the cwd). --source-root
defaults to sourceRoot in <root>/.ai-framework.json and must resolve inside --root. --from-config
reads the checkout's own config and scans its sourceRoot; it exits 2 when combined with --root or
--source-root. With no flag at all the run is the same as --from-config.
--baseline defaults to <root>/tools/code/baseline.json. A missing baseline means no entries.
--write-baseline writes every current finding to the baseline (sorted, "\\n" endings, byte-identical
across runs). It refuses a target outside --root or one that passes through a symlink.
--compare-baseline <file> also compares the baseline with <file> (a base branch's copy) and lists
under "added" every entry the baseline holds that <file> lacks. The baseline only shrinks. A
relative <file>, like a relative --baseline, resolves against --root.

Rules (ids as named in framework/rules/10-apex.md), applied to .cls and .trigger files under
force-app/ and pkg-*/ of the source root, with comments and '...' strings blanked first by
build_index.blank_apex (loaded from this checkout):
  apex-sharing              a class declaration without with, without or inherited sharing; or
                            without sharing with no comment on the 3 lines above the declaration
                            (or on the declaration's own lines), read from the raw source
  apex-user-mode            [SELECT ...] without WITH USER_MODE (WITH SYSTEM_MODE passes with a
                            comment); WITH SECURITY_ENFORCED anywhere; insert/update/delete/upsert/
                            merge/undelete statements without "as user", and Database DML calls
                            without AccessLevel.USER_MODE ("as system" and AccessLevel.SYSTEM_MODE
                            pass with a comment). Not applied inside an @IsTest class: test
                            data setup runs in system mode.
  apex-no-soql-dml-in-loop  [SELECT ...] or DML lexically inside a braced for, while or do body.
                            A SOQL for-loop header, for (X x : [SELECT ...]), is not in the body.
  apex-no-system-debug      System.debug(
  apex-no-seealldata        SeeAllData=true
  apex-no-assert-true       System.assert(true or Assert.isTrue(true
  apex-test-naming          an @IsTest class whose name does not end _Test

A baseline entry is {rule, path, hash}: hash is the sha1 of the stripped line text, then "#<n>",
n counting the earlier lines of the file that carry a finding of the same rule with the same
stripped text (a compliant identical line does not count). Moving a line keeps its entry;
editing it makes the finding new.

Prints JSON {findings, new, baselined, notes} (plus "added" with --compare-baseline). Each finding
is {rule, path, line, text}, path relative to --root. Exit codes: 0 nothing new, 1 a new finding
or (with --compare-baseline) a grown baseline, 2 bad usage, an invalid config or baseline, or an
unsafe write. There is deliberately no flag or env var that chooses which code this loads.
Stdlib only. Offline. Writes only with --write-baseline.
"""
import argparse
import bisect
import hashlib
import importlib.util
import json
import os
import re
import sys

CHECKOUT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(CHECKOUT, "tools", "config"))
import framework_config  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


build_index = _load("build_index", os.path.join(CHECKOUT, "tools", "index", "build_index.py"))

RULE_IDS = ("apex-sharing", "apex-user-mode", "apex-no-soql-dml-in-loop", "apex-no-system-debug",
            "apex-no-seealldata", "apex-no-assert-true", "apex-test-naming")
BASELINE_REL = "tools/code/baseline.json"
BASELINE_VERSION = 1
COMMENT_WINDOW = 3
NOTES = [
    "SOQL/DML-in-loop detection is narrow and may miss cases: it sees only [SELECT ...], DML "
    "statements and Database DML calls written inside a braced for, while or do body. Loops "
    "without braces, calls into other methods and dynamic SOQL are not followed.",
    "Comments and '...' strings are ignored. Each finding is one rule on one line.",
]

_CLASS = re.compile(r"\bclass\s+([A-Za-z_][A-Za-z0-9_]*)", re.I)
_SHARING = re.compile(r"\b(with|without|inherited)\s+sharing\b", re.I)
_ISTEST = re.compile(r"@isTest\b", re.I)
_SOQL = re.compile(r"\[\s*select\b", re.I)
_USER_MODE = re.compile(r"\bwith\s+user_mode\b", re.I)
_SYSTEM_MODE = re.compile(r"\bwith\s+system_mode\b", re.I)
_SECURITY_ENFORCED = re.compile(r"\bwith\s+security_enforced\b", re.I)
_DML_WORD = re.compile(r"\b(insert|update|delete|upsert|merge|undelete)\b", re.I)
_DATABASE_DML = re.compile(r"\bDatabase\s*\.\s*(insert|update|delete|upsert|merge|undelete)\s*\(", re.I)
_ACCESS_USER = re.compile(r"\bAccessLevel\s*\.\s*USER_MODE\b", re.I)
_ACCESS_SYSTEM = re.compile(r"\bAccessLevel\s*\.\s*SYSTEM_MODE\b", re.I)
_LOOP = re.compile(r"\b(for|while)\s*\(", re.I)
_DO = re.compile(r"\bdo\s*\{", re.I)
_DEBUG = re.compile(r"\bSystem\s*\.\s*debug\s*\(", re.I)
_SEEALLDATA = re.compile(r"\bSeeAllData\s*=\s*true\b", re.I)
_ASSERT_TRUE = re.compile(r"\b(?:System\s*\.\s*assert|Assert\s*\.\s*isTrue)\s*\(\s*true\s*[,)]", re.I)


class Usage(Exception):
    """Bad usage, an invalid config or baseline, or an unsafe write; exit 2."""


# ---- scanning one file -------------------------------------------------------------------------

def _match(code, start, open_ch, close_ch):
    """Offset just past the close_ch that balances the open_ch at start (len(code) if unbalanced)."""
    depth = 0
    for i in range(start, len(code)):
        ch = code[i]
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
    return len(code)


def _comment_lines(src):
    """0-based indexes of the lines that hold any part of a comment, found with the same pattern
    blank_apex uses, so a quote inside a comment or // inside a string is read the same way."""
    lines = set()
    for m in build_index._APEX_LITERALS.finditer(src):
        if m.group(0).startswith("/"):
            first = src.count("\n", 0, m.start())
            lines.update(range(first, first + m.group(0).count("\n") + 1))
    return lines


def check_file(path, src):
    """[{rule, path, line, text}] for one Apex source, sorted by line then rule."""
    code = build_index.blank_apex(src)
    raw_lines = src.split("\n")
    comments = _comment_lines(src)
    starts = [0] + [i + 1 for i, ch in enumerate(code) if ch == "\n"]
    found = set()

    def line(offset):
        return bisect.bisect_right(starts, offset)

    def commented(first, last):
        """A comment on lines first-COMMENT_WINDOW .. last (1-based, inclusive), in the raw source."""
        return any(i in comments for i in range(max(0, first - 1 - COMMENT_WINDOW), last))

    # Class declarations: sharing and test naming; @IsTest class spans for the user-mode exemption.
    tests = []  # (start, end)
    for m in _CLASS.finditer(code):
        before = code[:m.start()].rstrip()
        if before.endswith("."):
            continue  # X.class
        cut = max(before.rfind(";"), before.rfind("{"), before.rfind("}")) + 1
        prefix = code[cut:m.start()]
        head = cut + len(prefix) - len(prefix.lstrip())
        decl_first, decl_line = line(head), line(m.start())
        sharing = _SHARING.search(prefix)
        if sharing is None:
            found.add(("apex-sharing", decl_line))
        elif sharing.group(1).lower() == "without" and not commented(decl_first, decl_line):
            found.add(("apex-sharing", decl_line))
        if _ISTEST.search(prefix):
            if not m.group(1).endswith("_Test"):
                found.add(("apex-test-naming", decl_line))
            brace = code.find("{", m.end())
            tests.append((head, _match(code, brace, "{", "}") if brace >= 0 else len(code)))

    def user_mode(offset):
        """apex-user-mode does not apply inside an @IsTest class: test data setup runs in system mode."""
        if not any(s <= offset < e for s, e in tests):
            found.add(("apex-user-mode", line(offset)))

    # SOQL.
    soql = []  # (start, end)
    for m in _SOQL.finditer(code):
        end = _match(code, m.start(), "[", "]")
        soql.append((m.start(), end))
        query = code[m.start():end]
        if _SECURITY_ENFORCED.search(query) or _USER_MODE.search(query):
            continue
        if _SYSTEM_MODE.search(query) and commented(line(m.start()), line(end - 1)):
            continue
        user_mode(m.start())
    for m in _SECURITY_ENFORCED.finditer(code):
        user_mode(m.start())

    def in_soql(offset):
        return any(s <= offset < e for s, e in soql)

    # DML statements and Database DML calls.
    dml = []  # offsets
    for m in _DML_WORD.finditer(code):
        if in_soql(m.start()):
            continue
        before = code[:m.start()].rstrip()
        if before and before[-1] not in ";{})" and not re.search(r"\belse$", before, re.I):
            continue
        rest = code[m.end():]
        nxt = rest.lstrip()[:1]
        if not nxt or not (nxt.isalnum() or nxt in "_(["):
            continue  # update = 1; a declaration or an expression, not a statement
        semi = code.find(";", m.end())
        stmt = code[m.end(): semi if semi >= 0 else len(code)]
        dml.append(m.start())
        if re.match(r"\s*as\s+user\b", stmt, re.I):
            continue
        if re.match(r"\s*as\s+system\b", stmt, re.I) and commented(line(m.start()), line(m.start())):
            continue
        user_mode(m.start())
    for m in _DATABASE_DML.finditer(code):
        end = _match(code, m.end() - 1, "(", ")")
        args = code[m.end() - 1:end]
        dml.append(m.start())
        if _ACCESS_USER.search(args):
            continue
        if _ACCESS_SYSTEM.search(args) and commented(line(m.start()), line(end - 1)):
            continue
        user_mode(m.start())

    # Loop bodies: the braced block right after a for/while header, or after do.
    bodies = []
    for m in _LOOP.finditer(code):
        if in_soql(m.start()):
            continue
        close = _match(code, m.end() - 1, "(", ")")
        j = close
        while j < len(code) and code[j].isspace():
            j += 1
        if j < len(code) and code[j] == "{":
            bodies.append((j, _match(code, j, "{", "}")))
    for m in _DO.finditer(code):
        brace = m.end() - 1
        bodies.append((brace, _match(code, brace, "{", "}")))
    for offset in [s for s, _ in soql] + dml:
        if any(s < offset < e for s, e in bodies):
            found.add(("apex-no-soql-dml-in-loop", line(offset)))

    for pattern, rule in ((_DEBUG, "apex-no-system-debug"), (_SEEALLDATA, "apex-no-seealldata"),
                          (_ASSERT_TRUE, "apex-no-assert-true")):
        for m in pattern.finditer(code):
            found.add((rule, line(m.start())))

    return [{"rule": rule, "path": path, "line": n, "text": raw_lines[n - 1].strip()}
            for rule, n in sorted(found, key=lambda t: (t[1], t[0]))]


# ---- scanning a tree and the baseline ----------------------------------------------------------

def _inside(top, path):
    return os.path.commonpath([top, path]) == top


def scan(root, source_root):
    """Findings for every .cls and .trigger under force-app/ and pkg-*/ of source_root (absolute,
    or relative to root), sorted by path, line and rule. Paths are relative to root."""
    top = os.path.realpath(root)
    src = os.path.realpath(source_root if os.path.isabs(source_root) else os.path.join(top, source_root))
    if not _inside(top, src):
        raise ValueError("source root %s resolves outside the root %s" % (source_root, top))
    findings = []
    if not os.path.isdir(src):
        return findings
    for path in build_index.walk(src):
        if not path.endswith((".cls", ".trigger")) or os.path.islink(path):
            continue
        rel = os.path.relpath(os.path.realpath(path), top).replace(os.sep, "/")
        if rel.startswith("../"):
            continue
        findings.extend(check_file(rel, build_index.read_src(path)))
    return sorted(findings, key=lambda f: (f["path"], f["line"], f["rule"]))


def finding_key(f, src_lines, findings=None):
    """The baseline entry {rule, path, hash} of a finding, given its file's lines. n counts only
    the earlier lines that carry a finding of the same rule with the same stripped text, so a
    compliant line with identical text never shifts a legacy entry. `findings` is the file's
    findings; when omitted it is computed with check_file."""
    if findings is None:
        findings = check_file(f["path"], "\n".join(src_lines))
    text = src_lines[f["line"] - 1].strip()
    same = {g["line"] for g in findings if g["rule"] == f["rule"] and g["path"] == f["path"]}
    n = sum(1 for i in same if i < f["line"] and src_lines[i - 1].strip() == text)
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return {"rule": f["rule"], "path": f["path"], "hash": "%s#%d" % (digest, n)}


def _sort_entries(entries):
    unique = {(e["path"], e["rule"], e["hash"]): e for e in entries}
    return [{"rule": unique[k]["rule"], "path": k[0], "hash": k[2]} for k in sorted(unique)]


def baseline_entries(root, findings):
    """Sorted, unique baseline entries for findings whose paths are relative to root."""
    return _sort_entries(_keyed(os.path.realpath(root), findings))


def baseline_text(entries):
    """The baseline file's exact content."""
    return json.dumps({"version": BASELINE_VERSION, "entries": _sort_entries(entries)},
                      indent=1, sort_keys=True) + "\n"


def read_baseline(path, missing_ok):
    """Entries of a baseline file; Usage when it is invalid, or missing and not missing_ok."""
    if not os.path.isfile(path):
        if missing_ok and not os.path.lexists(path):
            return []
        raise Usage("baseline %s is not a readable file" % path)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError, RecursionError) as exc:
        raise Usage("baseline %s cannot be read: %s" % (path, type(exc).__name__))
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("version") != BASELINE_VERSION or not isinstance(entries, list):
        raise Usage("baseline %s is not {\"version\": %d, \"entries\": [...]}" % (path, BASELINE_VERSION))
    for e in entries:
        if not (isinstance(e, dict) and all(isinstance(e.get(k), str) for k in ("rule", "path", "hash"))):
            raise Usage("baseline %s holds an entry that is not {rule, path, hash}" % path)
    return [{"rule": e["rule"], "path": e["path"], "hash": e["hash"]} for e in entries]


def _key(e):
    return (e["rule"], e["path"], e["hash"])


def safe_target(top, path):
    """Absolute path of a write target under top; Usage when it resolves outside top or an
    existing component below top is a symlink."""
    raw = os.path.abspath(path if os.path.isabs(path) else os.path.join(top, path))
    if not _inside(top, raw):
        raise Usage("%s resolves outside the root %s" % (path, top))
    cur = top
    for part in os.path.relpath(raw, top).split(os.sep):
        if part in ("", "."):
            continue
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            raise Usage("%s passes through a symlink at %s" % (path, os.path.relpath(cur, top)))
    if os.path.lexists(cur) and not os.path.isfile(cur):
        raise Usage("%s exists and is not a regular file" % path)
    return cur


# ---- CLI ---------------------------------------------------------------------------------------

def parse(argv):
    ap = argparse.ArgumentParser(description="Deterministic Apex rule checks with a baseline.")
    ap.add_argument("--root", default=None)
    ap.add_argument("--source-root", default=None)
    ap.add_argument("--from-config", action="store_true")
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--compare-baseline", default=None)
    return ap.parse_args(argv)


def run(args):
    if args.from_config and (args.root is not None or args.source_root is not None):
        raise Usage("--from-config reads the checkout's own config; it takes no --root or --source-root")
    top = os.path.realpath(CHECKOUT if args.root is None else args.root)
    if not os.path.isdir(top):
        raise Usage("--root %s is not a directory" % args.root)
    try:
        if args.source_root is None:
            source = framework_config.source_root(top)
        else:
            source = os.path.realpath(args.source_root if os.path.isabs(args.source_root)
                                      else os.path.join(top, args.source_root))
            if not _inside(top, source):
                raise ValueError("--source-root %s resolves outside the root %s" % (args.source_root, top))
            if not os.path.isdir(source):
                raise ValueError("--source-root %s is not a directory" % args.source_root)
        findings = scan(top, source)
    except ValueError as exc:
        raise Usage(str(exc))
    baseline_arg = args.baseline if args.baseline is not None else BASELINE_REL
    baseline = os.path.abspath(baseline_arg if os.path.isabs(baseline_arg) else os.path.join(top, baseline_arg))
    entries = baseline_entries(top, findings)

    if args.write_baseline:
        target = safe_target(top, baseline)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(baseline_text(entries))
    recorded = read_baseline(baseline, missing_ok=True)
    known = {_key(e) for e in recorded}
    new, baselined = [], []
    for f, e in zip(_keyed(top, findings), findings):
        (baselined if _key(f) in known else new).append(e)
    current = {_key(e) for e in entries}
    notes = ["Scanned %s against %s." % (_show(top, source) or ".", _show(top, baseline))] + NOTES
    stale = sum(1 for e in recorded if _key(e) not in current)
    if stale:
        notes.append("%d baseline entries match no current finding; --write-baseline drops them." % stale)
    out = {"findings": findings, "new": new, "baselined": baselined, "notes": notes}
    grown = False
    if args.compare_baseline is not None:
        cmp_arg = args.compare_baseline
        base_path = os.path.abspath(cmp_arg if os.path.isabs(cmp_arg) else os.path.join(top, cmp_arg))
        base = {_key(e) for e in read_baseline(base_path, missing_ok=False)}
        out["added"] = [e for e in recorded if _key(e) not in base]
        grown = bool(out["added"])
        notes.append("Compared %s with %s; \"added\" lists the entries %s lacks."
                     % (_show(top, baseline), args.compare_baseline, args.compare_baseline))
    print(json.dumps(out, indent=1, sort_keys=True))
    return 1 if new or grown else 0


def _keyed(top, findings):
    """Baseline entries in the same order as findings (not deduplicated)."""
    lines, by_path, out = {}, {}, []
    for f in findings:
        by_path.setdefault(f["path"], []).append(f)
    for f in findings:
        if f["path"] not in lines:
            lines[f["path"]] = build_index.read_src(os.path.join(top, f["path"])).split("\n")
        out.append(finding_key(f, lines[f["path"]], by_path[f["path"]]))
    return out


def _show(top, path):
    rel = os.path.relpath(path, top).replace(os.sep, "/")
    return "" if rel == "." else rel


def main(argv=None):
    try:
        args = parse(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        return run(args)
    except Usage as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

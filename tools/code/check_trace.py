#!/usr/bin/env python3
"""Test traceability for one story's build package: does every criterion have a test that names it?

Usage:
  check_trace.py [--skeletons] <storyId> [--root <repo>]

The package is the single impacts/<storyId>-*/build-package.json in the --root work tree (default: this
checkout). Only files listed in scope.tests count as tests; a file counts by membership, never by its name.

  --skeletons   every criteria[].id is referenced by at least one scope.tests file that exists
  (full)        the same, plus no AC-n / EC-n reference that the package does not hold, plus every scope.tests
                file that exists references at least one criterion id
Files ending -meta.xml are metadata companions and cannot carry ids: an id found only in one covers no
criterion (both modes), and they are exempt from the "references at least one id" rule.

Matching lives in the guard-owned core, <checkout>/tools/guard/trace_core.py, loaded by a path computed from this
file, so this check and the guard's tests-first rule are one implementation. There is deliberately no flag or env
var to load another core: build mode may run this script, and a selectable core would run unseen code. Tests pass
a stub through main(argv, core_path=...). Matching is structural: an id in a comment counts.

Before matching, criteria[] goes through the core's criteria_problem, the rule the guard applies to the committed
package: non-empty, ids AC-<n> / EC-<n>, no duplicates. A failure prints the finding on stderr and exits 1.

Prints JSON on stdout. Exit codes: 0 no gaps, 1 gaps found or invalid criteria, 2 bad usage or nothing to check (bad storyId, zero
or several package folders, an unreadable package, a scope.tests path outside the repo, or a missing core).
Stdlib only. Offline. Writes nothing.
"""
import argparse
import glob
import importlib.util
import json
import os
import re
import sys

CHECKOUT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_CORE = os.path.join(CHECKOUT, "tools", "guard", "trace_core.py")
STORY_RE = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]+$")
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MISSING_CORE = "trace core not found at %s; apply the WS8 guard patch (ai-context/ws8/patches)"
CORE_API = ("read_tests", "criteria_problem", "missing_criteria", "unknown_refs")
META_SUFFIX = "-meta.xml"


class Unusable(Exception):
    """Nothing can be checked; exit 2."""


class Invalid(Exception):
    """The package's criteria fail the core's validation (empty, not AC-n / EC-n, or duplicate ids); exit 1."""


def load_core(path):
    if not os.path.isfile(path):
        raise Unusable(MISSING_CORE % path)
    try:
        spec = importlib.util.spec_from_file_location("trace_core", path)
        core = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(core)
    except Exception as exc:  # a broken core is unusable, not a traceback
        raise Unusable("trace core at %s cannot be loaded: %s" % (path, type(exc).__name__))
    absent = [name for name in CORE_API if not callable(getattr(core, name, None))]
    if absent:
        raise Unusable("trace core at %s lacks %s" % (path, ", ".join(absent)))
    return core


def find_package(root, story):
    folders = sorted(d for d in glob.glob(os.path.join(glob.escape(root), "impacts", glob.escape(story) + "-*"))
                     if os.path.isdir(d) and SLUG_RE.fullmatch(os.path.basename(d)[len(story) + 1:]))
    if not folders:
        raise Unusable("no impacts/%s-*/build-package.json under %s" % (story, root))
    if len(folders) > 1:
        names = ", ".join(os.path.basename(d) for d in folders)
        raise Unusable("more than one impacts folder matches %s: %s" % (story, names))
    path = os.path.join(folders[0], "build-package.json")
    if not os.path.isfile(path):
        raise Unusable("no impacts/%s-*/build-package.json under %s" % (story, root))
    return path


def load_package(path, root):
    rel = os.path.relpath(path, root).replace("\\", "/")
    try:
        with open(path, encoding="utf-8") as fh:
            pkg = json.load(fh)
    except (OSError, UnicodeDecodeError) as exc:
        raise Unusable("%s cannot be read: %s" % (rel, type(exc).__name__))
    except (ValueError, RecursionError):
        raise Unusable("%s is not valid JSON" % rel)
    if not isinstance(pkg, dict):
        raise Unusable("%s is not a JSON object" % rel)
    criteria = pkg.get("criteria")
    if not isinstance(criteria, list) or not all(isinstance(c, dict) and isinstance(c.get("id"), str) for c in criteria):
        raise Unusable("%s: criteria is not a list of objects with a string id" % rel)
    scope = pkg.get("scope")
    tests = scope.get("tests") if isinstance(scope, dict) else None
    if not isinstance(tests, list) or not all(isinstance(t, str) for t in tests):
        raise Unusable("%s: scope.tests is not a list of strings" % rel)
    top = os.path.realpath(root)
    for t in tests:
        parts = t.split("/")
        if not t or t.startswith("/") or "\\" in t or ".." in parts or "" in parts:
            raise Unusable("%s: scope.tests entry %s is not a repo-relative path" % (rel, json.dumps(t)))
        real = os.path.realpath(os.path.join(top, t))
        if os.path.commonpath([top, real]) != top:
            raise Unusable("%s: scope.tests entry %s resolves outside the repo" % (rel, json.dumps(t)))
    return rel, criteria, tests


def check(core, root, story, skeletons):
    rel, criteria, tests = load_package(find_package(root, story), root)
    # The guard-owned core's criteria rule, the same one scope_core applies to the committed package.
    problem = core.criteria_problem(criteria)
    if problem:
        raise Invalid("%s: %s" % (rel, problem))
    ids = [c["id"] for c in criteria]
    texts = core.read_tests(root, tests)
    # Metadata companions (*-meta.xml) cannot carry ids: an id found only there covers no criterion,
    # and they are exempt from the no-refs rule below.
    source_texts = {t: v for t, v in texts.items() if not t.endswith(META_SUFFIX)}
    missing = core.missing_criteria(ids, source_texts)
    files = [{"path": t, "exists": t in texts, "refs": core.unknown_refs([], {t: texts[t]}) if t in texts else []}
             for t in tests]
    unknown = core.unknown_refs(ids, texts)
    # A file references no id when every id is missing from that file alone.
    without = [t for t in tests if t in source_texts and ids
               and len(core.missing_criteria(ids, {t: source_texts[t]})) == len(ids)]
    ok = not missing if skeletons else not (missing or unknown or without)
    return {
        "storyId": story,
        "package": rel,
        "mode": "skeletons" if skeletons else "full",
        "criteria": ids,
        "tests": files,
        "missingCriteria": missing,
        "missingTestFiles": [t for t in tests if t not in texts],
        "unknownRefs": unknown,
        "testsWithoutRefs": without,
        "ok": ok,
    }


def main(argv=None, core_path=None):
    """core_path is for in-process tests only; no command-line flag or env var can set it."""
    ap = argparse.ArgumentParser(description="Criterion-to-test traceability for one build package.",
                                 allow_abbrev=False)
    ap.add_argument("storyId")
    ap.add_argument("--skeletons", action="store_true", help="only require every criterion to be referenced")
    ap.add_argument("--root", default=CHECKOUT, help="repo whose work tree holds the package (default: this checkout)")
    args = ap.parse_args(argv)
    core_file = core_path or DEFAULT_CORE
    try:
        if not STORY_RE.fullmatch(args.storyId):
            raise Unusable("storyId %s does not match %s" % (json.dumps(args.storyId), STORY_RE.pattern))
        if not os.path.isdir(args.root):
            raise Unusable("--root %s is not a directory" % args.root)
        core = load_core(os.path.abspath(core_file))
        report = check(core, os.path.realpath(args.root), args.storyId, args.skeletons)
    except Unusable as exc:
        sys.stderr.write("check_trace: %s\n" % exc)
        return 2
    except Invalid as exc:
        sys.stderr.write("check_trace: invalid package: %s\n" % exc)
        return 1
    sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

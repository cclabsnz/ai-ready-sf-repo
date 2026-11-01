"""Test-traceability core: which criterion ids the scope's test files reference.

Guard-owned (tools/guard/trace_core.py once the WS8 patch is applied). guard.py and tools/code/check_trace.py
both load this file by explicit path, never through sys.path, so the guard's tests-first rule and the CLI
can never disagree. Stdlib only, no repo imports, no side effects at import.

Matching is structural: an id counts when it appears in a test file's text as a whole token. Before the id
there is no letter (any script), digit, "_" or "-"; after it there is no letter, digit, "_" or "-<digit>".
So AC-1 is not satisfied by AC-10, XAC-1, ÄAC-1, X-AC-1, AC-1_b or AC-1-2. A comment satisfies it; test
quality is a review question.

Each text is scanned once with one reference pattern; the cost is linear in the text, whatever the number of
ids, so the guard's 7 s deadline holds for a full package.

  read_tests(root, paths)        {path: text} for the listed files that exist (first MAX_READ bytes, errors="replace")
  source_test_paths(paths)       the listed paths that can carry ids: every path not ending in META_SUFFIX, in order
  criteria_problem(criteria)     None for a valid criteria[] (non-empty, unique AC-n / EC-n ids), else a finding
  missing_criteria(ids, texts)   ids that no text references, sorted by prefix then number
  unknown_refs(ids, texts)       AC-n / EC-n ids the texts reference that ids does not hold, sorted the same way

A "-meta.xml" file in scope.tests is a metadata companion, not a test: an id found only there covers no
criterion. The guard's tests-first rule and check_trace.py both pass scope.tests through source_test_paths
before matching, so they exclude the same files.
"""
import os
import re

MAX_READ = 2 * 1024 * 1024
META_SUFFIX = "-meta.xml"
ID_RE = re.compile(r"(?:AC|EC)-[0-9]+")
# \w is Unicode-aware for str patterns: letters of any script, digits and "_".
REF_RE = re.compile(r"(?<![\w-])((?:AC|EC)-[0-9]+)(?!\w|-[0-9])")


def criteria_problem(criteria):
    """None when criteria is a non-empty list of objects with unique AC-<n> / EC-<n> ids, else the finding.
    scope_core applies the same rule to the committed package (a drift test keeps them equal)."""
    if not isinstance(criteria, list) or not criteria:
        return "criteria is not a non-empty list"
    seen = set()
    for c in criteria:
        if not isinstance(c, dict):
            return "criterion %r is not an object" % (c,)
        cid = c.get("id")
        if not isinstance(cid, str) or not ID_RE.fullmatch(cid):
            return "criterion id %r is not AC-<n> or EC-<n>" % (cid,)
        if cid in seen:
            return "duplicate criterion id %s" % cid
        seen.add(cid)
    return None


def source_test_paths(paths):
    """The entries of paths that can carry criterion ids, in their order: every string not ending in META_SUFFIX.
    A non-string entry is dropped (read_tests skips it too)."""
    return [p for p in paths if isinstance(p, str) and not p.endswith(META_SUFFIX)]


def read_tests(root, paths):
    """Text of each listed file that exists as a regular file inside root.

    A path that is absolute, contains "..", "\\" or a symlink, or names a directory is skipped: it is not a test
    file this check can read. Each file contributes at most MAX_READ bytes, decoded as UTF-8 with errors="replace".
    """
    top = os.path.realpath(root)
    out = {}
    for rel in paths:
        if not isinstance(rel, str) or not rel or rel.startswith("/") or "\\" in rel or "\0" in rel:
            continue
        if ".." in rel.split("/"):
            continue
        full = os.path.join(top, rel)
        if os.path.realpath(full) != os.path.normpath(full) or not os.path.isfile(full):
            continue
        try:
            with open(full, "rb") as fh:
                data = fh.read(MAX_READ)
        except OSError:
            continue
        out[rel] = data.decode("utf-8", errors="replace")
    return out


def _sort_key(cid):
    prefix, _, num = cid.partition("-") if isinstance(cid, str) else ("", "", "")
    return (0, prefix, int(num), "") if num.isdigit() else (1, "", 0, str(cid))


def _referenced(texts):
    found = set()
    for text in texts.values():
        found.update(REF_RE.findall(text))
    return found


def missing_criteria(ids, texts):
    """The ids that appear in none of the texts, unique and sorted. An id that is not AC-n / EC-n can never be
    referenced, so it is always missing (fails closed)."""
    return sorted(set(ids) - _referenced(texts), key=_sort_key)


def unknown_refs(ids, texts):
    """AC-n / EC-n references found in the texts that are not in ids, unique and sorted."""
    return sorted(_referenced(texts) - set(ids), key=_sort_key)

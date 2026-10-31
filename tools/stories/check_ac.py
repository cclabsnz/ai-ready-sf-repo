#!/usr/bin/env python3
"""Check a story's acceptance criteria for structure and vague wording.

Usage:
  check_ac.py <story.json>

Rules: no-criteria, missing-gwt, multiple-outcomes, no-example, vague-word.
no-criteria: acceptanceCriteria is missing, not a list, or empty.
Quoted text ("..." or `...`) is ignored by multiple-outcomes and vague-word.
Prints {"ok": bool, "findings": [{id, rule, detail}]}.
Exit codes: 0 no findings, 1 findings, 2 bad usage or unreadable input.
Stdlib only.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

QUOTED = re.compile(r'"[^"]*"|`[^`]*`')
SENTENCE_BREAK = re.compile(r"[.!?]+\s+[A-Z0-9]")
CONJUNCTION = re.compile(r"\b(and|or)\b", re.I)


def load_vague():
    with open(os.path.join(HERE, "vague_words.json"), encoding="utf-8") as fh:
        return list(json.load(fh)["words"])


def strip_quoted(text):
    return QUOTED.sub(" ", text)


def _nonempty(v):
    return isinstance(v, str) and v.strip() != ""


def _outcome_problem(then):
    plain = strip_quoted(then)
    if ";" in plain:
        return "';'"
    if SENTENCE_BREAK.search(plain):
        return "more than one sentence"
    m = CONJUNCTION.search(plain)
    if m:
        return "the word '%s'" % m.group(1).lower()
    return None


def check_ac(doc, vague):
    """Return [{id, rule, detail}] for the acceptance criteria in doc."""
    findings = []
    acs = doc.get("acceptanceCriteria") if isinstance(doc, dict) else None
    if not isinstance(acs, list) or not acs:
        return [{"id": "acceptanceCriteria", "rule": "no-criteria",
                 "detail": "the story has no acceptance criteria"}]
    patterns = [(w, re.compile(r"(?<!\w)" + re.escape(w).replace(r"\ ", r"\s+") + r"(?!\w)", re.I)) for w in vague]
    for i, ac in enumerate(acs):
        if not isinstance(ac, dict):
            continue
        ident = ac.get("id") if isinstance(ac.get("id"), str) else "acceptanceCriteria[%d]" % i

        def add(rule, detail):
            findings.append({"id": ident, "rule": rule, "detail": detail})

        missing = [k for k in ("given", "when", "then") if not _nonempty(ac.get(k))]
        if missing:
            add("missing-gwt", "empty or missing: %s" % ", ".join(missing))
        if _nonempty(ac.get("then")):
            problem = _outcome_problem(ac["then"])
            if problem:
                add("multiple-outcomes",
                    "then states more than one outcome (%s); split into separate criteria" % problem)
        ex = ac.get("examples")
        if not (isinstance(ex, list) and any(_nonempty(e) for e in ex)):
            add("no-example", "examples is empty")
        for k in ("given", "when", "then"):
            if not _nonempty(ac.get(k)):
                continue
            plain = strip_quoted(ac[k])
            for w, pat in patterns:
                if pat.search(plain):
                    add("vague-word", "%s contains '%s'" % (k, w))
    return findings


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0].startswith("-"):
        print("usage: check_ac.py <story.json>", file=sys.stderr)
        return 2
    try:
        with open(argv[0], encoding="utf-8") as fh:
            doc = json.load(fh)
        vague = load_vague()
    except (OSError, ValueError, KeyError) as exc:
        print("cannot read input: %s" % exc, file=sys.stderr)
        return 2
    if not isinstance(doc, dict):
        print("%s: record is not a JSON object" % argv[0], file=sys.stderr)
        return 2
    findings = check_ac(doc, vague)
    print(json.dumps({"ok": not findings, "findings": findings}, indent=2))
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())

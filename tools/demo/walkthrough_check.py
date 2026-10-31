#!/usr/bin/env python3
"""Re-run the walkthrough's deterministic steps and diff them against demo/expected/.

Usage:
  python3 tools/demo/walkthrough_check.py              run every step and compare
  python3 tools/demo/walkthrough_check.py --show <step> print one step's normalised output

Steps (demo/WALKTHROUGH.md):
  index-build       build_index.py on the configured sourceRoot, into a temp folder
  hop3-consumers    query.py consumers Account.Service_Level__c --hops 3 on that temp index
  register-view     register.py view (the committed DEMO-202 record)
  score-demo-202    demo/measure/score.py on DEMO-202's committed impact against its key
  consistency       consistency.py --text on the committed fixture runs (not live runs)
  check-rules       check_rules.py --from-config

Each step's expected output is demo/expected/<NN>-<step>.txt: three header lines (step, command,
exit code) and then stdout, normalised:
- CRLF becomes LF, and trailing spaces are dropped;
- stdout that is one JSON document is re-printed with indent 2, so a diff shows the changed line;
- the consumers list is sorted by (hop, api), because edge order follows the file walk, which
  differs between file systems;
- the repo path becomes <repo> and the temp folder <tmp>;
- ISO timestamps become <time>;
- hex words of 7 to 40 characters holding at least one digit and one letter a-f become <commit>
  (so a long decimal number stays visible), and so does any hex
  word in a known commit position ("commit": "..." and a line ending " at <hex>").
Expected files are read as UTF-8 (a BOM is allowed); one that does not decode is a difference.

The index is built into a temp folder, so the check leaves index/ alone. Nothing else is written.
To refresh an expected file after a reviewed change, run --show and save its output over the file.

Exit codes: 0 every step matches, 1 any difference (the diff is printed), 2 bad usage.
Stdlib only. Code paths come from this file's location; every step runs with the repo as cwd.
"""
import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
EXPECTED = os.path.join(REPO, "demo", "expected")

BUILD = os.path.join(REPO, "tools", "index", "build_index.py")
QUERY = os.path.join(REPO, "tools", "index", "query.py")
REGISTER = os.path.join(REPO, "tools", "impacts", "register.py")
SCORE = os.path.join(REPO, "demo", "measure", "score.py")
CONSISTENCY = os.path.join(REPO, "tools", "evals", "consistency.py")
CHECK_RULES = os.path.join(REPO, "tools", "code", "check_rules.py")

# Data paths are relative to the repo with "/" separators: consistency.py prints its folder
# arguments verbatim, and Python on Windows accepts "/" in paths.
FIXTURE = "demo/expected/consistency-fixture"
FIXTURE_RUNS = [FIXTURE + "/run-1", FIXTURE + "/run-2", FIXTURE + "/run-3"]
DEMO_202_IMPACT = "impacts/DEMO-202-round-robin-assignment/impact.json"
DEMO_202_KEY = "demo/stories/DEMO-202.answer.json"

TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")
HASH_RE = re.compile(r"(?<![0-9A-Za-z_])(?=[0-9a-f]*[0-9])(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![0-9A-Za-z_])")
# Known commit positions, normalised even when the hash happens to hold no digit.
COMMIT_CONTEXT_RES = (
    re.compile(r'("commit": ")[0-9a-f]{7,40}(")'),
    re.compile(r"( at )[0-9a-f]{7,40}($)", re.MULTILINE),
)


def source_root_rel():
    """sourceRoot from .ai-framework.json, as written there, and its absolute real path."""
    sys.path.insert(0, os.path.join(REPO, "tools", "config"))
    import framework_config
    return framework_config.load(REPO)["sourceRoot"], framework_config.source_root(REPO)


def steps(tmp):
    """The deterministic steps, in walkthrough order: (name, display command, argv, canonicaliser)."""
    index = os.path.join(tmp, "index")
    rel, absolute = source_root_rel()
    return [
        ("index-build",
         "python3 tools/index/build_index.py --root %s --out <tmp>/index" % rel,
         [BUILD, "--root", absolute, "--out", index], None),
        ("hop3-consumers",
         "python3 tools/index/query.py consumers Account.Service_Level__c --hops 3 --index <tmp>/index",
         [QUERY, "consumers", "Account.Service_Level__c", "--hops", "3", "--index", index],
         sort_consumers),
        ("register-view",
         "python3 tools/impacts/register.py view",
         [REGISTER, "view"], None),
        ("score-demo-202",
         "python3 demo/measure/score.py %s --key %s" % (DEMO_202_IMPACT, DEMO_202_KEY),
         [SCORE, DEMO_202_IMPACT, "--key", DEMO_202_KEY], None),
        ("consistency",
         "python3 tools/evals/consistency.py %s --text" % " ".join(FIXTURE_RUNS),
         [CONSISTENCY] + FIXTURE_RUNS + ["--text"], None),
        ("check-rules",
         "python3 tools/code/check_rules.py --from-config",
         [CHECK_RULES, "--from-config"], None),
    ]


def sort_consumers(doc):
    """Sort a consumers result by (hop, api); the order the index lists edges in is the walk order."""
    if isinstance(doc, dict) and isinstance(doc.get("consumers"), list):
        doc["consumers"] = sorted(doc["consumers"], key=lambda c: (
            c.get("hop") if isinstance(c.get("hop"), int) else 0, str(c.get("api"))))
    return doc


def reformat_json(text, canonicaliser=None):
    """Re-print text with indent 2 when it is exactly one JSON document; otherwise return it as is."""
    try:
        doc = json.loads(text)
    except ValueError:
        return text
    if canonicaliser is not None:
        doc = canonicaliser(doc)
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


def path_variants(path):
    """The spellings a path can take in output: as given and real, with either separator."""
    out = []
    for p in (path, os.path.abspath(path), os.path.realpath(path)):
        for q in (p, p.replace("\\", "/"), p.replace("/", "\\")):
            if q and q not in out:
                out.append(q)
    return sorted(out, key=len, reverse=True)  # longest first, so /private/var wins over /var


def normalise(text, repo=REPO, tmp=None):
    """Output text with line endings, temp and repo paths, timestamps and commit hashes made stable."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    flags = re.IGNORECASE if os.name == "nt" else 0
    for root, token in ((tmp, "<tmp>"), (repo, "<repo>")):
        if not root:
            continue
        for v in path_variants(root):
            text = re.sub(re.escape(v), lambda _m, t=token: t, text, flags=flags)
    text = TIME_RE.sub("<time>", text)
    for pattern in COMMIT_CONTEXT_RES:
        text = pattern.sub(lambda m: m.group(1) + "<commit>" + m.group(2), text)
    text = HASH_RE.sub("<commit>", text)
    lines = [line.rstrip() for line in text.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def render(name, command, code, stdout, canonicaliser=None, repo=REPO, tmp=None):
    """The expected-file form of one step's result."""
    body = normalise(reformat_json(stdout, canonicaliser), repo=repo, tmp=tmp)
    return "step: %s\ncommand: %s\nexit: %d\n%s" % (name, command, code, body)


def run_step(argv, cwd=REPO):
    """Run one step's script with this interpreter, no shell. Returns (exit code, stdout, stderr)."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable] + argv, cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    return p.returncode, p.stdout, p.stderr


def expected_path(expected_dir, index, name):
    return os.path.join(expected_dir, "%02d-%s.txt" % (index, name))


def compare(expected_dir, results):
    """results: [(name, rendered)] in step order. Returns [(name, ok, diff lines)]."""
    out = []
    for i, (name, rendered) in enumerate(results, 1):
        path = expected_path(expected_dir, i, name)
        try:
            # text mode: a CRLF checkout reads as LF; utf-8-sig drops a BOM an editor may add
            with open(path, encoding="utf-8-sig") as fh:
                want = fh.read()
        except OSError:
            out.append((name, False, ["no expected file at %s" % os.path.relpath(path, REPO)]))
            continue
        except UnicodeDecodeError:
            out.append((name, False, ["%s is not UTF-8 (a PowerShell > redirect writes UTF-16)"
                                      % os.path.relpath(path, REPO)]))
            continue
        want = want.replace("\r\n", "\n")
        if want == rendered:
            out.append((name, True, []))
            continue
        diff = list(difflib.unified_diff(want.splitlines(), rendered.splitlines(),
                                         "expected/" + os.path.basename(path), "actual", lineterm=""))
        out.append((name, False, diff))
    return out


def run_all(tmp):
    results, stderrs = [], {}
    for name, command, argv, canon in steps(tmp):
        code, stdout, stderr = run_step(argv)
        results.append((name, render(name, command, code, stdout, canon, tmp=tmp)))
        stderrs[name] = stderr
    return results, stderrs


def main(argv=None):
    ap = argparse.ArgumentParser(description="Diff the walkthrough's deterministic steps against demo/expected/.",
                                 allow_abbrev=False)
    ap.add_argument("--show", metavar="STEP", help="print one step's normalised output and exit")
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    tmp = tempfile.mkdtemp(prefix="walkthrough-check-")
    try:
        names = [s[0] for s in steps(tmp)]
        if a.show is not None and a.show not in names:
            print("unknown step %r; steps: %s" % (a.show, ", ".join(names)), file=sys.stderr)
            return 2
        results, stderrs = run_all(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if a.show is not None:
        sys.stdout.write(dict(results)[a.show])
        return 0
    failed = 0
    for name, ok, diff in compare(EXPECTED, results):
        print("[%s] %s" % ("PASS" if ok else "FAIL", name))
        if not ok:
            failed += 1
            for line in diff:
                print("    " + line)
            if stderrs.get(name, "").strip():
                print("    stderr: " + stderrs[name].strip().replace("\n", "\n    stderr: "))
    print("%d passed, %d failed" % (len(results) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

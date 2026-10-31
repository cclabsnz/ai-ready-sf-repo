#!/usr/bin/env python3
"""Run one eval case N times under Claude Code headless and collect each run's outputs.

  python3 tools/evals/run_all.py --case story-impact/004-escalation-hops-3 [--n 5] [--model <id>]

The owner runs this: it needs the owner's Claude Code account, and `claude` is on no assistant
allowlist. For run i (1..N) it:
  1. creates ai-context/evals/<skill>-<case>/run-<i>/ in this checkout (refused when the folder
     already holds files, so stale outputs are never compared as fresh);
  2. runs  claude -p <prompt> --model <model> --output-format json  from the checkout root. The
     prompt is the case's `input` plus an instruction to run the named skill and copy the files
     it wrote into the run folder. No permission-bypass flag is passed: the project's settings and
     guard apply to every run;
  3. saves the command's stdout to claude-output.json and stderr to claude-stderr.txt, and writes
     run.json: {case, claudeVersion, command, exit, frameworkVersion, indexStamp, model, run, runs}.
     claudeVersion is the first line of `claude --version`, run once per series through the same
     runner ("unknown" when it fails). frameworkVersion is this checkout's VERSION; indexStamp is the
     `stamp` of <checkout>/index/metadata.json read after the run (null when absent), since a skill
     may rebuild a stale index during the run.

The binary is always `claude`. No flag or environment variable chooses the binary or the code that
runs; --model chooses only the model id (default MODEL). The case comes from
framework/skills/<skill>/evals/cases/<case>.json in this checkout, located from __file__.

Compare the runs afterwards with tools/evals/consistency.py on the run folders.

Operator notes (tools/evals/README.md says the same):
- Clean worktree per run. Every run otherwise shares one working tree: an implement-story run sees
  the previous run's edits, and any skill may find an earlier run's ai-context/<id>-<slug>/ outputs.
  Start each run from a clean worktree at the same commit.
- Diff-names files (implement-story runs). After each run, write one file per run listing the
  touched paths: `git diff --name-only` plus `git ls-files --others --exclude-standard` (the plain
  diff misses new files), with every ai-context/ path removed (run folders differ per run and would
  read as drift). Pass them to consistency.py with --diff-names, in run order.
- Confirm the flags. Check -p, --model and --output-format against `claude --help` for the installed
  Claude Code version before the first series.
- Headless permissions are the operator's. Print mode cannot answer permission prompts, and no
  bypass flag is passed, so the project's and the operator's Claude Code settings decide whether the
  skill can write files and run its scripts.
- Case ids. The story-impact cases with ids 9001 and 9004 do not match the story-id pattern
  (PREFIX-n) that the skills' writers expect, so check where those runs write their outputs.

Prints a JSON summary. Exit codes: 0 every run exited 0, 1 a run exited non-zero, 2 bad usage
(unknown case, --n below 1, a run folder that already holds files, `claude` not found).
Tests call main(argv, runner=fake); the runner is called as runner(cmd, cwd) and returns an object
with returncode, stdout and stderr (subprocess.CompletedProcess). Stdlib only.
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKOUT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(CHECKOUT, "tools", "impacts"))

from safe_write import checkout_out_dir, write_nofollow  # noqa: E402

MODEL = "claude-sonnet-5-5"
DEFAULT_N = 5
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def default_runner(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def build_prompt(skill, case_input, run_rel):
    return ("Run the %s skill on the input below.\n\n"
            "Input:\n%s\n\n"
            "When the skill has finished, copy every file it wrote (its JSON record, its markdown "
            "report and its scan/ files) unchanged into the folder %s/ . Write nothing else in that "
            "folder." % (skill, case_input, run_rel))


def build_command(prompt, model):
    return ["claude", "-p", prompt, "--model", model, "--output-format", "json"]


CODE_SKILL = "implement-story"


def compare_hint(skill, run_rels):
    """The consistency.py command for these run folders. Code runs also take one touched-file list
    per run (git diff names plus untracked files, without ai-context/ paths), which the owner writes."""
    cmd = "python3 tools/evals/consistency.py %s --text" % " ".join(run_rels)
    if skill == CODE_SKILL:
        cmd += " --diff-names %s" % " ".join("<diff-names-run-%d.txt>" % i
                                             for i in range(1, len(run_rels) + 1))
    return cmd


VERSION_CMD = ["claude", "--version"]


def claude_version(runner):
    """First line of `claude --version` through the runner, or "unknown" when it fails."""
    try:
        proc = runner(list(VERSION_CMD), CHECKOUT)
    except (OSError, ValueError):
        return "unknown"
    lines = (proc.stdout or "").strip().splitlines()
    if proc.returncode != 0 or not lines or not lines[0].strip():
        return "unknown"
    return lines[0].strip()


def framework_version():
    try:
        with open(os.path.join(CHECKOUT, "VERSION"), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return None


def index_stamp():
    try:
        with open(os.path.join(CHECKOUT, "index", "metadata.json"), encoding="utf-8") as fh:
            stamp = json.load(fh).get("stamp")
    except (OSError, ValueError, AttributeError, RecursionError):
        return None
    return stamp if isinstance(stamp, dict) else None


def _bytes(text):
    return (text or "").replace("\r\n", "\n").encode("utf-8")


def usage(msg):
    print(msg, file=sys.stderr)
    return 2


def main(argv=None, runner=None, root=None):
    """root: the folder whose ai-context/ receives the run folders (default this checkout; tests
    pass a temp folder inside the checkout's ai-context/)."""
    ap = argparse.ArgumentParser(description="Run one eval case N times under Claude Code headless.",
                                 allow_abbrev=False)
    ap.add_argument("--case", required=True, help="<skill>/<case>, a file under framework/skills/<skill>/evals/cases/")
    ap.add_argument("--n", type=int, default=DEFAULT_N, help="number of runs (default %d)" % DEFAULT_N)
    ap.add_argument("--model", default=MODEL, help="model id (default %s)" % MODEL)
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    runner = runner or default_runner
    root = root or CHECKOUT

    skill, sep, case = a.case.partition("/")
    if not sep or not NAME_RE.match(skill) or not NAME_RE.match(case):
        return usage("--case '%s' is not <skill>/<case> (lower-case letters, digits and hyphens)" % a.case)
    if a.n < 1:
        return usage("--n is %d; it is at least 1" % a.n)
    if not a.model.strip():
        return usage("--model is empty")
    case_path = os.path.join(CHECKOUT, "framework", "skills", skill, "evals", "cases", case + ".json")
    try:
        with open(case_path, encoding="utf-8") as fh:
            case_doc = json.load(fh)
    except (OSError, ValueError) as exc:
        return usage("cannot read case %s: %s" % (os.path.relpath(case_path, CHECKOUT), type(exc).__name__))
    if not isinstance(case_doc, dict) or not isinstance(case_doc.get("input"), str) or not case_doc["input"].strip():
        return usage("case %s has no input text" % a.case)

    run_dirs = []
    for i in range(1, a.n + 1):
        try:
            d = checkout_out_dir(root, "evals/%s-%s/run-%d" % (skill, case, i))
        except ValueError as exc:
            return usage("%s; nothing run" % exc)
        if os.path.isdir(d) and os.listdir(d):
            return usage("%s already holds files; move it aside before a new series; nothing run" % d)
        run_dirs.append(d)

    version = framework_version()
    cc_version = claude_version(runner)
    summary = []
    for i, d in enumerate(run_dirs, 1):
        os.makedirs(d, exist_ok=True)
        run_rel = os.path.relpath(d, CHECKOUT).replace(os.sep, "/")
        cmd = build_command(build_prompt(skill, case_doc["input"], run_rel), a.model)
        try:
            proc = runner(cmd, CHECKOUT)
        except FileNotFoundError:
            return usage("claude was not found on PATH; install Claude Code to run live evals")
        record = {"case": "%s/%s" % (skill, case), "claudeVersion": cc_version, "command": cmd,
                  "exit": proc.returncode,
                  "frameworkVersion": version, "indexStamp": index_stamp(), "model": a.model,
                  "run": i, "runs": a.n}
        write_nofollow(os.path.join(d, "claude-output.json"), _bytes(proc.stdout))
        write_nofollow(os.path.join(d, "claude-stderr.txt"), _bytes(proc.stderr))
        write_nofollow(os.path.join(d, "run.json"),
                       (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        summary.append({"dir": run_rel, "exit": proc.returncode})
    print(json.dumps({"case": "%s/%s" % (skill, case), "model": a.model, "runs": summary,
                      "compare": compare_hint(skill, [s["dir"] for s in summary])},
                     indent=2, sort_keys=True))
    return 0 if all(s["exit"] == 0 for s in summary) else 1


if __name__ == "__main__":
    sys.exit(main())

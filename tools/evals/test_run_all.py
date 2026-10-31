#!/usr/bin/env python3
"""Tests for run_all.py through an injected runner; `claude` is never started.

Plain script: python3 tools/evals/test_run_all.py
Run folders go under a temp folder inside <checkout>/ai-context/, removed after.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKOUT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import run_all  # noqa: E402

CASE = "story-impact/004-escalation-hops-3"
CASE_FILE = os.path.join(CHECKOUT, "framework", "skills", "story-impact", "evals", "cases",
                         "004-escalation-hops-3.json")


class Fake:
    """calls holds the claude -p runs; version_calls holds the claude --version calls."""

    def __init__(self, code=0, version=(0, "9.9.9 (Claude Code)\n")):
        self.calls, self.version_calls, self.code, self.version = [], [], code, version

    def __call__(self, cmd, cwd):
        if cmd == ["claude", "--version"]:
            self.version_calls.append((list(cmd), cwd))
            if self.version is None:
                raise FileNotFoundError(cmd[0])
            return subprocess.CompletedProcess(cmd, self.version[0], stdout=self.version[1], stderr="")
        self.calls.append((list(cmd), cwd))
        return subprocess.CompletedProcess(cmd, self.code, stdout='{"result": "ok"}\n', stderr="")


def tmp_root():
    return tempfile.mkdtemp(prefix="run_all_", dir=os.path.join(CHECKOUT, "ai-context"))


def call(argv, runner, root):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = run_all.main(argv, runner=runner, root=root)
    return code, out.getvalue(), err.getvalue()


def read_case_input():
    with open(CASE_FILE, encoding="utf-8") as fh:
        return json.load(fh)["input"]


def run_dir(root, i):
    return os.path.join(root, "ai-context", "evals", "story-impact-004-escalation-hops-3", "run-%d" % i)


def case_builds_exact_claude_command():
    root = tmp_root()
    try:
        fake = Fake()
        code, out, err = call(["--case", CASE, "--n", "2"], fake, root)
        assert code == 0, (code, err)
        assert len(fake.calls) == 2, fake.calls
        for i, (cmd, cwd) in enumerate(fake.calls, 1):
            rel = os.path.relpath(run_dir(root, i), CHECKOUT).replace(os.sep, "/")
            prompt = run_all.build_prompt("story-impact", read_case_input(), rel)
            assert cmd == ["claude", "-p", prompt, "--model", "claude-sonnet-5-5", "--output-format", "json"], cmd
            assert cwd == CHECKOUT, cwd
            assert read_case_input() in prompt and "story-impact skill" in prompt and rel + "/" in prompt, prompt
        assert run_all.MODEL == "claude-sonnet-5-5"
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_default_n_is_5_and_model_overrides():
    root = tmp_root()
    try:
        fake = Fake()
        code, _, err = call(["--case", CASE, "--model", "claude-opus-5-5"], fake, root)
        assert code == 0, err
        assert len(fake.calls) == 5, len(fake.calls)
        assert all(c[0][3:5] == ["--model", "claude-opus-5-5"] for c in fake.calls), fake.calls
        assert all(c[0][0] == "claude" for c in fake.calls)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_run_json_records_provenance():
    root = tmp_root()
    try:
        fake = Fake()
        call(["--case", CASE, "--n", "1"], fake, root)
        d = run_dir(root, 1)
        with open(os.path.join(d, "run.json"), encoding="utf-8") as fh:
            rec = json.load(fh)
        with open(os.path.join(CHECKOUT, "VERSION"), encoding="utf-8") as fh:
            version = fh.read().strip()
        assert rec["model"] == "claude-sonnet-5-5" and rec["frameworkVersion"] == version, rec
        assert rec["case"] == CASE and rec["run"] == 1 and rec["runs"] == 1 and rec["exit"] == 0, rec
        assert rec["command"] == fake.calls[0][0], rec
        assert rec["indexStamp"] == run_all.index_stamp(), rec
        assert rec["indexStamp"] is None or "commit" in rec["indexStamp"], rec
        with open(os.path.join(d, "claude-output.json"), encoding="utf-8") as fh:
            assert json.load(fh) == {"result": "ok"}
        with open(os.path.join(d, "run.json"), "rb") as fh:
            assert b"\r" not in fh.read()
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_no_flag_chooses_the_binary():
    root = tmp_root()
    try:
        for extra in (["--claude", "x"], ["--bin", "x"], ["--runner", "x"]):
            fake = Fake()
            code, _, _ = call(["--case", CASE, "--n", "1"] + extra, fake, root)
            assert code == 2 and fake.calls == [], (extra, code)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_bad_usage_exits_2_without_running():
    root = tmp_root()
    try:
        for argv in (["--case", "story-impact"], ["--case", "../x/y"], ["--case", "story-impact/../../VERSION"],
                     ["--case", "story-impact/999-missing"], ["--case", CASE, "--n", "0"], []):
            fake = Fake()
            code, _, err = call(argv, fake, root)
            assert code == 2 and fake.calls == [] and "Traceback" not in err, (argv, code, err)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_existing_run_folder_refused():
    root = tmp_root()
    try:
        call(["--case", CASE, "--n", "1"], Fake(), root)
        fake = Fake()
        code, _, err = call(["--case", CASE, "--n", "1"], fake, root)
        assert code == 2 and fake.calls == [] and "already holds files" in err, (code, err)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_non_zero_run_exits_1():
    root = tmp_root()
    try:
        code, out, _ = call(["--case", CASE, "--n", "1"], Fake(code=3), root)
        assert code == 1 and json.loads(out)["runs"][0]["exit"] == 3, out
    finally:
        shutil.rmtree(root, ignore_errors=True)


def read_run_json(root):
    with open(os.path.join(run_dir(root, 1), "run.json"), encoding="utf-8") as fh:
        return json.load(fh)


def case_claude_version_recorded():
    root = tmp_root()
    try:
        fake = Fake()
        code, _, err = call(["--case", CASE, "--n", "2"], fake, root)
        assert code == 0, err
        assert fake.version_calls == [(["claude", "--version"], CHECKOUT)], fake.version_calls
        assert read_run_json(root)["claudeVersion"] == "9.9.9 (Claude Code)", read_run_json(root)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    for version in ((1, "boom\n"), (0, "\n"), None):
        root = tmp_root()
        try:
            code, _, err = call(["--case", CASE, "--n", "1"], Fake(version=version), root)
            assert code == 0, (version, err)
            assert read_run_json(root)["claudeVersion"] == "unknown", (version, read_run_json(root))
        finally:
            shutil.rmtree(root, ignore_errors=True)


def case_compare_hint():
    root = tmp_root()
    try:
        code, out, _ = call(["--case", CASE, "--n", "2"], Fake(), root)
        hint = json.loads(out)["compare"]
        assert code == 0 and hint.startswith("python3 tools/evals/consistency.py ") and "--diff-names" not in hint, hint
        code, out, err = call(["--case", "implement-story/001-assignment-on-insert", "--n", "2"], Fake(), root)
        hint = json.loads(out)["compare"]
        assert code == 0 and hint.endswith(" --diff-names <diff-names-run-1.txt> <diff-names-run-2.txt>"), (err, hint)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def case_missing_claude_exits_2():
    root = tmp_root()
    try:
        def missing(cmd, cwd):
            raise FileNotFoundError(cmd[0])
        code, _, err = call(["--case", CASE, "--n", "1"], missing, root)
        assert code == 2 and "not found" in err, (code, err)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main():
    failures = passed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("case_") and callable(fn):
            try:
                fn()
                passed += 1
                print("PASS %s" % name)
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print("FAIL %s: %r" % (name, exc))
    print("%d passed, %d failed" % (passed, failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

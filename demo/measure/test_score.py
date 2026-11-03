#!/usr/bin/env python3
"""Tests for score.py. Temp trees go under <checkout>/ai-context; the demo files are only read.

Run: python3 demo/measure/test_score.py
"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
SCORE = os.path.join(HERE, "score.py")
KEY = os.path.join(REPO, "demo", "stories", "DEMO-202.answer.json")
IMPACT = os.path.join(REPO, "impacts", "DEMO-202-round-robin-assignment", "impact.json")

import importlib.util
_spec = importlib.util.spec_from_file_location("score", SCORE)
score = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(score)

TMP = tempfile.mkdtemp(prefix="score_", dir=os.path.join(REPO, "ai-context"))


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = score.main(list(args))
    return code, out.getvalue(), err.getvalue()


def write(name, obj):
    path = os.path.join(TMP, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh)
    return path


def synthetic_key():
    comp = lambda api: {"api": api, "type": "ApexClass", "changeType": "modify", "hop": 0, "why": "synthetic"}
    return write("key.json", {"version": 1, "storyId": "SYN-1", "squad": "Synthetic Squad",
                              "seeds": ["Alpha"], "hops": 1,
                              "components": [comp("Alpha"), comp("Beta"), comp("Gamma")]})


def rec(*apis):
    return write("rec.json", {"components": [{"api": a} for a in apis]})


def test_demo202_finds_the_whole_key():
    code, out, _ = run(IMPACT, "--key", KEY)
    result = json.loads(out)
    with open(KEY, encoding="utf-8") as fh:
        want = [c["api"] for c in json.load(fh)["components"]]
    with open(IMPACT, encoding="utf-8") as fh:
        record = [c["api"] for c in json.load(fh)["components"]]
    assert code == 0
    assert sorted(result["found"]) == sorted(want)
    assert result["missed"] == [] and result["recall"] == 1.0
    # The key predates the design, so components of the chosen design and review items are extras.
    assert sorted(result["extra"]) == sorted(set(record) - set(want))
    assert result["precision"] == len(want) / len(record)


def test_extra_is_listed():
    code, out, _ = run(rec("Alpha", "Beta", "Gamma", "Delta"), "--key", synthetic_key())
    result = json.loads(out)
    assert code == 0
    assert result["extra"] == ["Delta"]
    assert result["missed"] == []
    assert result["precision"] == 0.75


def test_missed_is_reported():
    code, out, _ = run(rec("Alpha"), "--key", synthetic_key())
    result = json.loads(out)
    assert code == 0
    assert result["found"] == ["Alpha"]
    assert result["missed"] == ["Beta", "Gamma"]
    assert abs(result["recall"] - 1 / 3) < 1e-9
    assert result["precision"] == 1.0


def test_api_case_is_ignored_and_record_spelling_kept():
    code, out, _ = run(rec("alpha", "BETA", "Alpha"), "--key", synthetic_key())
    result = json.loads(out)
    assert code == 0
    assert result["found"] == ["alpha", "BETA"]
    assert result["missed"] == ["Gamma"]
    assert result["extra"] == []
    assert result["precision"] == 1.0
    assert abs(result["recall"] - 2 / 3) < 1e-9


def test_empty_record_gives_null_precision():
    code, out, _ = run(rec(), "--key", synthetic_key())
    result = json.loads(out)
    assert code == 0 and result["precision"] is None and result["recall"] == 0.0


def test_bad_inputs_exit_2():
    assert run(os.path.join(TMP, "nope.json"), "--key", synthetic_key())[0] == 2
    assert run(rec("Alpha"), "--key", write("bad.json", {"version": 2}))[0] == 2
    assert run(write("nocomp.json", {}), "--key", synthetic_key())[0] == 2


def test_readme_figures_come_from_a_run():
    with open(os.path.join(HERE, "README.md"), encoding="utf-8") as fh:
        text = fh.read()
    block = text.split("```\n{", 2)[1].split("\n```", 1)[0]
    pasted = json.loads("{" + block)
    _, out, _ = run(IMPACT, "--key", KEY)
    assert pasted == json.loads(out), "README output differs from a fresh run"
    assert "demo/measure/score.py impacts/DEMO-202-round-robin-assignment/impact.json" in text
    # outside the pasted block, no digit may follow a figure-like cue
    import re
    prose = text.replace("```\n{" + block + "\n```", "")
    assert not re.search(r"\d+\s*(%|minutes|hours|x faster)", prose), "unsourced figure in README"


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = failed = 0
    try:
        for t in tests:
            try:
                t()
                passed += 1
            except Exception as exc:
                failed += 1
                print(f"FAIL {t.__name__}: {type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(TMP, True)
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

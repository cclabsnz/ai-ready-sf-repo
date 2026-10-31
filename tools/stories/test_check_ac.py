#!/usr/bin/env python3
"""Tests for check_ac.py. Temp files only.

Run: python3 tools/stories/test_check_ac.py
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_ac as C  # noqa: E402

CLI = os.path.join(HERE, "check_ac.py")
TMP = tempfile.mkdtemp(prefix="check_ac_")
atexit.register(shutil.rmtree, TMP, True)

VAGUE = C.load_vague()


def story(**over):
    ac = {"id": "AC-1", "given": "a premium case", "when": "the agent escalates it",
          "then": "the case moves to the premium queue", "examples": ["Case 1 moves"],
          "source": "stated"}
    ac.update(over)
    return {"acceptanceCriteria": [ac]}


def rules(doc):
    return [(f["rule"], f["detail"]) for f in C.check_ac(doc, VAGUE)]


def only(doc, rule):
    return [d for r, d in rules(doc) if r == rule]


def test_clean_criterion_passes():
    assert rules(story()) == []


def test_load_vague_matches_file():
    assert "etc." in VAGUE and "user-friendly" in VAGUE and len(VAGUE) == 11


def test_quoted_text_ignored():
    assert rules(story(then='shows "Terms and Conditions"')) == []
    assert rules(story(then="shows `as needed`")) == []
    assert rules(story(then='shows "Done. Really! Yes" in "red; blue"')) == []


def test_multiple_outcomes():
    got = only(story(then="the case is assigned and an email is sent"), "multiple-outcomes")
    assert got, rules(story(then="x"))
    assert only(story(then="the case is assigned or closed"), "multiple-outcomes")
    assert only(story(then="the case is assigned; an email is sent"), "multiple-outcomes")
    assert only(story(then="A is set. B is sent. C is logged"), "multiple-outcomes")
    assert not only(story(then="the case is assigned."), "multiple-outcomes")


def test_two_sentences_fail_decimal_passes():
    assert only(story(then="A is set. B is sent."), "multiple-outcomes")
    assert only(story(then="A is set! B is sent"), "multiple-outcomes")
    assert not only(story(then="the case is assigned."), "multiple-outcomes")
    assert not only(story(then="the score is set to 2.5"), "multiple-outcomes")
    assert not only(story(then="the score is 2.5."), "multiple-outcomes")
    assert not only(story(then='shows "A. B" on screen'), "multiple-outcomes")


def test_vague_phrase():
    got = only(story(then="loads quickly"), "vague-word")
    assert len(got) == 1 and "quickly" in got[0], got
    got = only(story(then="works properly etc."), "vague-word")
    assert any("properly" in g for g in got) and any("etc." in g for g in got), got
    assert only(story(when="Easily"), "vague-word"), "case-insensitive"
    assert only(story(then="done, and so on"), "vague-word")


def test_vague_phrase_any_whitespace():
    assert only(story(then="works as\nneeded"), "vague-word")
    assert only(story(then="works as   needed"), "vague-word")


def test_vague_whole_word_only():
    assert not only(story(then="uses the Fastlane queue"), "vague-word")
    assert not only(story(then="sets etcetera"), "vague-word")


def test_no_example():
    assert only(story(examples=[]), "no-example")
    assert only(story(examples=[" "]), "no-example")
    assert not only(story(), "no-example")


def test_missing_gwt():
    got = only(story(given=""), "missing-gwt")
    assert got and "given" in got[0], got
    d = story()
    del d["acceptanceCriteria"][0]["then"]
    assert only(d, "missing-gwt")


def test_no_criteria():
    d = story()
    d["acceptanceCriteria"] = []
    assert C.check_ac(d, VAGUE) == [{"id": "acceptanceCriteria", "rule": "no-criteria",
                                     "detail": "the story has no acceptance criteria"}]
    del d["acceptanceCriteria"]
    assert [r for r, _ in rules(d)] == ["no-criteria"], rules(d)
    assert not only(story(), "no-criteria")
    path = os.path.join(TMP, "none.json")
    with open(path, "w", newline="\n") as fh:
        json.dump(dict(story(), acceptanceCriteria=[]), fh)
    p = run([path])
    assert p.returncode == 1 and json.loads(p.stdout)["findings"][0]["rule"] == "no-criteria", p.stdout


def test_finding_ids():
    f = C.check_ac(story(then="loads quickly"), VAGUE)
    assert f[0]["id"] == "AC-1" and set(f[0]) == {"id", "rule", "detail"}


def run(path):
    return subprocess.run([sys.executable, CLI] + path, capture_output=True, text=True)


def test_cli_exit_codes():
    ok, bad = os.path.join(TMP, "ok.json"), os.path.join(TMP, "bad.json")
    with open(ok, "w", newline="\n") as fh:
        json.dump(story(), fh)
    with open(bad, "w", newline="\n") as fh:
        json.dump(story(then="loads quickly"), fh)
    p = run([ok])
    assert p.returncode == 0 and json.loads(p.stdout)["ok"] is True, (p.stdout, p.stderr)
    p = run([bad])
    assert p.returncode == 1 and json.loads(p.stdout)["findings"], (p.stdout, p.stderr)
    assert run([]).returncode == 2
    assert run([os.path.join(TMP, "missing.json")]).returncode == 2


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL %s: %r" % (name, exc))
    print("%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

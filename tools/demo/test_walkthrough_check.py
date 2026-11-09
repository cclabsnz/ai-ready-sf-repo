#!/usr/bin/env python3
"""Tests for walkthrough_check.py: normalisation and diff detection, on temp data only.

Run: python3 tools/demo/test_walkthrough_check.py
"""
import atexit
import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("walkthrough_check", os.path.join(HERE, "walkthrough_check.py"))
wc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wc)

TMP = tempfile.mkdtemp(prefix="walkthrough_check_test_")
atexit.register(shutil.rmtree, TMP, True)


def fresh(name):
    d = os.path.join(TMP, name)
    os.makedirs(d)
    return d


def write(path, text, newline="\n"):
    with open(path, "w", encoding="utf-8", newline=newline) as fh:
        fh.write(text)


# ---- normalisation ----

def test_commit_hashes_normalised():
    out = wc.normalise('indexed 3 nodes, 2 edges at da83fdea\n"commit": "121a920"\n'
                       '"c": "7432f06090ecc18cb9c4c4cbfe4ddd6430142cfd"\n')
    assert out == 'indexed 3 nodes, 2 edges at <commit>\n"commit": "<commit>"\n"c": "<commit>"\n', out


def test_hex_only_words_and_short_numbers_kept():
    text = "defaced facade added 256 nodes, recall 1.0, line 1234567890123\n"
    out = wc.normalise(text)
    assert out == text, out  # all-letter words and an all-digit number are not hashes


def test_changed_long_decimal_is_a_difference():
    d = fresh("decimal")
    write(wc.expected_path(d, 1, "s"), wc.render("s", "c", 0, '{"count": 12345678}'))
    got = wc.compare(d, [("s", wc.render("s", "c", 0, '{"count": 12345679}'))])
    assert got[0][1] is False, got
    assert any("12345679" in l for l in got[0][2]), got


def test_all_letter_hash_in_commit_position_normalised():
    out = wc.normalise('indexed 3 nodes, 2 edges at deadbeef\n"commit": "abcdefa"\nfacade at noon\n')
    assert out == 'indexed 3 nodes, 2 edges at <commit>\n"commit": "<commit>"\nfacade at noon\n', out


def test_bom_expected_file_matches():
    d = fresh("bom")
    rendered = wc.render("s", "python3 x.py", 0, "hello\n")
    write(wc.expected_path(d, 1, "s"), "﻿" + rendered)
    assert wc.compare(d, [("s", rendered)])[0][1] is True


def test_utf16_expected_file_is_a_difference():
    d = fresh("utf16")
    rendered = wc.render("s", "python3 x.py", 0, "hello\n")
    with open(wc.expected_path(d, 1, "s"), "w", encoding="utf-16") as fh:
        fh.write(rendered)
    got = wc.compare(d, [("s", rendered)])
    assert got[0][1] is False and "not UTF-8" in got[0][2][0], got


def test_hash_inside_identifier_kept():
    out = wc.normalise("CaseTrigger_abc1234def x_1234567\n")
    assert out == "CaseTrigger_abc1234def x_1234567\n", out


def test_timestamps_normalised():
    out = wc.normalise('"builtAt": "2026-10-30T00:39:07+00:00", "t": "2026-10-31T09:05:01.123Z"\n')
    assert out == '"builtAt": "<time>", "t": "<time>"\n', out


def test_repo_and_tmp_paths_normalised():
    repo = fresh("repo")
    tmp = fresh("tmpdir")
    text = "%s/demo/org\n%s\\demo\\org\n%s/index\n" % (repo, repo.replace("/", "\\"), tmp)
    out = wc.normalise(text, repo=repo, tmp=tmp)
    assert out == "<repo>/demo/org\n<repo>\\demo\\org\n<tmp>/index\n", out


def test_realpath_variant_normalised():
    real = fresh("real")
    link = os.path.join(TMP, "link")
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        return "skip"
    out = wc.normalise(os.path.realpath(link) + "/x\n", repo=link)
    assert out == "<repo>/x\n", out


def test_crlf_and_trailing_space():
    out = wc.normalise("a  \r\nb\r\n\r\n\r\n")
    assert out == "a\nb\n", repr(out)


def test_single_json_document_reindented():
    out = wc.reformat_json('{"b": 1, "a": [1, 2]}')
    assert out == '{\n  "b": 1,\n  "a": [\n    1,\n    2\n  ]\n}\n', out


def test_mixed_output_left_alone():
    text = '{"a": 1}\n\nKind: impact\n2/3 identical\n'
    assert wc.reformat_json(text) == text


def test_consumers_sorted_by_hop_then_api():
    text = ('{"api": "X", "consumers": [{"api": "b", "hop": 2}, {"api": "z", "hop": 1}, '
            '{"api": "a", "hop": 2}]}')
    out = wc.reformat_json(text, wc.sort_consumers)
    assert out.index('"z"') < out.index('"a"') < out.index('"b"'), out


# ---- diff detection ----

def test_match_passes():
    d = fresh("match")
    rendered = wc.render("s", "python3 x.py", 0, '{"a": 1}')
    write(wc.expected_path(d, 1, "s"), rendered)
    assert wc.compare(d, [("s", rendered)]) == [("s", True, [])]


def test_crlf_expected_file_still_matches():
    d = fresh("crlf")
    rendered = wc.render("s", "python3 x.py", 0, "hello\n")
    write(wc.expected_path(d, 1, "s"), rendered, newline="\r\n")
    assert wc.compare(d, [("s", rendered)])[0][1] is True


def test_changed_output_is_a_difference_with_diff():
    d = fresh("changed")
    write(wc.expected_path(d, 1, "s"), wc.render("s", "python3 x.py", 0, '{"recall": 1.0}'))
    got = wc.compare(d, [("s", wc.render("s", "python3 x.py", 0, '{"recall": 0.5}'))])
    name, ok, diff = got[0]
    assert ok is False
    assert any(l.startswith('-  "recall": 1.0') for l in diff), diff
    assert any(l.startswith('+  "recall": 0.5') for l in diff), diff


def test_changed_exit_code_is_a_difference():
    d = fresh("exit")
    write(wc.expected_path(d, 1, "s"), wc.render("s", "python3 x.py", 0, "ok\n"))
    got = wc.compare(d, [("s", wc.render("s", "python3 x.py", 1, "ok\n"))])
    assert got[0][1] is False and "+exit: 1" in got[0][2], got


def test_missing_expected_file_is_a_difference():
    d = fresh("missing")
    got = wc.compare(d, [("s", "anything\n")])
    assert got[0][1] is False and "no expected file" in got[0][2][0], got


def test_missing_expected_file_on_another_drive():
    # Windows: relpath raises ValueError when the expected folder is on another drive from the repo.
    d = fresh("otherdrive")
    real = os.path.relpath

    def other_drive(path, start=None):
        raise ValueError("path is on mount 'C:', start on mount 'D:'")
    os.path.relpath = other_drive
    try:
        got = wc.compare(d, [("s", "anything\n")])
    finally:
        os.path.relpath = real
    assert got[0][1] is False and wc.expected_path(d, 1, "s") in got[0][2][0], got


def test_commit_change_alone_is_not_a_difference():
    d = fresh("commit")
    write(wc.expected_path(d, 1, "s"), wc.render("s", "c", 0, "at 1a2b3c4d\n"))
    got = wc.compare(d, [("s", wc.render("s", "c", 0, "at 9f8e7d6c\n"))])
    assert got[0][1] is True, got


def test_run_step_on_temp_script():
    d = fresh("script")
    script = os.path.join(d, "emit.py")
    write(script, 'import sys\nprint("{\\"at\\": \\"2026-01-02T03:04:05Z\\"}")\nsys.exit(3)\n')
    code, out, err = wc.run_step([script], cwd=d)
    assert code == 3, (code, err)
    rendered = wc.render("emit", "python3 emit.py", code, out)
    assert rendered == 'step: emit\ncommand: python3 emit.py\nexit: 3\n{\n  "at": "<time>"\n}\n', rendered


def test_steps_are_the_six_deterministic_ones():
    names = [s[0] for s in wc.steps(TMP)]
    assert names == ["index-build", "hop3-consumers", "register-view", "score-demo-202",
                     "consistency", "check-rules"], names
    for name, _cmd, argv, _c in wc.steps(TMP):
        assert os.path.isabs(argv[0]) and os.path.isfile(argv[0]), (name, argv[0])


def test_unknown_show_step_is_usage_error():
    assert wc.main(["--show", "no-such-step"]) == 2


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed = failed = skipped = 0
    for name, fn in tests:
        try:
            result = fn()
        except Exception as exc:  # noqa: BLE001 - report every failure and keep going
            failed += 1
            print("[FAIL] %s: %s: %s" % (name, type(exc).__name__, exc))
            continue
        if result == "skip":
            skipped += 1
            print("[SKIP] %s" % name)
        else:
            passed += 1
            print("[PASS] %s" % name)
    print("%d passed, %d failed" % (passed, failed) + (", %d skipped" % skipped if skipped else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

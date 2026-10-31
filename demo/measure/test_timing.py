#!/usr/bin/env python3
"""Tests for timing.py on synthetic transcripts. Temp trees go under <checkout>/ai-context.

Run: python3 demo/measure/test_timing.py
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
_spec = importlib.util.spec_from_file_location("timing", os.path.join(HERE, "timing.py"))
timing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(timing)

TMP = tempfile.mkdtemp(prefix="timing_", dir=os.path.join(REPO, "ai-context"))


def run(lines):
    path = os.path.join(TMP, "session.jsonl")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = timing.main([path])
    return code, out.getvalue()


def asst(ts, n):
    blocks = [{"type": "tool_use", "id": f"t{i}", "name": "Read", "input": {}} for i in range(n)]
    blocks.append({"type": "text", "text": "ok"})
    return json.dumps({"type": "assistant", "timestamp": ts, "message": {"content": blocks}})


def test_duration_and_tool_calls():
    code, out = run([
        json.dumps({"type": "user", "timestamp": "2026-01-01T10:00:00.000Z", "message": {"content": "hi"}}),
        asst("2026-01-01T10:00:30.000Z", 2),
        "not json at all",
        json.dumps({"type": "summary"}),
        asst("2026-01-01T10:02:05.500Z", 1),
    ])
    result = json.loads(out)
    assert code == 0
    assert result["start"] == "2026-01-01T10:00:00.000Z"
    assert result["end"] == "2026-01-01T10:02:05.500Z"
    assert result["durationSeconds"] == 125.5
    assert result["toolCalls"] == 3


def test_user_tool_result_not_counted():
    code, out = run([
        json.dumps({"type": "user", "timestamp": "2026-01-01T10:00:00Z",
                    "message": {"content": [{"type": "tool_result", "tool_use_id": "t0"}]}}),
        asst("2026-01-01T10:00:10Z", 1),
    ])
    assert code == 0 and json.loads(out)["toolCalls"] == 1


def test_no_timestamps_exit_2():
    code, out = run(["{}", "garbage", json.dumps({"type": "assistant", "message": {"content": []}})])
    assert code == 2 and out == ""


def test_missing_file_exit_2():
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        assert timing.main([os.path.join(TMP, "absent.jsonl")]) == 2


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

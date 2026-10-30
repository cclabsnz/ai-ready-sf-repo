#!/usr/bin/env python3
"""Tests for render_register.py. Plain script: python3 tools/impacts/test_render_register.py"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "render_register.py")


def comp(api, change, typ="ApexClass"):
    return {"api": api, "type": typ, "changeType": change, "impact": "Medium",
            "confidence": "Confirmed", "hop": 0, "evidence": "force-app/x.cls:1", "path": None}


def doc(story, comps, squad="Alpha", decisions=None):
    return {"schemaVersion": 1, "storyId": story, "slug": "demo", "squad": squad,
            "status": "in-flight", "confirmedBy": "Tech Lead",
            "provenance": {"indexStamp": {"commit": "abc1234"}, "frameworkVersion": "1",
                           "model": "m", "assistantVersion": "1", "hops": 1},
            "components": comps, "decisions": decisions or [], "unknowns": []}


def make_root(*docs):
    root = tempfile.mkdtemp()
    for d in docs:
        path = os.path.join(root, "impacts", "%s-%s" % (d["storyId"], d["slug"]))
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "impact.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(d, fh)
    return root


def run(*args):
    p = subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def default_out(root):
    return os.path.join(root, "ai-context", "register", "register.html")


def render(root):
    code, out, err = run("--root", root)
    assert code == 0, (code, err)
    with open(default_out(root), encoding="utf-8") as fh:
        return fh.read()


def sample_root():
    a = doc("DEMO-1", [comp("Shared_X", "modify"), comp("Shared_Y", "review"),
                       comp("Only_A", "new")],
            decisions=[{"text": "<script>alert(1)</script>", "ownerRole": "Tech Lead"}])
    b = doc("DEMO-2", [comp("Shared_X", "delete"), comp("Shared_Y", "modify")], squad="Beta")
    c = doc("DEMO-3", [comp("Both_Review", "review")])
    d = doc("DEMO-4", [comp("Both_Review", "review")], squad="Beta")
    return make_root(a, b, c, d)


def row_class(page, api):
    m = re.search(r'<tr class="([a-z]+)">(?:(?!</tr>).)*?>%s<' % re.escape(api), page, re.S)
    return m.group(1) if m else None


def test_out_outside_ai_context_refused():
    root = sample_root()
    outside = tempfile.mkdtemp()
    try:
        target = os.path.join(outside, "x.html")
        code, _, _ = run("--root", root, "--out", target)
        assert code == 2, code
        assert not os.path.exists(target)
        code, _, _ = run("--root", root, "--out", "ai-context/../README.html")
        assert code == 2, code
        assert not os.path.exists(os.path.join(root, "README.html"))
        assert not os.path.exists(os.path.join(root, "ai-context")), "folder created on refusal"
    finally:
        shutil.rmtree(root)
        shutil.rmtree(outside)


def test_out_symlink_refused():
    root = sample_root()
    outside = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(root, "ai-context", "register"))
        victim = os.path.join(outside, "victim.html")
        with open(victim, "w", encoding="utf-8") as fh:
            fh.write("keep")
        os.symlink(victim, default_out(root))
        code, _, _ = run("--root", root)
        assert code == 2, code
        with open(victim, encoding="utf-8") as fh:
            assert fh.read() == "keep"
    finally:
        shutil.rmtree(root)
        shutil.rmtree(outside)


def test_relative_out_resolves_against_root():
    root = sample_root()
    try:
        code, out, err = run("--root", root, "--out", "ai-context/view/r.html")
        assert code == 0, (code, err)
        path = os.path.join(root, "ai-context", "view", "r.html")
        assert os.path.isfile(path)
        assert os.path.realpath(out.strip()) == os.path.realpath(path), out
    finally:
        shutil.rmtree(root)


def test_escapes_html():
    root = sample_root()
    try:
        page = render(root)
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
        assert "<script" not in page
    finally:
        shutil.rmtree(root)


def test_no_external_refs():
    root = sample_root()
    try:
        page = render(root)
        for bad in ("http://", "https://", "<script", "@import", "url("):
            assert bad not in page, bad
    finally:
        shutil.rmtree(root)


def test_neutral_wording():
    root = sample_root()
    try:
        page = render(root).lower()
        for word in ("we recommend", "should", "approve", "block"):
            assert word not in page, word
    finally:
        shutil.rmtree(root)


def test_conflict_marked():
    root = sample_root()
    try:
        page = render(root)
        assert row_class(page, "Shared_X") == "conflict", row_class(page, "Shared_X")
        assert row_class(page, "Shared_Y") == "watch"
        assert row_class(page, "Both_Review") == "watch"
        assert row_class(page, "Only_A") is None, "single-story component in shared table"
        assert page.count('class="conflict"') == 1
        assert page.count('class="watch"') == 2
        assert page.index(">Shared_X<") < page.index(">Both_Review<") < page.index(">Shared_Y<")
    finally:
        shutil.rmtree(root)


def test_story_list_and_invalid():
    root = sample_root()
    bad = os.path.join(root, "impacts", "DEMO-9-bad")
    os.makedirs(bad)
    with open(os.path.join(bad, "impact.json"), "w", encoding="utf-8") as fh:
        json.dump(doc("<i>x</i>", []), fh)
    try:
        page = render(root)
        for s in ("DEMO-1", "DEMO-2", "DEMO-3", "DEMO-4", "Tech Lead", "in-flight"):
            assert s in page, s
        assert 'id="invalid"' in page
        assert "impacts/DEMO-9-bad/impact.json" in page
        assert "&lt;i&gt;x&lt;/i&gt;" in page and "<i>" not in page
    finally:
        shutil.rmtree(root)


def test_empty_register():
    root = tempfile.mkdtemp()
    try:
        page = render(root)
        assert 'id="invalid"' not in page
        assert 'class="conflict"' not in page and 'class="watch"' not in page
    finally:
        shutil.rmtree(root)


def test_deterministic():
    root = sample_root()
    try:
        first = render(root)
        with open(default_out(root), "rb") as fh:
            raw1 = fh.read()
        second = render(root)
        with open(default_out(root), "rb") as fh:
            raw2 = fh.read()
        assert first == second and raw1 == raw2
        assert b"\r\n" not in raw1
        assert root not in first, "absolute root path leaked into page"
    finally:
        shutil.rmtree(root)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL %s: %r" % (t.__name__, exc))
    print("%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

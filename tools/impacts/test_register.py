#!/usr/bin/env python3
"""Tests for register.py. Plain script: python3 tools/impacts/test_register.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import register  # noqa: E402
from _testutil import SkipTest, run_tests  # noqa: E402

SCRIPT = os.path.join(HERE, "register.py")


def comp(api, change, typ="ApexClass"):
    return {"api": api, "type": typ, "changeType": change, "impact": "Medium",
            "confidence": "Confirmed", "hop": 0, "evidence": "force-app/x.cls:1", "path": None}


def doc(story, comps, status="in-flight", squad="Alpha"):
    return {"schemaVersion": 1, "storyId": story, "slug": "demo", "squad": squad,
            "status": status, "confirmedBy": "Tech Lead",
            "provenance": {"indexStamp": {"commit": "abc1234"}, "frameworkVersion": "1",
                           "model": "m", "assistantVersion": "1", "hops": 1},
            "components": comps, "decisions": [], "unknowns": []}


def write_doc(root, d, folder=None):
    folder = folder or "%s-%s" % (d["storyId"], d["slug"])
    path = os.path.join(root, "impacts", folder)
    os.makedirs(path, exist_ok=True)
    with open(os.path.join(path, "impact.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(d, fh)


def make_root(*docs):
    root = tempfile.mkdtemp()
    for d in docs:
        write_doc(root, d)
    return root


def run(*args):
    p = subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def test_conflict_and_watch():
    a = doc("DEMO-1", [comp("X", "modify"), comp("Y", "review")])
    b = doc("DEMO-2", [comp("X", "modify"), comp("Y", "modify")], squad="Beta")
    root = make_root(a, b)
    try:
        reg = register.load_register(root)
        ov = register.overlaps(a, reg["impacts"])
        assert [(o["api"], o["kind"]) for o in ov] == [("X", "conflict"), ("Y", "watch")], ov
        for o in ov:
            assert [(s["storyId"], s["squad"]) for s in o["stories"]] == [("DEMO-2", "Beta")]
    finally:
        shutil.rmtree(root)


def test_own_story_excluded():
    a = doc("DEMO-1", [comp("X", "modify")])
    root = make_root(a)
    try:
        reg = register.load_register(root)
        assert len(reg["impacts"]) == 1
        assert register.overlaps(a, reg["impacts"]) == []
    finally:
        shutil.rmtree(root)


def test_shipped_excluded():
    a = doc("DEMO-1", [comp("X", "modify")])
    b = doc("DEMO-2", [comp("X", "modify")], status="shipped")
    root = make_root(b)
    try:
        reg = register.load_register(root)
        assert reg["impacts"] == [] and reg["invalid"] == []
        assert register.overlaps(a, reg["impacts"]) == []
    finally:
        shutil.rmtree(root)


def test_invalid_file_listed_not_fatal():
    b = doc("DEMO-2", [comp("X", "modify")])
    root = make_root(b)
    bad = os.path.join(root, "impacts", "DEMO-3-bad")
    os.makedirs(bad)
    with open(os.path.join(bad, "impact.json"), "w", encoding="utf-8") as fh:
        fh.write("{")
    with open(os.path.join(root, "impacts", "squads.json"), "w", encoding="utf-8") as fh:
        json.dump({"squads": ["Alpha", "Beta"]}, fh)
    try:
        reg = register.load_register(root)
        assert len(reg["impacts"]) == 1 and len(reg["invalid"]) == 1, reg
        assert reg["invalid"][0]["path"] == "impacts/DEMO-3-bad/impact.json"
        draft = os.path.join(root, "draft.json")
        with open(draft, "w", encoding="utf-8") as fh:
            json.dump(doc("DEMO-1", [comp("X", "modify")]), fh)
        code, out, _ = run("overlaps", draft, "--root", root)
        assert code == 0, code
        data = json.loads(out)
        assert len(data["invalid"]) == 1 and data["overlaps"][0]["kind"] == "conflict"
        assert data["registerCommit"] == "unknown"
        assert "_dir" not in out and "_commit" not in out
        assert data["overlaps"][0]["stories"][0]["commit"] == "uncommitted"
        code, _, _ = run("overlaps", os.path.join(bad, "impact.json"), "--root", root)
        assert code == 2, code
    finally:
        shutil.rmtree(root)


def test_scope_found_and_missing():
    b = doc("DEMO-2", [comp("X", "modify"), comp("Y", "review")])
    root = make_root(b)
    try:
        code, out, _ = run("scope", "DEMO-2", "--root", root)
        assert code == 0, code
        data = json.loads(out)
        assert data["components"] == ["X", "Y"] and data["squad"] == "Alpha", data
        assert data["source"] == "impact" and "paths" not in data, data
        code, _, _ = run("scope", "DEMO-999", "--root", root)
        assert code == 4, code
    finally:
        shutil.rmtree(root)


def _write_package(root, scope_obj, story="DEMO-2"):
    with open(os.path.join(root, ".ai-framework.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"sourceRoot": "src"}, fh)
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    pkg = {"schemaVersion": 1, "storyId": story, "slug": "demo", "criteria": [{"id": "AC-1"}],
           "scope": scope_obj}
    with open(os.path.join(root, "impacts", "DEMO-2-demo", "build-package.json"), "w",
              encoding="utf-8", newline="\n") as fh:
        json.dump(pkg, fh)


def test_scope_prefers_package():
    b = doc("DEMO-2", [comp("X", "modify"), comp("Y", "new")])
    root = make_root(b)
    try:
        _write_package(root, {"modify": ["src/b.cls", "src/a.cls"],
                              "create": [{"api": "Y", "type": "ApexClass", "path": "src/y.cls"}],
                              "tests": ["src/a_Test.cls"]})
        found = register.scope("DEMO-2", register.load_register(root)["impacts"], root)
        assert found["source"] == "build-package", found
        assert found["paths"] == ["src/a.cls", "src/a_Test.cls", "src/b.cls", "src/y.cls"], found
        assert found["components"] == ["X", "Y"] and found["squad"] == "Alpha", found
        # Without root the function keeps today's behaviour.
        assert register.scope("DEMO-2", register.load_register(root)["impacts"])["source"] == "impact"
        code, out, _ = run("scope", "DEMO-2", "--root", root)
        assert code == 0 and json.loads(out)["source"] == "build-package", out
    finally:
        shutil.rmtree(root)


def test_scope_invalid_package_falls_back():
    b = doc("DEMO-2", [comp("X", "modify")])
    root = make_root(b)
    try:
        _write_package(root, {"modify": ["tools/evil.py"], "create": [], "tests": []})
        found = register.scope("DEMO-2", register.load_register(root)["impacts"], root)
        assert found["source"] == "impact" and "paths" not in found, found
        assert any("outside sourceRoot" in e or "reserved" in e for e in found["packageErrors"]), found
    finally:
        shutil.rmtree(root)


def test_deterministic_order():
    docs = [doc("DEMO-%d" % n, [comp("X", "modify"), comp("Y%d" % n, "new")]) for n in (3, 1, 2)]
    root = make_root(*docs)
    try:
        code1, out1, _ = run("view", "--root", root)
        code2, out2, _ = run("view", "--root", root)
        assert code1 == 0 and out1 == out2
        data = json.loads(out1)
        assert [e["storyId"] for e in data["components"]["X"]] == ["DEMO-1", "DEMO-2", "DEMO-3"]
        assert "_dir" not in out1 and "_commit" not in out1
    finally:
        shutil.rmtree(root)


def test_review_own_is_watch_only():
    a = doc("DEMO-1", [comp("X", "review")])
    b = doc("DEMO-2", [comp("X", "delete")])
    root = make_root(b)
    try:
        ov = register.overlaps(a, register.load_register(root)["impacts"])
        assert [o["kind"] for o in ov] == ["watch"]
    finally:
        shutil.rmtree(root)


def test_deep_json_listed_invalid():
    a = doc("DEMO-1", [comp("X", "modify")])
    root = make_root(a)
    try:
        d = os.path.join(root, "impacts", "DEMO-2-deep")
        os.makedirs(d)
        with open(os.path.join(d, "impact.json"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write("[" * 200000 + "]" * 200000)
        reg = register.load_register(root)
        assert [i["path"] for i in reg["invalid"]] == ["impacts/DEMO-2-deep/impact.json"], reg
        assert "RecursionError" in reg["invalid"][0]["errors"][0]
        assert [x["storyId"] for x in reg["impacts"]] == ["DEMO-1"]
        code, out, err = run("view", "--root", root)
        assert code == 0, err[-300:]
        assert "impacts/DEMO-2-deep/impact.json" in json.loads(out)["invalid"][0]["path"]
    finally:
        shutil.rmtree(root)


def _plain_git(repo, *args):
    """Test setup only: git with hooks off and a fixed identity."""
    return subprocess.run(["git", "-C", repo, "-c", "core.hooksPath=" + os.devnull,
                           "-c", "user.name=Test", "-c", "user.email=test-identity",
                           "-c", "commit.gpgsign=false"] + list(args),
                          capture_output=True, text=True, timeout=60)


def test_planted_git_config_does_not_run():
    if shutil.which("git") is None:
        raise SkipTest("git unavailable")
    repo = tempfile.mkdtemp()
    try:
        write_doc(repo, doc("DEMO-1", [comp("X", "modify")]))
        if _plain_git(repo, "init", "-q").returncode != 0:
            raise SkipTest("git init failed")
        _plain_git(repo, "add", "-A")
        assert _plain_git(repo, "commit", "-q", "-m", "seed").returncode == 0
        marker = os.path.join(repo, "FSMONITOR_RAN")
        hook = os.path.join(repo, "fsmonitor.sh")
        with open(hook, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("#!/bin/sh\ntouch '%s'\nexit 1\n" % marker)
        os.chmod(hook, 0o755)
        assert _plain_git(repo, "config", "core.fsmonitor", hook).returncode == 0
        # Control: an unhardened git command runs the planted script.
        subprocess.run(["git", "-C", repo, "status"], capture_output=True, timeout=60)
        if os.path.exists(marker):
            os.remove(marker)
        else:
            print("NOTE test_planted_git_config_does_not_run: the fsmonitor vector did not "
                  "reproduce unhardened on this platform; the assertions below still run")
        assert register._git(repo, ["status", "--porcelain"]) is not None
        reg = register.load_register(repo)
        assert [d["storyId"] for d in reg["impacts"]] == ["DEMO-1"], reg
        assert reg["impacts"][0]["_commit"] not in ("", "uncommitted"), reg["impacts"][0]
        assert register.register_commit(repo) != "unknown"
        assert not os.path.exists(marker), "planted core.fsmonitor ran"
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def test_git_env_vars_ignored():
    """GIT_DIR, GIT_WORK_TREE and GIT_LITERAL_PATHSPECS in the caller's environment do not redirect git."""
    if shutil.which("git") is None:
        raise SkipTest("git unavailable")
    repo = tempfile.mkdtemp()
    saved = {k: os.environ.get(k) for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_LITERAL_PATHSPECS")}
    try:
        write_doc(repo, doc("DEMO-1", [comp("X", "modify")]))
        if _plain_git(repo, "init", "-q").returncode != 0:
            raise SkipTest("git init failed")
        _plain_git(repo, "add", "-A")
        assert _plain_git(repo, "commit", "-q", "-m", "seed").returncode == 0
        head = _plain_git(repo, "rev-parse", "--short", "HEAD").stdout.strip()
        bogus = os.path.join(repo, "no-such-git-dir")
        os.environ.update(GIT_DIR=bogus, GIT_WORK_TREE=bogus, GIT_LITERAL_PATHSPECS="1")
        env = register._git_env()
        assert not any(k.startswith("GIT_") and k not in ("GIT_CONFIG_NOSYSTEM", "GIT_TERMINAL_PROMPT",
                                                          "GIT_NO_LAZY_FETCH") for k in env), sorted(env)
        assert register.register_commit(repo) == head, register.register_commit(repo)
        reg = register.load_register(repo)
        assert reg["impacts"][0]["_commit"] == head, reg["impacts"][0]
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(repo, ignore_errors=True)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    return run_tests([(t.__name__, t) for t in tests])


if __name__ == "__main__":
    sys.exit(main())

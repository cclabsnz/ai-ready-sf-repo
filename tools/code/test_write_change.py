#!/usr/bin/env python3
"""Tests for implement-story's write_change.py. Plain script: python3 tools/code/test_write_change.py

The checkout's script runs by subprocess with --root <temp root>. The temp root holds data only: a synthetic
build package (no provenance, so no confirmedBy), the scoped files, and the draft. Temp roots are made inside
the checkout's ai-context/ and removed afterwards, because the writer refuses any output outside it.
"""
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tools", "impacts"))

from _testutil import run_tests, symlink  # noqa: E402

SCRIPT = os.path.join(REPO, "framework", "skills", "implement-story", "scripts", "write_change.py")
RENDERED = [os.path.join(REPO, d, "skills", "implement-story", "scripts", "write_change.py")
            for d in (".claude", ".github")]
CTX = os.path.join(REPO, "ai-context")
STORY, SLUG = "DEMO-931", "widget-assign"
BASE = "src/force-app/main/default/classes"
SVC = BASE + "/WidgetService.cls"
NEW = BASE + "/WidgetRouter.cls"
TEST = BASE + "/WidgetService_Test.cls"
DONE = ["python3 tools/code/check_trace.py --skeletons %s" % STORY,
        "python3 tools/code/check_rules.py --from-config",
        "python3 tools/code/check_trace.py %s" % STORY]

PLANT = ("import os\n"
         "open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname("
         "os.path.abspath(__file__)))), 'PLANTED_MARKER'), 'w').close()\n"
         "raise SystemExit(0)\n")

TEST_SRC = ("@IsTest\nprivate class WidgetService_Test {\n"
            "    @IsTest\n    static void assignsOnInsert() {\n        // AC-1\n"
            "        System.assertEquals(1, 1, 'one widget');\n    }\n"
            "    @IsTest\n    static void keepsOwner() {\n        // EC-2\n"
            "        System.assertEquals(2, 2, 'two widgets');\n    }\n}\n")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def package():
    return {"schemaVersion": 1, "storyId": STORY, "slug": SLUG,
            "criteria": [{"id": "AC-1", "given": "g", "when": "w", "then": "t", "examples": ["x"]},
                         {"id": "EC-2", "given": "g", "when": "w", "then": "t", "examples": []}],
            "scope": {"modify": [SVC, SVC + "-meta.xml"],
                      "create": [{"api": "WidgetRouter", "type": "ApexClass", "path": NEW},
                                 {"api": "WidgetRouter", "type": "ApexClass", "path": NEW + "-meta.xml"}],
                      "tests": [TEST, TEST + "-meta.xml"]},
            "rules": [], "done": list(DONE)}


def make_root(pkg=None):
    os.makedirs(CTX, exist_ok=True)
    root = tempfile.mkdtemp(prefix="write_change_", dir=CTX)
    write(os.path.join(root, SVC), "public with sharing class WidgetService {\n    void run() {}\n}\n")
    write(os.path.join(root, NEW), "public with sharing class WidgetRouter {\n    void route() {}\n}\n")
    write(os.path.join(root, TEST), TEST_SRC)
    write(os.path.join(root, "impacts", "%s-%s" % (STORY, SLUG), "build-package.json"),
          json.dumps(pkg or package(), indent=2))
    return root


def good_draft():
    return {"storyId": STORY,
            "files": [{"path": SVC, "component": "WidgetService", "changeType": "modify",
                       "evidence": SVC + ":2", "confidence": "Confirmed"},
                      {"path": NEW, "component": "WidgetRouter", "changeType": "new",
                       "evidence": NEW + ":1", "confidence": "Confirmed"},
                      {"path": TEST, "component": "WidgetService_Test", "changeType": "new",
                       "evidence": TEST + ":5", "confidence": "Confirmed"}],
            "criteriaToTests": {"AC-1": [TEST + "#assignsOnInsert"], "EC-2": [TEST + "#keepsOwner"]},
            "done": [{"command": c, "exit": 0} for c in DONE]}


def draft_file(doc):
    d = tempfile.mkdtemp(prefix="write_change_in_")
    path = os.path.join(d, "draft.json")
    write(path, json.dumps(doc))
    return d, path


def run(root, draft_path, cwd=None, script=SCRIPT, extra=(), slug=SLUG):
    args = [sys.executable, script, "--id", STORY, "--slug", slug, "--draft", draft_path,
            "--root", root] + list(extra)
    p = subprocess.run(args, capture_output=True, text=True, cwd=cwd or REPO)
    return p.returncode, p.stdout + p.stderr


def out_dir(root):
    return os.path.join(root, "ai-context", "%s-%s" % (STORY, SLUG))


def cleanup(*paths):
    for p in paths:
        shutil.rmtree(p, ignore_errors=True)


def expect_refused(doc, text, code=1, pkg=None):
    root = make_root(pkg)
    tmp, d = draft_file(doc)
    try:
        got, out = run(root, d)
        assert got == code and text in out, (text, got, out)
        assert not os.path.exists(os.path.join(root, "ai-context")), "files were created"
    finally:
        cleanup(root, tmp)


def test_valid():
    root = make_root()
    tmp, d = draft_file(good_draft())
    try:
        code, out = run(root, d)
        assert code == 0, out
        printed = json.loads(out)
        rel_pkg = "impacts/%s-%s/build-package.json" % (STORY, SLUG)
        assert printed["package"] == rel_pkg and printed["doneFailed"] == [], printed
        doc = json.loads(read(os.path.join(out_dir(root), "change.json")))
        assert doc["schemaVersion"] == 1 and doc["slug"] == SLUG and doc["storyId"] == STORY, doc
        assert doc["package"]["path"] == rel_pkg and len(doc["package"]["sha1"]) == 40, doc["package"]
        md = read(os.path.join(out_dir(root), "change.md"))
        assert "| `%s` | WidgetService | modify | `%s:2` | Confirmed |" % (SVC, SVC) in md, md
        assert "| AC-1 | `%s#assignsOnInsert` |" % TEST in md, md
        assert "Every done command was reported with exit 0 (Inferred)." in md, md
        assert ("Exit codes are the session's own report in the draft; write_change.py does not run or "
                "re-run the commands. Confidence: Inferred.") in md, md
        assert "Every done command exited 0." not in md, md
        for word in ("should", "we recommend", "approve", "block"):
            assert word not in md.lower(), word
        first = read(os.path.join(out_dir(root), "change.json")), md
        code, out = run(root, d)
        assert code == 0, out
        again = read(os.path.join(out_dir(root), "change.json")), read(os.path.join(out_dir(root), "change.md"))
        assert first == again, "output differs between runs"
        assert "\r" not in md
    finally:
        cleanup(root, tmp)


def test_failed_done_is_recorded():
    doc = good_draft()
    doc["done"][2]["exit"] = 1
    root = make_root()
    tmp, d = draft_file(doc)
    try:
        code, out = run(root, d)
        assert code == 0, out
        assert json.loads(out)["doneFailed"] == [DONE[2]], out
        md = read(os.path.join(out_dir(root), "change.md"))
        assert "Not done (Inferred): `%s` reported a non-zero exit." % DONE[2] in md, md
        assert "does not run or re-run the commands" in md, md
    finally:
        cleanup(root, tmp)


def test_file_outside_scope_fails():
    doc = good_draft()
    doc["files"].append({"path": BASE + "/OtherService.cls", "component": "OtherService",
                         "changeType": "modify", "evidence": BASE + "/OtherService.cls:1",
                         "confidence": "Confirmed"})
    expect_refused(doc, "OtherService.cls is outside the package scope")
    doc = good_draft()
    doc["files"][0]["changeType"] = "new"
    expect_refused(doc, "is in scope.modify; changeType is \"new\"")
    doc = good_draft()
    doc["files"][1]["component"] = "OtherRouter"
    expect_refused(doc, "is scope.create for WidgetRouter")


def test_criterion_without_test_fails():
    doc = good_draft()
    del doc["criteriaToTests"]["EC-2"]
    expect_refused(doc, "criterion EC-2 maps to no test")
    doc = good_draft()
    doc["criteriaToTests"]["EC-2"] = []
    expect_refused(doc, "criterion EC-2 maps to no test")
    doc = good_draft()
    doc["criteriaToTests"]["EC-2"] = [TEST + "-meta.xml#keepsOwner"]
    expect_refused(doc, "metadata companion")
    doc = good_draft()
    doc["criteriaToTests"]["EC-2"] = [SVC + "#run"]
    expect_refused(doc, "is not in scope.tests")
    doc = good_draft()
    doc["criteriaToTests"]["AC-9"] = [TEST + "#assignsOnInsert"]
    expect_refused(doc, "AC-9\" is not a package criterion id")
    doc = good_draft()
    doc["criteriaToTests"]["EC-2"] = [TEST + "#missingMethod"]
    expect_refused(doc, "method missingMethod not found")


def test_missing_done_fails():
    doc = good_draft()
    del doc["done"][1]
    expect_refused(doc, "was not run (no entry in done)")
    doc = good_draft()
    doc["done"].append({"command": "python3 tools/other.py", "exit": 0})
    expect_refused(doc, "is not in the package done[]")


def test_bool_exit_refused():
    doc = good_draft()
    doc["done"][0]["exit"] = True
    expect_refused(doc, "has exit true, not an integer")
    doc = good_draft()
    doc["done"][0]["exit"] = "0"
    expect_refused(doc, "not an integer")


def test_evidence_checked():
    doc = good_draft()
    doc["files"][0]["evidence"] = SVC + ":99"
    expect_refused(doc, "past the end")
    doc = good_draft()
    doc["files"][0]["evidence"] = NEW + ":1"
    expect_refused(doc, "is not '%s:<line>'" % SVC)
    doc = good_draft()
    doc["files"][0]["confidence"] = "Sure"
    expect_refused(doc, "confidence \"Sure\"")


def test_draft_cannot_carry_writer_keys():
    for key in ("schemaVersion", "slug", "package"):
        doc = good_draft()
        doc[key] = 1
        expect_refused(doc, key)
    doc = good_draft()
    doc["storyId"] = "DEMO-1"
    expect_refused(doc, "draft storyId")


def test_package_mismatch_exit_2():
    pkg = package()
    pkg["slug"] = "other-slug"
    expect_refused(good_draft(), "build package is for %s-other-slug" % STORY, code=2, pkg=pkg)


def test_package_folders_exit_2():
    root = make_root()
    tmp, d = draft_file(good_draft())
    try:
        os.makedirs(os.path.join(root, "impacts", STORY + "-second"))
        code, out = run(root, d)
        assert code == 2 and "expected exactly one" in out, out
        cleanup(os.path.join(root, "impacts"))
        code, out = run(root, d)
        assert code == 2 and "found none" in out, out
        # An explicit --package works with no impacts folder at all.
        pdir = tempfile.mkdtemp(prefix="write_change_pkg_")
        try:
            write(os.path.join(pdir, "build-package.json"), json.dumps(package()))
            code, out = run(root, d, extra=["--package", os.path.join(pdir, "build-package.json")])
            assert code == 0, out
        finally:
            cleanup(pdir)
    finally:
        cleanup(root, tmp)


def test_symlinked_output_refused():
    for name in ("change.json", "change.md"):
        root = make_root()
        outside = tempfile.mkdtemp(prefix="write_change_outside_")
        tmp, d = draft_file(good_draft())
        target = os.path.join(outside, "target.txt")
        write(target, "original\n")
        try:
            os.makedirs(out_dir(root))
            symlink(target, os.path.join(out_dir(root), name))
            code, out = run(root, d)
            assert code != 0 and "symlink" in out, (name, out)
            assert read(target) == "original\n", (name, read(target))
            assert os.listdir(out_dir(root)) == [name], os.listdir(out_dir(root))
        finally:
            cleanup(root, outside, tmp)


def test_out_dir_outside_ai_context_refused():
    root = make_root()
    outside = tempfile.mkdtemp(prefix="write_change_outside_")
    tmp, d = draft_file(good_draft())
    try:
        code, out = run(root, d, slug="../../escape")
        assert code == 2 and "--slug '../../escape' does not match" in out, out
        symlink(outside, os.path.join(root, "ai-context"))
        code, out = run(root, d)
        assert code == 2 and "resolves outside <root>/ai-context/" in out, out
        assert os.listdir(outside) == [], os.listdir(outside)
    finally:
        cleanup(root, outside, tmp)


def test_root_never_supplies_code():
    root = make_root()
    tmp, d = draft_file(good_draft())
    for rel in ("tools/impacts/safe_write.py", "safe_write.py", "json.py", "glob.py"):
        write(os.path.join(root, rel), PLANT)
    try:
        code, out = run(root, d, cwd=root)
        assert code == 0, out
        assert not os.path.exists(os.path.join(root, "PLANTED_MARKER")), "root code ran"
        assert os.path.exists(os.path.join(out_dir(root), "change.json")), out
    finally:
        cleanup(root, tmp)


def test_md_write_failure_removes_json():
    spec = importlib.util.spec_from_file_location("write_change_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    real = mod.write_nofollow
    calls = []

    def flaky(path, data):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("simulated disk full")
        return real(path, data)

    mod.write_nofollow = flaky
    root = make_root()
    tmp, d = draft_file(good_draft())
    try:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = mod.main(["--id", STORY, "--slug", SLUG, "--draft", d, "--root", root])
        assert code == 2, (code, err.getvalue())
        assert [os.path.basename(p) for p in calls] == ["change.json", "change.md"], calls
        assert "change.json removed" in err.getvalue(), err.getvalue()
        assert os.listdir(out_dir(root)) == [], os.listdir(out_dir(root))
    finally:
        cleanup(root, tmp)


def test_rendered_copies_find_repo_root():
    present = [p for p in RENDERED if os.path.isfile(p)]
    assert present == RENDERED, "render.py has not copied write_change.py: %s" % RENDERED
    for path in RENDERED:
        here = os.path.dirname(path)
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here))))
        assert os.path.samefile(repo, REPO), path
    root = make_root()
    tmp, d = draft_file(good_draft())
    try:
        for path in RENDERED:
            code, out = run(root, d, script=path)
            assert code == 0, (path, out)
    finally:
        cleanup(root, tmp)


def main():
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    return run_tests(tests, show_pass=True)


if __name__ == "__main__":
    sys.exit(main())

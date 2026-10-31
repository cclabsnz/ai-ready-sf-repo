#!/usr/bin/env python3
"""Tests for solution-design's write_design.py. Plain script: python3 tools/designs/test_write_design.py

The checkout's script runs by subprocess with --root <temp root> and --index <temp index>. The temp
root holds data only. Temp roots are made inside the checkout's ai-context/ and removed afterwards,
because the writer refuses any output outside it. Tests never read <checkout>/index.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "tools", "impacts"))

from _testutil import run_tests, symlink  # noqa: E402
from validate_design import validate_design  # noqa: E402
from design_md import render_md  # noqa: E402

SCRIPT = os.path.join(REPO, "framework", "skills", "solution-design", "scripts", "write_design.py")
RENDERED = [os.path.join(REPO, d, "skills", "solution-design", "scripts", "write_design.py")
            for d in (".claude", ".github")]
CLS = "force-app/main/default/classes/WidgetService.cls"
STORY, SLUG = "DEMO-921", "widget-resize"
CTX = os.path.join(REPO, "ai-context")
IDX = {"stamp": {"commit": "feedc0de", "indexVersion": "0.5.0", "builtAt": "synthetic"},
       "nodes": {"WidgetService": {"type": "ApexClass", "path": CLS}}, "edges": []}

PLANT = ("import os\n"
         "open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname("
         "os.path.abspath(__file__)))), 'PLANTED_MARKER'), 'w').close()\n"
         "raise SystemExit(0)\n")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def make_root():
    os.makedirs(CTX, exist_ok=True)
    root = tempfile.mkdtemp(prefix="write_design_", dir=CTX)
    write(os.path.join(root, CLS), "public with sharing class WidgetService {\n    void run() {}\n}\n")
    write(os.path.join(root, "index", "metadata.json"), json.dumps(IDX))
    write(os.path.join(root, "VERSION"), "0.1.0\n")
    return root


def good_draft():
    return {
        "storyId": STORY, "slug": SLUG,
        "options": [
            {"id": "OPT-1", "title": "Do nothing", "summary": "Keep the current widget service.",
             "doNothing": True, "components": [],
             "tradeOffs": [{"criterion": "reuse", "note": "No change to the build."}],
             "impactSummary": "No metadata changes."},
            {"id": "OPT-2", "title": "Extend WidgetService", "summary": "Add a resize method.",
             "doNothing": False,
             "components": [{"api": "WidgetService", "type": "ApexClass", "changeType": "modify",
                             "evidence": CLS + ":1", "confidence": "Confirmed"},
                            {"api": "WidgetSize__c", "type": "CustomObject", "changeType": "new",
                             "evidence": None, "confidence": "Inferred"}],
             "tradeOffs": [{"criterion": "maintainability", "note": "One class holds widget logic."}],
             "impactSummary": "One class changes and one object is added."},
        ],
        "recommendation": {"optionId": "OPT-2", "reasons": ["Reuses the existing service."]},
    }


def draft_file(doc):
    d = tempfile.mkdtemp(prefix="write_design_in_")
    path = os.path.join(d, "draft.json")
    write(path, json.dumps(doc))
    return d, path


def run(root, draft_path, cwd=None, slug=SLUG, script=SCRIPT, index=None, extra=()):
    args = [sys.executable, script, "--id", STORY, "--slug", slug, "--draft", draft_path,
            "--root", root, "--index", index or os.path.join(root, "index")] + list(extra)
    p = subprocess.run(args, capture_output=True, text=True, cwd=cwd or REPO)
    return p.returncode, p.stdout + p.stderr


def out_dir(root):
    return os.path.join(root, "ai-context", "%s-%s" % (STORY, SLUG))


def cleanup(*paths):
    for p in paths:
        shutil.rmtree(p, ignore_errors=True)


def test_writes_valid():
    root = make_root()
    tmp, d = draft_file(good_draft())
    try:
        code, out = run(root, d, extra=["--model", "m-1", "--assistant-version", "cc-2"])
        assert code == 0, out
        printed = json.loads(out)
        assert printed["designJson"].endswith("design.json") and printed["designMd"].endswith("design.md"), printed
        assert printed["recommendedOption"] == "OPT-2", printed
        doc = json.loads(read(os.path.join(out_dir(root), "design.json")))
        idx = json.loads(read(os.path.join(root, "index", "metadata.json")))
        assert validate_design(doc, "draft", root, idx=idx, check_evidence=True) == [], doc
        assert doc["status"] == "draft" and doc["schemaVersion"] == 1, doc
        assert doc["provenance"] == {"indexStamp": IDX["stamp"], "frameworkVersion": "0.1.0",
                                     "model": "m-1", "assistantVersion": "cc-2"}, doc["provenance"]
        assert "confirmedBy" not in doc and "chosenOption" not in doc, doc
        md = read(os.path.join(out_dir(root), "design.md"))
        for heading in ("## Options", "## Trade-offs", "## Recommendation", "## Components"):
            assert heading in md, (heading, md)
        assert "| Option | Title | Do nothing | Summary | Impact summary |" in md, md
        assert "| `WidgetService` | ApexClass | modify | `%s:1` | Confirmed |" % CLS in md, md
        assert "| `WidgetSize__c` | CustomObject | new | none | Inferred |" in md, md
        assert "OPT-2" in md.split("## Recommendation", 1)[1] and "Reuses the existing service." in md, md
        assert "provisional" in md and "named owner" in md, md
        for word in ("should", "we recommend", "approve", "block"):
            assert word not in md.lower(), word
        first = read(os.path.join(out_dir(root), "design.json")), md
        code, out = run(root, d, extra=["--model", "m-1", "--assistant-version", "cc-2"])
        assert code == 0, out
        again = read(os.path.join(out_dir(root), "design.json")), read(os.path.join(out_dir(root), "design.md"))
        assert first == again, "output differs between runs"
        assert "\r" not in md
        assert md == render_md(doc), "design.md is not tools/designs/design_md.py output"
    finally:
        cleanup(root, tmp)


def test_provenance_defaults_unknown():
    root = make_root()
    tmp, d = draft_file(good_draft())
    try:
        code, out = run(root, d)
        assert code == 0, out
        doc = json.loads(read(os.path.join(out_dir(root), "design.json")))
        assert doc["provenance"]["model"] == "unknown", doc["provenance"]
        assert doc["provenance"]["assistantVersion"] == "unknown", doc["provenance"]
    finally:
        cleanup(root, tmp)


def test_invalid_writes_nothing():
    root = make_root()
    try:
        cases = []
        doc = good_draft()
        doc["options"][1]["components"][0]["evidence"] = CLS + ":999"
        cases.append((doc, ":999"))
        doc = good_draft()
        doc["options"][1]["components"][0]["api"] = "GhostService"
        cases.append((doc, "GhostService"))
        doc = good_draft()
        doc["recommendation"]["optionId"] = "OPT-5"
        cases.append((doc, "OPT-5"))
        for doc, text in cases:
            tmp, d = draft_file(doc)
            try:
                code, out = run(root, d)
                assert code == 1 and text in out, (text, out)
                assert not os.path.exists(os.path.join(root, "ai-context")), "files were created"
            finally:
                cleanup(tmp)
    finally:
        cleanup(root)


def test_draft_cannot_carry_writer_keys():
    root = make_root()
    try:
        for key, val in (("schemaVersion", 1), ("status", "draft"), ("provenance", {}),
                         ("confirmedBy", "Tech Lead"), ("chosenOption", "OPT-2")):
            doc = good_draft()
            doc[key] = val
            tmp, d = draft_file(doc)
            try:
                code, out = run(root, d)
                assert code == 1 and key in out, (key, out)
                assert not os.path.exists(os.path.join(root, "ai-context")), key
            finally:
                cleanup(tmp)
        doc = good_draft()
        doc["storyId"] = "DEMO-999"
        tmp, d = draft_file(doc)
        try:
            code, out = run(root, d)
            assert code == 1 and "storyId" in out, out
        finally:
            cleanup(tmp)
    finally:
        cleanup(root)


def test_missing_index_exit_2():
    root = make_root()
    tmp, d = draft_file(good_draft())
    try:
        code, out = run(root, d, index=os.path.join(root, "no-index"))
        assert code == 2 and "index" in out, out
        assert not os.path.exists(os.path.join(root, "ai-context")), "files were created"
    finally:
        cleanup(root, tmp)


def test_root_never_supplies_code():
    root = make_root()
    tmp, d = draft_file(good_draft())
    for rel in ("tools/impacts/validate.py", "tools/impacts/safe_write.py",
                "tools/designs/validate_design.py", "tools/designs/design_md.py",
                "tools/stories/validate_story.py",
                "tools/index/query.py"):
        write(os.path.join(root, rel), PLANT)
    try:
        code, out = run(root, d, cwd=root)
        assert code == 0, out
        assert not os.path.exists(os.path.join(root, "PLANTED_MARKER")), "root code ran"
        assert os.path.exists(os.path.join(out_dir(root), "design.json")), out
    finally:
        cleanup(root, tmp)


def test_symlinked_output_refused():
    for name in ("design.json", "design.md"):
        root = make_root()
        outside = tempfile.mkdtemp(prefix="write_design_outside_")
        tmp, d = draft_file(good_draft())
        target = os.path.join(outside, "target.txt")
        write(target, "original\n")
        try:
            os.makedirs(out_dir(root))
            symlink(target, os.path.join(out_dir(root), name))
            code, out = run(root, d)
            assert code != 0, (name, out)
            assert "symlink" in out, (name, out)
            assert read(target) == "original\n", (name, read(target))
            assert os.listdir(out_dir(root)) == [name], os.listdir(out_dir(root))
        finally:
            cleanup(root, outside, tmp)


def test_out_dir_outside_ai_context_refused():
    root = make_root()
    outside = tempfile.mkdtemp(prefix="write_design_outside_")
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


def test_root_outside_checkout_refused():
    root = tempfile.mkdtemp(prefix="write_design_elsewhere_")
    write(os.path.join(root, "index", "metadata.json"), json.dumps(IDX))
    tmp, d = draft_file(good_draft())
    try:
        code, out = run(root, d)
        assert code == 2 and "outside the checkout's ai-context/" in out, out
        assert not os.path.exists(os.path.join(root, "ai-context")), "files were created"
    finally:
        cleanup(root, tmp)


def test_md_tables_escape_pipes():
    root = make_root()
    doc = good_draft()
    doc["options"][1]["title"] = "Extend A|B"
    doc["options"][1]["tradeOffs"][0]["note"] = "x|y"
    tmp, d = draft_file(doc)
    try:
        code, out = run(root, d)
        assert code == 0, out
        md = read(os.path.join(out_dir(root), "design.md"))
        row = [l for l in md.splitlines() if l.startswith("| OPT-2 |")][0]
        assert "A\\|B" in row and len(row.replace("\\|", "").strip("|").split("|")) == 5, row
        assert "x\\|y" in md, md
    finally:
        cleanup(root, tmp)


def test_md_write_failure_removes_json():
    """design.md fails after design.json was written: design.json is removed, exit 2."""
    import contextlib
    import importlib.util
    import io
    spec = importlib.util.spec_from_file_location("write_design_under_test", SCRIPT)
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
            code = mod.main(["--id", STORY, "--slug", SLUG, "--draft", d, "--root", root,
                             "--index", os.path.join(root, "index")])
        assert code == 2, (code, err.getvalue())
        assert [os.path.basename(p) for p in calls] == ["design.json", "design.md"], calls
        assert "simulated disk full" in err.getvalue() and "design.json removed" in err.getvalue(), err.getvalue()
        assert os.listdir(out_dir(root)) == [], os.listdir(out_dir(root))
    finally:
        cleanup(root, tmp)


def test_rendered_copies_find_repo_root():
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

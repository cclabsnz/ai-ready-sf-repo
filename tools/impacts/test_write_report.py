#!/usr/bin/env python3
"""Tests for story-impact's write_report.py. Plain script: python3 tools/impacts/test_write_report.py

The checkout's script runs by subprocess with --root <temp root>. The temp root holds data only.
Temp roots are made inside the checkout's ai-context/ and removed afterwards, because the writer
refuses any output outside it.
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

from _testutil import run_tests, symlink  # noqa: E402
from validate import validate  # noqa: E402

SCRIPT = os.path.join(REPO, "framework", "skills", "story-impact", "scripts", "write_report.py")
RENDERED = [os.path.join(REPO, d, "skills", "story-impact", "scripts", "write_report.py")
            for d in (".claude", ".github")]
INDEX_COMMIT = "feedc0de1234567"
CLS = "force-app/main/default/classes/WidgetService.cls"
STORY, SLUG = "DEMO-901", "widget-change"
# Temp roots live inside the checkout's ai-context/, the only place the writer may write.
CTX = os.path.join(REPO, "ai-context")

PLANT = ("import os\n"
         "open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname("
         "os.path.abspath(__file__)))), 'PLANTED_MARKER'), 'w').close()\n"
         "raise SystemExit(0)\n")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def other_record():
    return {"schemaVersion": 1, "storyId": "DEMO-902", "slug": "other-widget", "squad": "Service Ops",
            "status": "in-flight", "confirmedBy": "Tech Lead",
            "provenance": {"indexStamp": {"commit": "abc1234"}, "frameworkVersion": "0.1.0",
                           "model": "m", "assistantVersion": "unknown", "hops": 1},
            "components": [{"api": "WidgetService", "type": "ApexClass", "changeType": "modify",
                            "impact": "High", "confidence": "Confirmed", "hop": 0,
                            "evidence": CLS + ":2", "path": CLS}],
            "decisions": [], "unknowns": []}


def make_root(register=True):
    os.makedirs(CTX, exist_ok=True)
    root = tempfile.mkdtemp(prefix="write_report_", dir=CTX)
    write(os.path.join(root, CLS), "public with sharing class WidgetService {\n"
                                   "    public static void run() {}\n}\n")
    write(os.path.join(root, "VERSION"), "9.9.9\n")
    write(os.path.join(root, "index", "metadata.json"), json.dumps(
        {"stamp": {"commit": INDEX_COMMIT, "indexVersion": 1, "builtAt": "synthetic"},
         "nodes": {}, "edges": []}))
    if register:
        write(os.path.join(root, "impacts", "squads.json"),
              json.dumps({"version": 1, "squads": ["Customer Care", "Service Ops"]}))
        write(os.path.join(root, "impacts", "DEMO-902-other-widget", "impact.json"),
              json.dumps(other_record()))
    return root


def inputs(root, rows=None, meta=None):
    scan = os.path.join(tempfile.mkdtemp(prefix="write_report_in_"))
    if rows is None:
        rows = [{"api": "WidgetService", "layer": "Apex", "type": "ApexClass", "ownership": "Custom",
                 "changeType": "modify", "impact": "High", "scale": "S", "hop": "0",
                 "evidence": CLS + ":2", "confidence": "Confirmed", "note": "entry point"}]
    if meta is None:
        meta = {"squad": "Customer Care", "hops": 2, "model": "test-model",
                "assistantVersion": "unknown",
                "decisions": [{"text": "Agree the widget sequencing", "ownerRole": "Tech Lead"}],
                "unknowns": ["Org-only config for widgets"]}
    cpath = os.path.join(scan, "classified.json")
    mpath = os.path.join(scan, "meta.json")
    write(cpath, json.dumps(rows))
    write(mpath, json.dumps(meta))
    return scan, cpath, mpath


def run(root, *extra, cwd=None, story=STORY, slug=SLUG, script=SCRIPT):
    args = [sys.executable, script, "--id", story, "--slug", slug, "--root", root] + list(extra)
    p = subprocess.run(args, capture_output=True, text=True, cwd=cwd or REPO)
    return p.returncode, p.stdout + p.stderr


def out_dir(root):
    return os.path.join(root, "ai-context", "%s-%s" % (STORY, SLUG))


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def cleanup(*paths):
    for p in paths:
        shutil.rmtree(p, ignore_errors=True)


def test_root_never_supplies_code():
    root = make_root()
    scan, c, m = inputs(root)
    for rel in ("tools/impacts/register.py", "tools/impacts/validate.py", "tools/index/query.py"):
        write(os.path.join(root, rel), PLANT)
    try:
        code, out = run(root, "--classified", c, "--meta", m, cwd=root)
        assert code == 0, out
        assert not os.path.exists(os.path.join(root, "PLANTED_MARKER")), "root code ran"
        doc = json.loads(read(os.path.join(out_dir(root), "impact.json")))
        assert doc["provenance"]["indexStamp"]["commit"] == INDEX_COMMIT, doc["provenance"]
        assert doc["provenance"]["frameworkVersion"] == "9.9.9", doc["provenance"]
    finally:
        cleanup(root, scan)


def test_out_dir_outside_ai_context_refused():
    root = make_root()
    outside = tempfile.mkdtemp(prefix="write_report_outside_")
    scan, c, m = inputs(root)
    try:
        code, out = run(root, "--classified", c, "--meta", m, slug="../../escape")
        assert code == 2 and "--slug '../../escape' does not match" in out, out
        code, out = run(root, "--classified", c, "--meta", m, story="../x")
        assert code == 2 and "--id '../x' does not match" in out, out
        assert not os.path.exists(os.path.join(root, "ai-context")), "files were created"
        symlink(outside, os.path.join(root, "ai-context"))
        code, out = run(root, "--classified", c, "--meta", m)
        assert code == 2 and "resolves outside <root>/ai-context/" in out, out
        assert os.listdir(outside) == [], os.listdir(outside)
        os.remove(os.path.join(root, "ai-context"))
        os.makedirs(os.path.join(root, "ai-context"))
        symlink(outside, out_dir(root))
        code, out = run(root, "--classified", c, "--meta", m)
        assert code == 2 and "resolves outside <root>/ai-context/" in out, out
        assert os.listdir(outside) == [], os.listdir(outside)
    finally:
        cleanup(root, outside, scan)


def test_root_outside_checkout_refused():
    """A --root outside the checkout's ai-context/ cannot move the output there."""
    inside = make_root()
    root = tempfile.mkdtemp(prefix="write_report_elsewhere_")
    for rel in (CLS, "VERSION", os.path.join("index", "metadata.json")):
        os.makedirs(os.path.dirname(os.path.join(root, rel)) or root, exist_ok=True)
        shutil.copyfile(os.path.join(inside, rel), os.path.join(root, rel))
    scan, c, m = inputs(root)
    try:
        code, out = run(root, "--classified", c, "--meta", m)
        assert code == 2 and "outside the checkout's ai-context/" in out, out
        assert not os.path.exists(os.path.join(root, "ai-context")), "files were created"
    finally:
        cleanup(root, inside, scan)


def test_symlinked_output_file_refused():
    for name in ("impact.json", "impact.md"):
        root = make_root()
        outside = tempfile.mkdtemp(prefix="write_report_outside_")
        scan, c, m = inputs(root)
        target = os.path.join(outside, "target.txt")
        write(target, "original\n")
        try:
            os.makedirs(out_dir(root))
            symlink(target, os.path.join(out_dir(root), name))
            code, out = run(root, "--classified", c, "--meta", m)
            assert code != 0, (name, out)
            assert "symlink" in out, (name, out)
            assert read(target) == "original\n", (name, read(target))
            assert os.listdir(out_dir(root)) == [name], os.listdir(out_dir(root))
        finally:
            cleanup(root, outside, scan)


def test_writes_valid_json_and_md():
    root = make_root()
    scan, c, m = inputs(root)
    try:
        code, out = run(root, "--classified", c, "--meta", m)
        assert code == 0, out
        doc = json.loads(read(os.path.join(out_dir(root), "impact.json")))
        errs = validate(doc, "draft", root, check_evidence=True)
        assert errs == [], errs
        assert doc["status"] == "draft"
        comp = doc["components"][0]
        assert comp["hop"] == 0 and comp["path"] == CLS, comp
        assert "layer" not in comp and "note" not in comp, comp
        md = read(os.path.join(out_dir(root), "impact.md"))
        assert "- (Tech Lead): Agree the widget sequencing" in md, md
        assert "- (owner role): ..." not in md, md
        first = read(os.path.join(out_dir(root), "impact.json")), md
        code, out = run(root, "--classified", c, "--meta", m)
        assert code == 0, out
        again = read(os.path.join(out_dir(root), "impact.json")), read(
            os.path.join(out_dir(root), "impact.md"))
        assert first == again, "output differs between runs"
    finally:
        cleanup(root, scan)


def test_overlap_section_names_other_story():
    root = make_root()
    scan, c, m = inputs(root)
    try:
        code, out = run(root, "--classified", c, "--meta", m)
        assert code == 0, out
        md = read(os.path.join(out_dir(root), "impact.md"))
        section = md.split("## Overlaps with other stories", 1)[1].split("\n## ", 1)[0]
        rows = [l for l in section.splitlines() if l.startswith("| `")]
        assert len(rows) == 1, section
        cells = [x.strip() for x in rows[0].strip("|").split("|")]
        assert cells[:6] == ["`WidgetService`", "conflict", "DEMO-902", "Service Ops", "in-flight",
                             "modify"], cells
    finally:
        cleanup(root, scan)


def test_invalid_register_file_listed():
    root = make_root()
    scan, c, m = inputs(root)
    write(os.path.join(root, "impacts", "DEMO-903-broken", "impact.json"), "{not json")
    try:
        code, out = run(root, "--classified", c, "--meta", m)
        assert code == 0, out
        md = read(os.path.join(out_dir(root), "impact.md"))
        assert "### Register files that failed validation" in md, md
        assert "impacts/DEMO-903-broken/impact.json" in md, md
    finally:
        cleanup(root, scan)


def test_no_register_says_none():
    root = make_root(register=False)
    scan, c, m = inputs(root)
    try:
        code, out = run(root, "--classified", c, "--meta", m)
        assert code == 0, out
        md = read(os.path.join(out_dir(root), "impact.md"))
        assert "- none in the register at" in md, md
    finally:
        cleanup(root, scan)


def test_md_cells_escape_backslash_before_pipe():
    root = make_root()
    rows = [{"api": "WidgetService", "layer": "Ap\\|ex", "type": "ApexClass", "ownership": "Custom\\",
             "changeType": "modify", "impact": "High", "scale": "S", "hop": "0",
             "evidence": CLS + ":2", "confidence": "Confirmed", "note": "entry point"}]
    scan, c, m = inputs(root, rows=rows)
    try:
        code, out = run(root, "--classified", c, "--meta", m)
        assert code == 0, out
        md = read(os.path.join(out_dir(root), "impact.md"))
        row = [l for l in md.splitlines() if l.startswith("| `WidgetService` | Ap")][0]
        assert "| Ap\\\\\\|ex | ApexClass | Custom\\\\ |" in row, row
        plain = row.replace("\\\\", "").replace("\\|", "")
        assert len(plain.strip("|").split("|")) == 10, row
    finally:
        cleanup(root, scan)


def test_bad_evidence_writes_nothing():
    root = make_root()
    rows = [{"api": "WidgetService", "type": "ApexClass", "changeType": "modify", "impact": "High",
             "hop": 0, "evidence": "x.cls:999", "confidence": "Confirmed"}]
    scan, c, m = inputs(root, rows=rows)
    try:
        code, out = run(root, "--classified", c, "--meta", m)
        assert code == 1, out
        assert "x.cls:999" in out, out
        assert not os.path.exists(os.path.join(root, "ai-context")), "files were created"
    finally:
        cleanup(root, scan)


def test_missing_meta_is_usage_error():
    root = make_root()
    scan, c, m = inputs(root)
    try:
        code, out = run(root, "--classified", c)
        assert code == 2, out
        assert not os.path.exists(os.path.join(root, "ai-context")), "files were created"
    finally:
        cleanup(root, scan)


def _meta(**extra):
    meta = {"squad": "Customer Care", "hops": 2, "model": "test-model", "assistantVersion": "unknown",
            "decisions": [], "unknowns": []}
    meta.update(extra)
    return meta


def test_write_report_passes_design_option():
    root = make_root()
    scan, c, m = inputs(root, meta=_meta(designOption="OPT-2", recommendedBy="assistant"))
    try:
        code, out = run(root, "--classified", c, "--meta", m)
        assert code == 0, out
        doc = json.loads(read(os.path.join(out_dir(root), "impact.json")))
        assert doc["designOption"] == "OPT-2", doc
        assert doc["provenance"]["recommendedBy"] == "assistant", doc["provenance"]
        assert "chosenOption" not in doc, doc
        assert validate(doc, "draft", root, check_evidence=True) == []
        md = read(os.path.join(out_dir(root), "impact.md"))
        head = md.split("| Impact | Count |", 1)[0]
        assert "Assessed option: OPT-2 from design.json (recommended by: assistant)." in head, head
        for word in ("we recommend", "should", "approve", "block"):
            assert word not in md.lower(), (word, md)
    finally:
        cleanup(root, scan)
    # Re-assessed for an owner-named option: designOption without recommendedBy.
    root = make_root()
    scan, c, m = inputs(root, meta=_meta(designOption="OPT-3"))
    try:
        code, out = run(root, "--classified", c, "--meta", m)
        assert code == 0, out
        doc = json.loads(read(os.path.join(out_dir(root), "impact.json")))
        assert doc["designOption"] == "OPT-3" and "recommendedBy" not in doc["provenance"], doc
        md = read(os.path.join(out_dir(root), "impact.md"))
        assert "Assessed option: OPT-3 from design.json." in md, md
    finally:
        cleanup(root, scan)
    # Bad values are refused and nothing is written.
    for extra in ({"designOption": "two"}, {"designOption": "OPT-2", "recommendedBy": "owner"},
                  {"recommendedBy": "assistant"}):
        root = make_root()
        scan, c, m = inputs(root, meta=_meta(**extra))
        try:
            code, out = run(root, "--classified", c, "--meta", m)
            assert code == 1, (extra, out)
            assert not os.path.exists(os.path.join(root, "ai-context")), extra
        finally:
            cleanup(root, scan)


def test_no_design_meta_writes_no_design_fields():
    root = make_root()
    scan, c, m = inputs(root, meta=_meta())
    try:
        code, out = run(root, "--classified", c, "--meta", m)
        assert code == 0, out
        doc = json.loads(read(os.path.join(out_dir(root), "impact.json")))
        assert "designOption" not in doc and "recommendedBy" not in doc["provenance"], doc
        assert "Assessed option" not in read(os.path.join(out_dir(root), "impact.md"))
    finally:
        cleanup(root, scan)


def test_rendered_copies_find_repo_root():
    for path in RENDERED:
        here = os.path.dirname(path)
        repo = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(here))))
        assert os.path.samefile(repo, REPO), path
    root = make_root()
    scan, c, m = inputs(root)
    try:
        for path in RENDERED:
            code, out = run(root, "--classified", c, "--meta", m, script=path)
            assert code == 0, (path, out)
    finally:
        cleanup(root, scan)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    return run_tests([(t.__name__, t) for t in tests], show_pass=True)


if __name__ == "__main__":
    sys.exit(main())

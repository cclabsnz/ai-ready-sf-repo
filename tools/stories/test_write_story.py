#!/usr/bin/env python3
"""Tests for story-refine's write_story.py. Plain script: python3 tools/stories/test_write_story.py

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
sys.path.insert(0, os.path.join(REPO, "tools", "impacts"))

from _testutil import run_tests, symlink  # noqa: E402
from validate_story import validate_story  # noqa: E402
from check_ac import check_ac, load_vague  # noqa: E402

SCRIPT = os.path.join(REPO, "framework", "skills", "story-refine", "scripts", "write_story.py")
RENDERED = [os.path.join(REPO, d, "skills", "story-refine", "scripts", "write_story.py")
            for d in (".claude", ".github")]
FIELD = "force-app/main/default/objects/Widget__c/fields/Size__c.field-meta.xml"
STORY, SLUG = "DEMO-911", "widget-size-refined"
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
    return {"schemaVersion": 1, "storyId": "DEMO-912", "slug": "widget-resize", "squad": "Service Ops",
            "status": "in-flight", "confirmedBy": "Tech Lead",
            "provenance": {"indexStamp": {"commit": "abc1234"}, "frameworkVersion": "0.1.0",
                           "model": "m", "assistantVersion": "unknown", "hops": 1},
            "components": [{"api": "Widget__c.Size__c", "type": "CustomField", "changeType": "modify",
                            "impact": "High", "confidence": "Confirmed", "hop": 0,
                            "evidence": FIELD + ":2", "path": FIELD}],
            "decisions": [], "unknowns": []}


def make_root(register=True):
    os.makedirs(CTX, exist_ok=True)
    root = tempfile.mkdtemp(prefix="write_story_", dir=CTX)
    write(os.path.join(root, FIELD), "<CustomField>\n    <fullName>Size__c</fullName>\n"
                                     "    <required>false</required>\n</CustomField>\n")
    write(os.path.join(root, "index", "metadata.json"), json.dumps(
        {"stamp": {"commit": "feedc0de", "indexVersion": 1, "builtAt": "synthetic"},
         "nodes": {"Widget__c.Size__c": {"type": "CustomField", "path": FIELD}}, "edges": []}))
    write(os.path.join(root, "impacts", "squads.json"),
          json.dumps({"version": 1, "squads": ["Customer Care", "Service Ops"]}))
    if register:
        write(os.path.join(root, "impacts", "DEMO-912-widget-resize", "impact.json"),
              json.dumps(other_record()))
    return root


def good_draft():
    return {
        "storyId": STORY, "slug": SLUG, "squad": "Customer Care",
        "persona": "a service agent", "goal": "record a widget size on each widget",
        "benefit": "agents pick the right replacement part",
        "inScope": ["Widget size field"], "outOfScope": ["Widget pricing"], "nonFunctional": [],
        "openQuestions": [{"id": "OQ-1", "text": "Which sizes are retired?", "ownerRole": "Product Owner",
                           "answer": None, "deferred": False}],
        "acceptanceCriteria": [
            {"id": "AC-1", "given": "a widget with no size", "when": "the agent saves it",
             "then": "the widget saves with a blank size", "examples": ["Widget W-1 saves"],
             "source": "edge-case"}],
        "edgeCases": [
            {"id": "EC-1", "category": "blank", "component": "Widget__c.Size__c",
             "detail": "field is not required; value left blank",
             "evidence": FIELD + ":3", "confidence": "Confirmed", "becameCriterion": "AC-1",
             "reason": None},
            {"id": "EC-2", "category": "bulk", "component": "Widget__c",
             "detail": "a bulk change of 200 records or more", "evidence": None,
             "confidence": "Unverifiable", "becameCriterion": None,
             "reason": "bulk loads are out of scope"}],
        "droppedSeeds": [{"category": "field-access", "component": "Widget__c.Size__c",
                          "detail": "Widget_Editor edit", "reason": "no such permission set in use"}],
        "seeds": ["Widget__c.Size__c", "Widget__c"],
    }


def draft_file(doc):
    d = tempfile.mkdtemp(prefix="write_story_in_")
    path = os.path.join(d, "draft.json")
    write(path, json.dumps(doc))
    return d, path


def run(root, draft_path, cwd=None, story=STORY, slug=SLUG, script=SCRIPT):
    args = [sys.executable, script, "--id", story, "--slug", slug, "--draft", draft_path, "--root", root]
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


def test_writes_valid_story():
    root = make_root()
    tmp, d = draft_file(good_draft())
    try:
        code, out = run(root, d)
        assert code == 0, out
        printed = json.loads(out)
        assert printed["storyJson"].endswith("story.json") and printed["storyMd"].endswith("story.md"), printed
        doc = json.loads(read(os.path.join(out_dir(root), "story.json")))
        assert validate_story(doc, "draft", root, check_evidence=True) == [], doc
        assert check_ac(doc, load_vague()) == []
        assert doc["status"] == "draft" and doc["schemaVersion"] == 1, doc
        assert "confirmedBy" not in doc, doc
        md = read(os.path.join(out_dir(root), "story.md"))
        for heading in ("## Acceptance criteria", "## Edge cases", "## Dropped seeds",
                        "## Overlaps with other stories", "## Open questions", "## Scope"):
            assert heading in md, heading
        assert "| AC | Given | When | Then | Examples | Source |" in md, md
        assert "| EC | Category | Component | Detail | Evidence | Confidence | Criterion |" in md, md
        assert ("| EC-2 | bulk | `Widget__c` | a bulk change of 200 records or more | none | Unverifiable "
                "| none: bulk loads are out of scope |") in md, md
        assert "| Category | Component | Detail | Reason |" in md, md
        assert ("| field-access | `Widget__c.Size__c` | Widget_Editor edit | no such permission set in use |"
                in md), md
        assert "(Product Owner)" in md or "| Product Owner |" in md, md
        for word in ("should", "we recommend", "approve", "block"):
            fixed = md.replace("Which sizes are retired?", "")
            assert word not in fixed.lower(), word
        first = read(os.path.join(out_dir(root), "story.json")), md
        code, out = run(root, d)
        assert code == 0, out
        again = read(os.path.join(out_dir(root), "story.json")), read(os.path.join(out_dir(root), "story.md"))
        assert first == again, "output differs between runs"
        assert "\r" not in md
    finally:
        cleanup(root, tmp)


def test_vague_criterion_writes_nothing():
    root = make_root()
    doc = good_draft()
    doc["acceptanceCriteria"][0]["then"] = "the widget saves quickly"
    tmp, d = draft_file(doc)
    try:
        code, out = run(root, d)
        assert code == 1, out
        assert "vague-word" in out and "quickly" in out, out
        assert not os.path.exists(os.path.join(root, "ai-context")), "files were created"
    finally:
        cleanup(root, tmp)


def test_invalid_draft_writes_nothing():
    root = make_root()
    doc = good_draft()
    doc["edgeCases"][0]["evidence"] = FIELD + ":999"
    tmp, d = draft_file(doc)
    try:
        code, out = run(root, d)
        assert code == 1, out
        assert ":999" in out, out
        assert not os.path.exists(os.path.join(root, "ai-context")), "files were created"
    finally:
        cleanup(root, tmp)


def test_draft_cannot_carry_writer_keys():
    root = make_root()
    try:
        for key, val in (("confirmedBy", "Product Owner"), ("status", "confirmed"),
                         ("schemaVersion", 1), ("overlaps", [])):
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


def test_overlap_from_seeds_is_watch():
    root = make_root()
    tmp, d = draft_file(good_draft())
    try:
        code, out = run(root, d)
        assert code == 0, out
        assert json.loads(out)["overlaps"] == 1, out
        doc = json.loads(read(os.path.join(out_dir(root), "story.json")))
        assert len(doc["overlaps"]) == 1, doc["overlaps"]
        ov = doc["overlaps"][0]
        assert ov["api"] == "Widget__c.Size__c" and ov["kind"] == "watch", ov
        assert ov["type"] == "CustomField", ov
        assert ov["stories"][0]["storyId"] == "DEMO-912" and ov["stories"][0]["changeType"] == "modify", ov
        md = read(os.path.join(out_dir(root), "story.md"))
        section = md.split("## Overlaps with other stories", 1)[1].split("\n## ", 1)[0]
        rows = [l for l in section.splitlines() if l.startswith("| `")]
        assert len(rows) == 1, section
        cells = [x.strip() for x in rows[0].strip("|").split("|")]
        assert cells[:6] == ["`Widget__c.Size__c`", "watch", "DEMO-912", "Service Ops", "in-flight",
                             "modify"], cells
    finally:
        cleanup(root, tmp)


def test_no_register_and_invalid_register_listed():
    root = make_root(register=False)
    tmp, d = draft_file(good_draft())
    try:
        code, out = run(root, d)
        assert code == 0, out
        md = read(os.path.join(out_dir(root), "story.md"))
        assert "- none in the register at" in md, md
        doc = json.loads(read(os.path.join(out_dir(root), "story.json")))
        assert doc["overlaps"] == [], doc["overlaps"]
        write(os.path.join(root, "impacts", "DEMO-913-broken", "impact.json"), "{not json")
        code, out = run(root, d)
        assert code == 0, out
        md = read(os.path.join(out_dir(root), "story.md"))
        assert "### Register files that failed validation" in md, md
        assert "impacts/DEMO-913-broken/impact.json" in md, md
    finally:
        cleanup(root, tmp)


def test_unknown_seed_type():
    root = make_root()
    os.remove(os.path.join(root, "index", "metadata.json"))
    write(os.path.join(root, "impacts", "DEMO-912-widget-resize", "impact.json"),
          json.dumps(other_record()))
    tmp, d = draft_file(good_draft())
    try:
        code, out = run(root, d)
        assert code == 0, out
        doc = json.loads(read(os.path.join(out_dir(root), "story.json")))
        assert doc["overlaps"][0]["type"] == "Unknown", doc["overlaps"]
    finally:
        cleanup(root, tmp)


def test_root_never_supplies_code():
    root = make_root()
    tmp, d = draft_file(good_draft())
    for rel in ("tools/impacts/register.py", "tools/impacts/validate.py", "tools/impacts/safe_write.py",
                "tools/stories/validate_story.py", "tools/stories/check_ac.py", "tools/index/query.py"):
        write(os.path.join(root, rel), PLANT)
    try:
        code, out = run(root, d, cwd=root)
        assert code == 0, out
        assert not os.path.exists(os.path.join(root, "PLANTED_MARKER")), "root code ran"
        assert os.path.exists(os.path.join(out_dir(root), "story.json")), out
    finally:
        cleanup(root, tmp)


def test_symlinked_output_refused():
    for name in ("story.json", "story.md"):
        root = make_root()
        outside = tempfile.mkdtemp(prefix="write_story_outside_")
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
    outside = tempfile.mkdtemp(prefix="write_story_outside_")
    tmp, d = draft_file(good_draft())
    try:
        code, out = run(root, d, slug="../../escape")
        assert code == 2 and "--slug '../../escape' does not match" in out, out
        symlink(outside, os.path.join(root, "ai-context"))
        code, out = run(root, d)
        assert code == 2 and "resolves outside <root>/ai-context/" in out, out
        assert os.listdir(outside) == [], os.listdir(outside)
        os.remove(os.path.join(root, "ai-context"))
        os.makedirs(os.path.join(root, "ai-context"))
        symlink(outside, out_dir(root))
        code, out = run(root, d)
        assert code == 2 and "resolves outside <root>/ai-context/" in out, out
        assert os.listdir(outside) == [], os.listdir(outside)
    finally:
        cleanup(root, outside, tmp)


def test_root_outside_checkout_refused():
    root = tempfile.mkdtemp(prefix="write_story_elsewhere_")
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
    doc["acceptanceCriteria"][0]["given"] = 'a widget with size "A|B"'
    doc["openQuestions"][0]["text"] = "Is size X|Y retired?"
    doc["edgeCases"][1]["detail"] = "bulk P|Q"
    tmp, d = draft_file(doc)
    try:
        code, out = run(root, d)
        assert code == 0, out
        md = read(os.path.join(out_dir(root), "story.md"))
        row = [l for l in md.splitlines() if l.startswith("| AC-1 |")][0]
        assert 'A\\|B' in row, row
        cells = row.replace("\\|", "").strip("|").split("|")
        assert len(cells) == 6, row
        oq = [l for l in md.splitlines() if l.startswith("| OQ-1 |")][0]
        assert "X\\|Y" in oq, oq
        ec = [l for l in md.splitlines() if l.startswith("| EC-2 |")][0]
        assert "P\\|Q" in ec and len(ec.replace("\\|", "").strip("|").split("|")) == 7, ec
    finally:
        cleanup(root, tmp)


def md_cells(row):
    """Split a markdown table row on unescaped pipes; a backslash escapes the next character."""
    cells, cur, i = [], "", 0
    while i < len(row):
        ch = row[i]
        if ch == "\\" and i + 1 < len(row):
            cur += row[i:i + 2]
            i += 2
            continue
        if ch == "|":
            cells.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    cells.append(cur)
    return [c.strip() for c in cells[1:-1]]


def test_md_cells_escape_backslash_before_pipe():
    root = make_root()
    doc = good_draft()
    doc["edgeCases"][1]["detail"] = "a\\|b"  # text a\|b: an escape a reader would otherwise eat
    doc["droppedSeeds"][0]["reason"] = "ends in a backslash \\"
    tmp, d = draft_file(doc)
    try:
        code, out = run(root, d)
        assert code == 0, out
        md = read(os.path.join(out_dir(root), "story.md"))
        ec = [l for l in md.splitlines() if l.startswith("| EC-2 |")][0]
        assert "a\\\\\\|b" in ec, ec
        assert len(md_cells(ec)) == 7, md_cells(ec)
        ds = [l for l in md.splitlines() if l.startswith("| field-access |")][0]
        assert ds.endswith("backslash \\\\ |"), ds
        assert len(md_cells(ds)) == 4, md_cells(ds)
    finally:
        cleanup(root, tmp)


def test_missing_detail_writes_nothing():
    root = make_root()
    try:
        for key in ("edgeCases", "droppedSeeds"):
            doc = good_draft()
            del doc[key][0]["detail"]
            tmp, d = draft_file(doc)
            try:
                code, out = run(root, d)
                assert code == 1 and "missing key 'detail'" in out, (key, out)
                assert not os.path.exists(os.path.join(root, "ai-context")), key
            finally:
                cleanup(tmp)
    finally:
        cleanup(root)


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
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    return run_tests([(t.__name__, t) for t in tests], show_pass=True)


if __name__ == "__main__":
    sys.exit(main())

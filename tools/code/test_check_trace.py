#!/usr/bin/env python3
"""Tests for check_trace.py: CLI plumbing only, against a stub core written into a temp dir.

check_trace.py has no flag or env var that selects a core, so the stub is injected in-process through
main(argv, core_path=...). A few cases run the real script as a subprocess.

The matching logic belongs to the guard-owned tools/guard/trace_core.py and is unit-tested with the guard.
One case runs the real core and prints SKIP while that file is absent.

Run: python3 tools/code/test_check_trace.py
"""
import atexit
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import traceback

sys.dont_write_bytecode = True  # importing check_trace and the stub leaves no __pycache__
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
CHECK = os.path.join(HERE, "check_trace.py")
REAL_CORE = os.path.join(REPO, "tools", "guard", "trace_core.py")

class Skip(Exception):
    """The case cannot run here; counted apart from passes and failures."""


TMP = tempfile.mkdtemp(prefix="check_trace_")
atexit.register(shutil.rmtree, TMP, True)

# A deliberately simple stand-in with the real core's interface. Plain substring tokens are enough
# to exercise the CLI's argument handling, file selection, exit codes and JSON.
STUB = '''
import os
import re
MAX_READ = 1000
REF = re.compile(r"\\b(?:AC|EC)-[0-9]+\\b")

def read_tests(root, paths):
    out = {}
    for p in paths:
        full = os.path.join(root, p)
        if os.path.isfile(full):
            with open(full, encoding="utf-8", errors="replace") as fh:
                out[p] = fh.read(MAX_READ)
    return out

def source_test_paths(paths):
    return [p for p in paths if not p.endswith("-meta.xml")]

def criteria_problem(criteria):
    if not criteria:
        return "STUB empty criteria"
    ids = [c["id"] for c in criteria]
    if any(not re.fullmatch(r"(?:AC|EC)-[0-9]+", i) for i in ids):
        return "STUB bad id"
    if len(set(ids)) != len(ids):
        return "STUB duplicate id"
    return None

def _refs(texts):
    return {m for t in texts.values() for m in REF.findall(t)}

def missing_criteria(ids, texts):
    found = _refs(texts)
    return [i for i in ids if i not in found]

def unknown_refs(ids, texts):
    return sorted(_refs(texts) - set(ids))
'''

STORY = "ZED-7"
FOLDER = "ZED-7-sample-change"
TEST_A = "force-app/main/default/classes/ZedThing_Test.cls"
TEST_B = "force-app/main/default/classes/ZedOther_Test.cls"


def stub_core():
    path = os.path.join(TMP, "stub_trace_core.py")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(STUB)
    return path


def make_root(files=None, pkg=None, folder=FOLDER):
    root = tempfile.mkdtemp(prefix="root_", dir=TMP)
    if pkg is None:
        pkg = {"schemaVersion": 1, "storyId": STORY, "slug": "sample-change",
               "criteria": [{"id": "AC-1"}, {"id": "AC-2"}],
               "scope": {"modify": [], "create": [], "tests": [TEST_A, TEST_B]}}
    if pkg is not False:
        write(root, "impacts/%s/build-package.json" % folder, pkg if isinstance(pkg, str) else json.dumps(pkg))
    for rel, text in (files or {}).items():
        write(root, rel, text)
    return root


def write(root, rel, text):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def load_check():
    spec = importlib.util.spec_from_file_location("check_trace_under_test", CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CHECK_MOD = load_check()


def run(args, core="stub"):
    """check_trace.main in-process. The stub core is injected through main's core_path keyword, which no
    command line can reach; core=None uses the script's own default (tools/guard/trace_core.py)."""
    core_path = stub_core() if core == "stub" else core
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = CHECK_MOD.main(args, core_path=core_path)
        except SystemExit as exc:  # argparse usage errors
            code = exc.code
        except Exception:
            err.write("Traceback\n" + traceback.format_exc())
            code = None
    return code, out.getvalue(), err.getvalue()


def run_script(args):
    """The real command line, as a subprocess: what a user or the guard sees."""
    p = subprocess.run([sys.executable, CHECK] + args, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def run_json(args, core="stub"):
    code, out, err = run(args, core)
    assert "Traceback" not in err, err
    return code, json.loads(out)


def case_all_referenced_passes_both_modes():
    root = make_root({TEST_A: "// AC-1\n", TEST_B: "// AC-2\n"})
    for extra in (["--skeletons"], []):
        code, doc = run_json(extra + [STORY, "--root", root])
        assert code == 0 and doc["ok"] is True, doc
        assert doc["missingCriteria"] == [] and doc["storyId"] == STORY, doc


def case_missing_criterion_fails():
    root = make_root({TEST_A: "// AC-1\n"})
    code, doc = run_json(["--skeletons", STORY, "--root", root])
    assert code == 1 and doc["ok"] is False and doc["missingCriteria"] == ["AC-2"], doc
    assert doc["missingTestFiles"] == [TEST_B], doc


def case_id_in_out_of_scope_file_ignored():
    root = make_root({TEST_A: "// AC-1\n", "force-app/main/default/classes/Extra_Test.cls": "// AC-2\n"})
    code, doc = run_json(["--skeletons", STORY, "--root", root])
    assert code == 1 and doc["missingCriteria"] == ["AC-2"], doc


def case_skeletons_vs_full():
    # Unknown refs and a test file with no id pass --skeletons and fail the full check.
    root = make_root({TEST_A: "// AC-1 AC-2 AC-9\n", TEST_B: "// nothing\n"})
    code, doc = run_json(["--skeletons", STORY, "--root", root])
    assert code == 0 and doc["mode"] == "skeletons" and doc["ok"] is True, doc
    code, doc = run_json([STORY, "--root", root])
    assert code == 1 and doc["mode"] == "full" and doc["ok"] is False, doc
    assert doc["unknownRefs"] == ["AC-9"] and doc["testsWithoutRefs"] == [TEST_B], doc


def case_meta_companion_skipped_by_no_refs_rule():
    # A *-meta.xml in scope.tests cannot carry ids: the full check does not list it as a test without refs.
    # A non-meta file with no id still fails, so the skip is by suffix only.
    meta = TEST_A + "-meta.xml"
    pkg = {"schemaVersion": 1, "storyId": STORY, "slug": "sample-change",
           "criteria": [{"id": "AC-1"}, {"id": "AC-2"}],
           "scope": {"modify": [], "create": [], "tests": [TEST_A, meta]}}
    root = make_root({TEST_A: "// AC-1 AC-2\n", meta: "<ApexClass/>\n"}, pkg=pkg)
    for extra in (["--skeletons"], []):
        code, doc = run_json(extra + [STORY, "--root", root])
        assert code == 0 and doc["ok"] is True and doc["testsWithoutRefs"] == [], doc
    pkg["scope"]["tests"] = [TEST_A, meta, TEST_B]
    root = make_root({TEST_A: "// AC-1 AC-2\n", meta: "<ApexClass/>\n", TEST_B: "// none\n"}, pkg=pkg)
    code, doc = run_json([STORY, "--root", root])
    assert code == 1 and doc["testsWithoutRefs"] == [TEST_B], doc


def case_id_only_in_meta_does_not_cover():
    # An id that appears only in a *-meta.xml covers no criterion, in either mode.
    meta = TEST_A + "-meta.xml"
    pkg = {"schemaVersion": 1, "storyId": STORY, "slug": "sample-change",
           "criteria": [{"id": "AC-1"}, {"id": "AC-2"}],
           "scope": {"modify": [], "create": [], "tests": [TEST_A, meta]}}
    root = make_root({TEST_A: "// AC-1\n", meta: "<!-- AC-2 -->\n"}, pkg=pkg)
    for extra in (["--skeletons"], []):
        code, doc = run_json(extra + [STORY, "--root", root])
        assert code == 1 and doc["missingCriteria"] == ["AC-2"], doc


def case_meta_exclusion_comes_from_the_core():
    # check_trace has no exclusion of its own: it asks the core's source_test_paths, the helper the guard's
    # tests-first rule uses. A stub whose helper drops every path leaves every criterion missing, even with the
    # ids in a plain test file; a stub that keeps every path lets an id in a -meta.xml count.
    meta = TEST_A + "-meta.xml"
    pkg = {"schemaVersion": 1, "storyId": STORY, "slug": "sample-change",
           "criteria": [{"id": "AC-1"}, {"id": "AC-2"}],
           "scope": {"modify": [], "create": [], "tests": [TEST_A, meta]}}
    none_core = os.path.join(TMP, "none_paths_core.py")
    write(TMP, "none_paths_core.py", STUB.replace('if not p.endswith("-meta.xml")', "if False"))
    root = make_root({TEST_A: "// AC-1 AC-2\n", meta: "<x/>\n"}, pkg=pkg)
    code, doc = run_json(["--skeletons", STORY, "--root", root], core=none_core)
    assert code == 1 and doc["missingCriteria"] == ["AC-1", "AC-2"], doc
    assert doc["missingTestFiles"] == [], doc  # the files still exist; only coverage changed
    all_core = os.path.join(TMP, "all_paths_core.py")
    write(TMP, "all_paths_core.py", STUB.replace('if not p.endswith("-meta.xml")', ""))
    root = make_root({TEST_A: "// AC-1\n", meta: "<!-- AC-2 -->\n"}, pkg=pkg)
    code, doc = run_json(["--skeletons", STORY, "--root", root], core=all_core)
    assert code == 0 and doc["missingCriteria"] == [], doc


def case_core_without_source_test_paths_exits_2():
    old = os.path.join(TMP, "no_helper_core.py")
    write(TMP, "no_helper_core.py", STUB.replace("def source_test_paths(", "def _unused_paths("))
    root = make_root({TEST_A: "// AC-1\n", TEST_B: "// AC-2\n"})
    code, out, err = run([STORY, "--root", root], core=old)
    assert code == 2 and "source_test_paths" in err and "Traceback" not in err, (code, err)


def case_core_loaded_without_bytecode():
    # The core is compiled from source, as the guard does: loading it writes no __pycache__ beside it,
    # even with bytecode writing switched on.
    folder = tempfile.mkdtemp(prefix="corebc_", dir=TMP)
    core = os.path.join(folder, "trace_core.py")
    write(folder, "trace_core.py", STUB)
    root = make_root({TEST_A: "// AC-1\n", TEST_B: "// AC-2\n"})
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = False
    try:
        code, doc = run_json([STORY, "--root", root], core=core)
    finally:
        sys.dont_write_bytecode = old
    assert code == 0, doc
    assert sorted(os.listdir(folder)) == ["trace_core.py"], os.listdir(folder)


def case_unknown_ref_fails():
    root = make_root({TEST_A: "// AC-1\n", TEST_B: "// AC-2 EC-4\n"})
    code, doc = run_json([STORY, "--root", root])
    assert code == 1 and doc["unknownRefs"] == ["EC-4"] and doc["testsWithoutRefs"] == [], doc


def case_json_shape_and_determinism():
    root = make_root({TEST_A: "// AC-1\n", TEST_B: "// AC-2\n"})
    code1, out1, _ = run([STORY, "--root", root])
    code2, out2, _ = run([STORY, "--root", root])
    assert code1 == code2 == 0 and out1 == out2, (out1, out2)
    doc = json.loads(out1)
    assert sorted(doc) == ["criteria", "missingCriteria", "missingTestFiles", "mode", "ok", "package",
                           "storyId", "tests", "testsWithoutRefs", "unknownRefs"], sorted(doc)
    assert doc["package"] == "impacts/%s/build-package.json" % FOLDER, doc
    assert doc["tests"] == [{"exists": True, "path": TEST_A, "refs": ["AC-1"]},
                            {"exists": True, "path": TEST_B, "refs": ["AC-2"]}], doc["tests"]


def case_missing_core_exits_2():
    root = make_root({TEST_A: "// AC-1\n", TEST_B: "// AC-2\n"})
    code, out, err = run([STORY, "--root", root], core=os.path.join(TMP, "no_core.py"))
    assert code == 2 and "missing from tools/guard/, and the guard owner must restore it" in err, (code, out, err)
    assert "Traceback" not in err, err
    # The real script with its own default core, while tools/guard/trace_core.py is absent.
    if not os.path.isfile(REAL_CORE):
        code, out, err = run_script([STORY, "--root", root])
        assert code == 2 and "missing from tools/guard/, and the guard owner must restore it" in err, (code, out, err)
        assert REAL_CORE in err and out == "", (out, err)


def case_core_flag_rejected():
    # No command line may select the core: --core (and any spelling of it) is an unknown argument.
    root = make_root({TEST_A: "// AC-1\n", TEST_B: "// AC-2\n"})
    for extra in (["--core", stub_core()], ["--core=" + stub_core()], ["--co", stub_core()]):
        code, out, err = run_script([STORY, "--root", root] + extra)
        assert code == 2 and "unrecognized arguments" in err and out == "", (extra, code, out, err)
        assert "Traceback" not in err, err
    code, out, err = run_script(["--help"])
    assert code == 0 and "--core" not in out and "--root" in out, out


def case_broken_core_exits_2():
    bad = os.path.join(TMP, "bad_core.py")
    write(TMP, "bad_core.py", "def missing_criteria(ids, texts):\n    return []\n")
    root = make_root({TEST_A: "// AC-1\n"})
    code, out, err = run([STORY, "--root", root], core=bad)
    assert code == 2 and "Traceback" not in err and "unknown_refs" in err, (code, err)


def case_bad_story_id_exits_2():
    root = make_root()
    for sid in ["zed-7", "ZED-7-sample-change", "../ZED-7", "ZED"]:
        code, out, err = run([sid, "--root", root])
        assert code == 2 and "Traceback" not in err and "storyId" in err, (sid, code, err)


def case_usage_errors_exit_2():
    code, out, err = run([])
    assert code == 2, (code, err)
    code, out, err = run([STORY, "--root", os.path.join(TMP, "no-such-root")])
    assert code == 2 and "Traceback" not in err, (code, err)


def case_no_package_exits_2():
    root = make_root(pkg=False)
    code, out, err = run([STORY, "--root", root])
    assert code == 2 and "no impacts/ZED-7-*/build-package.json" in err, (code, err)


def case_two_matching_folders_exit_2():
    root = make_root()
    write(root, "impacts/ZED-7-other-change/build-package.json", "{}")
    code, out, err = run([STORY, "--root", root])
    assert code == 2 and "more than one" in err, (code, err)
    # ZED-70-* is a different story
    root = make_root({TEST_A: "AC-1\n", TEST_B: "AC-2\n"})
    write(root, "impacts/ZED-70-sample-change/build-package.json", "{}")
    code, out, err = run([STORY, "--root", root])
    assert code == 0, (code, out, err)


def case_malformed_package_exits_2():
    for pkg, needle in [("{nope", "not valid JSON"), ("[1]", "not a JSON object"),
                        (json.dumps({"criteria": [{"id": "AC-1"}]}), "scope.tests"),
                        (json.dumps({"criteria": "AC-1", "scope": {"tests": []}}), "criteria"),
                        (json.dumps({"criteria": [{"id": 3}], "scope": {"tests": []}}), "criteria"),
                        (json.dumps({"criteria": [{"id": "AC-1"}], "scope": {"tests": "x"}}), "scope.tests")]:
        root = make_root(pkg=pkg)
        code, out, err = run([STORY, "--root", root])
        assert code == 2 and "Traceback" not in err and needle in err, (pkg, code, err)


def case_invalid_criteria_exit_1():
    # The verdict and message come from the core's criteria_problem (the stub's "STUB ..." text proves it).
    for criteria, needle in [([], "STUB empty criteria"), ([{"id": "OQ-1"}], "STUB bad id"),
                             ([{"id": "AC-1"}, {"id": "AC-1"}], "STUB duplicate id")]:
        root = make_root({TEST_A: "// AC-1\n"}, pkg={"criteria": criteria, "scope": {"tests": [TEST_A]}})
        for extra in (["--skeletons"], []):
            code, out, err = run(extra + [STORY, "--root", root])
            assert code == 1 and out == "" and "invalid package" in err and needle in err, (criteria, code, out, err)
            assert "Traceback" not in err, err


def case_core_without_criteria_problem_exits_2():
    old = os.path.join(TMP, "old_core.py")
    write(TMP, "old_core.py", STUB.replace("def criteria_problem(", "def _unused("))
    root = make_root({TEST_A: "// AC-1\n", TEST_B: "// AC-2\n"})
    code, out, err = run([STORY, "--root", root], core=old)
    assert code == 2 and "criteria_problem" in err and "Traceback" not in err, (code, err)


def case_escaping_test_path_exits_2():
    for bad in ["../outside_Test.cls", "/etc/hosts", "force-app\\x_Test.cls", ""]:
        pkg = {"criteria": [{"id": "AC-1"}], "scope": {"tests": [bad]}}
        root = make_root(pkg=pkg)
        code, out, err = run([STORY, "--root", root])
        assert code == 2 and "Traceback" not in err and "scope.tests" in err, (bad, code, err)


def case_symlinked_test_escaping_root_exits_2():
    outside = tempfile.mkdtemp(prefix="outside_", dir=TMP)
    write(outside, "x_Test.cls", "// AC-1\n")
    root = make_root(pkg={"criteria": [{"id": "AC-1"}], "scope": {"tests": ["link/x_Test.cls"]}})
    os.symlink(outside, os.path.join(root, "link"))
    code, out, err = run([STORY, "--root", root])
    assert code == 2 and "outside" in err, (code, err)


def case_real_core_when_present():
    if not os.path.isfile(REAL_CORE):
        raise Skip("tools/guard/trace_core.py is absent")
    # The AC-1 / AC-10 boundary, both ways. AC-1 is referenced (AC-10 does not hide it), so --skeletons passes;
    # AC-10 is not in a package holding AC-1 and AC-2, so the full check reports it as an unknown reference.
    root = make_root({TEST_A: "// AC-1 and AC-10\n", TEST_B: "// AC-2\n"})
    code, doc = run_json(["--skeletons", STORY, "--root", root], core=None)
    assert code == 0 and doc["ok"] is True and doc["missingCriteria"] == [], doc
    code, doc = run_json([STORY, "--root", root], core=None)
    assert code == 1 and doc["ok"] is False, doc
    assert doc["missingCriteria"] == [] and doc["unknownRefs"] == ["AC-10"], doc
    # AC-10 alone does not satisfy AC-1.
    root = make_root({TEST_A: "// AC-10\n", TEST_B: "// AC-2\n"})
    code, doc = run_json(["--skeletons", STORY, "--root", root], core=None)
    assert code == 1 and doc["missingCriteria"] == ["AC-1"], doc
    # The real core's meta exclusion: an id only in X_Test.cls-meta.xml covers nothing (the guard's rule too).
    meta = TEST_A + "-meta.xml"
    pkg = {"schemaVersion": 1, "storyId": STORY, "slug": "sample-change",
           "criteria": [{"id": "AC-1"}, {"id": "AC-2"}],
           "scope": {"modify": [], "create": [], "tests": [TEST_A, meta]}}
    root = make_root({TEST_A: "// AC-1\n", meta: "<x>AC-2</x>\n"}, pkg=pkg)
    code, doc = run_json(["--skeletons", STORY, "--root", root], core=None)
    assert code == 1 and doc["missingCriteria"] == ["AC-2"] and doc["missingTestFiles"] == [], doc


def main():
    cases = [(n, f) for n, f in sorted(globals().items()) if n.startswith("case_")]
    failed = skipped = 0
    for name, fn in cases:
        try:
            fn()
            print("[PASS] %s" % name)
        except Skip as exc:
            skipped += 1
            print("SKIP %s: %s" % (name, exc))
        except Exception as exc:
            failed += 1
            print("[FAIL] %s: %s: %s" % (name, type(exc).__name__, str(exc)[:500]))
    print("%d passed, %d failed, %d skipped" % (len(cases) - failed - skipped, failed, skipped))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

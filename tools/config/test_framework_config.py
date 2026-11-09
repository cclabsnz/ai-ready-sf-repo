#!/usr/bin/env python3
"""Tests for framework_config.py and build_index.py --from-config.

Plain script: python3 tools/config/test_framework_config.py
Temp repos go under <checkout>/ai-context/ and are removed afterwards.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
CHECKOUT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(CHECKOUT, "tools", "impacts"))

import framework_config  # noqa: E402
import pr_check  # noqa: E402

CONFIG_SCRIPT = os.path.join(HERE, "framework_config.py")
BUILD = os.path.join(CHECKOUT, "tools", "index", "build_index.py")
PR_CHECK = os.path.join(CHECKOUT, "tools", "impacts", "pr_check.py")
DEFAULT_CHECKS = {"noImpact": "comment", "outOfScope": "comment"}
APEX = "public with sharing class %s {}\n"


def test_inside_never_raises():
    # commonpath raises ValueError on paths from different Windows drives; mixing absolute and relative
    # raises it on every OS, so this exercises the same branch here.
    top = os.path.realpath(CHECKOUT)
    assert framework_config._inside(top, os.path.join(top, "tools")) is True
    assert framework_config._inside(top, "relative") is False
    assert framework_config._inside(top, os.path.dirname(top)) is False


def tmp_repo(config=None):
    base = os.path.join(CHECKOUT, "ai-context")
    os.makedirs(base, exist_ok=True)
    root = tempfile.mkdtemp(dir=base)
    if config is not None:
        write_config(root, config)
    return root


def write_config(root, config):
    with open(os.path.join(root, ".ai-framework.json"), "w", encoding="utf-8", newline="\n") as fh:
        if isinstance(config, str):
            fh.write(config)
        else:
            json.dump(config, fh)


def write_class(src_root, name):
    d = os.path.join(src_root, "force-app", "main", "default", "classes")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name + ".cls"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(APEX % name)


def raises_value_error(fn, *args):
    try:
        fn(*args)
    except ValueError as exc:
        return str(exc)
    raise AssertionError("ValueError expected")


def run(args, cwd=None):
    return subprocess.run([sys.executable] + args, capture_output=True, text=True, cwd=cwd)


def node_names(index_dir):
    with open(os.path.join(index_dir, "metadata.json"), encoding="utf-8") as fh:
        return set(json.load(fh)["nodes"])


def test_defaults_when_absent():
    root = tmp_repo()
    try:
        assert framework_config.load(root) == {"startingPoint": "existing", "sourceRoot": ".",
                                               "impactChecks": DEFAULT_CHECKS}
        assert framework_config.source_root(root) == os.path.realpath(root)
        assert framework_config.impact_checks(root) == DEFAULT_CHECKS
        p = run([CONFIG_SCRIPT, "source-root", "--root", root])
        assert p.returncode == 0 and p.stdout == ".\n", (p.returncode, p.stdout, p.stderr)
        p = run([CONFIG_SCRIPT, "show", "--root", root])
        assert p.returncode == 0, p.stderr
        assert json.loads(p.stdout)["sourceRoot"] == "."
    finally:
        shutil.rmtree(root)


def test_source_root_configured():
    root = tmp_repo({"startingPoint": "existing", "sourceRoot": "src/org"})
    try:
        os.makedirs(os.path.join(root, "src", "org"))
        assert framework_config.source_root(root) == os.path.realpath(os.path.join(root, "src", "org"))
        p = run([CONFIG_SCRIPT, "source-root", "--root", root])
        assert p.returncode == 0 and p.stdout == "src/org\n", (p.returncode, p.stdout, p.stderr)
    finally:
        shutil.rmtree(root)


def test_source_root_must_stay_inside():
    root = tmp_repo()
    outside = tmp_repo()
    try:
        for value in ("..", "../" + os.path.basename(outside), outside, "src/../.."):
            write_config(root, {"sourceRoot": value})
            msg = raises_value_error(framework_config.source_root, root)
            assert "outside the repo" in msg, msg
            p = run([CONFIG_SCRIPT, "source-root", "--root", root])
            assert p.returncode == 2 and p.stdout == "", (value, p.returncode, p.stdout)
            assert "outside the repo" in p.stderr and "Traceback" not in p.stderr, p.stderr
        link = os.path.join(root, "escape")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            link = None
        if link:
            write_config(root, {"sourceRoot": "escape"})
            assert "outside the repo" in raises_value_error(framework_config.source_root, root)
        write_config(root, {"sourceRoot": "missing"})
        assert "not a directory" in raises_value_error(framework_config.source_root, root)
        for bad in ("", 3, None, ["src"]):
            write_config(root, {"sourceRoot": bad})
            assert "sourceRoot" in raises_value_error(framework_config.load, root)
    finally:
        shutil.rmtree(root)
        shutil.rmtree(outside)


def test_unknown_key_rejected():
    root = tmp_repo({"startingPoint": "existing", "sourceRot": "demo/org"})
    try:
        msg = raises_value_error(framework_config.load, root)
        assert "unknown key" in msg and "sourceRot" in msg, msg
        raises_value_error(framework_config.impact_checks, root)
        p = run([CONFIG_SCRIPT, "show", "--root", root])
        assert p.returncode == 2 and "unknown key" in p.stderr, (p.returncode, p.stderr)
        write_config(root, {"startingPoint": "brownfield"})
        assert "startingPoint" in raises_value_error(framework_config.load, root)
        assert framework_config.impact_checks(root) == DEFAULT_CHECKS  # pr_check ignores it
        write_config(root, {"sourceRoot": 3})
        assert "sourceRoot" in raises_value_error(framework_config.load, root)
        assert framework_config.impact_checks(root) == DEFAULT_CHECKS
        write_config(root, {"startingPoint": "greenfield"})
        assert framework_config.load(root)["startingPoint"] == "greenfield"
    finally:
        shutil.rmtree(root)


def test_impact_checks_semantics_unchanged():
    """The cases pr_check.load_settings had before it moved here, through both entry points."""
    root = tmp_repo()
    try:
        for fn in (framework_config.impact_checks, pr_check.load_settings):
            assert fn(root) == DEFAULT_CHECKS
        cases = [
            ({"impactChecks": {"outOfScope": "fail"}}, {"noImpact": "comment", "outOfScope": "fail"}),
            ({"impactChecks": {"noImpact": "fail", "outOfScope": "fail"}},
             {"noImpact": "fail", "outOfScope": "fail"}),
            ({"impactChecks": {"noImpact": "comment"}}, DEFAULT_CHECKS),
            ({"impactChecks": {}}, DEFAULT_CHECKS),
            ({"impactChecks": None}, DEFAULT_CHECKS),
            ({"impactChecks": {"other": "x", "noImpact": "fail"}},
             {"noImpact": "fail", "outOfScope": "comment"}),
            ({"startingPoint": "existing"}, DEFAULT_CHECKS),
        ]
        for config, expected in cases:
            write_config(root, config)
            for fn in (framework_config.impact_checks, pr_check.load_settings):
                assert fn(root) == expected, (config, fn(root))
        bad = [
            ({"impactChecks": {"outOfScope": "maybe"}}, "not one of comment, fail"),
            ({"impactChecks": {"noImpact": True}}, "not one of comment, fail"),
            ({"impactChecks": "fail"}, "impactChecks is not an object"),
            ([], "is not a JSON object"),
            ("{not json", ""),
            ("[" * 200000 + "]" * 200000, "cannot be read"),
        ]
        for config, needle in bad:
            write_config(root, config)
            for fn in (framework_config.impact_checks, pr_check.load_settings):
                msg = raises_value_error(fn, root)
                assert needle in msg, (needle, msg)
        write_config(root, {"impactChecks": {"outOfScope": "x\n`" * 100}})
        msg = raises_value_error(framework_config.impact_checks, root)
        assert "\n" not in msg and len(msg) < 400, msg
    finally:
        shutil.rmtree(root)


def _copy_tools(root):
    for sub, name in (("index", "build_index.py"), ("config", "framework_config.py")):
        d = os.path.join(root, "tools", sub)
        os.makedirs(d, exist_ok=True)
        shutil.copy(os.path.join(CHECKOUT, "tools", sub, name), os.path.join(d, name))
    return os.path.join(root, "tools", "index", "build_index.py")


def test_from_config_builds_configured_root_into_checkout_index():
    root = tmp_repo({"startingPoint": "existing", "sourceRoot": "src"})
    try:
        builder = _copy_tools(root)
        write_class(root, "TopLevelOnly")
        write_class(os.path.join(root, "src"), "SourceRootOnly")
        p = run([builder, "--from-config"], cwd=os.path.join(root, "src"))
        assert p.returncode == 0, (p.returncode, p.stdout, p.stderr)
        names = node_names(os.path.join(root, "index"))
        assert "SourceRootOnly" in names and "TopLevelOnly" not in names, names
        assert not os.path.exists(os.path.join(root, "src", "index"))
        write_config(root, {"sourceRoot": ".."})
        p = run([builder, "--from-config"])
        assert p.returncode == 2 and "outside the repo" in p.stderr, (p.returncode, p.stderr)
        assert "Traceback" not in p.stderr, p.stderr
        write_config(root, {"sourceRoot": "nowhere"})
        p = run([builder, "--from-config"])
        assert p.returncode == 2 and "not a directory" in p.stderr, (p.returncode, p.stderr)
    finally:
        shutil.rmtree(root)


def test_from_config_refuses_root_or_out():
    root = tmp_repo({"sourceRoot": "src"})
    try:
        builder = _copy_tools(root)
        write_class(os.path.join(root, "src"), "SourceRootOnly")
        for extra in (["--root", "."], ["--out", os.path.join(root, "elsewhere")],
                      ["--root", "src", "--out", "index"], ["--ro", "."]):
            p = run([builder, "--from-config"] + extra, cwd=root)
            assert p.returncode == 2, (extra, p.returncode, p.stdout, p.stderr)
            assert "--from-config" in p.stderr and "Traceback" not in p.stderr, p.stderr
        assert not os.path.exists(os.path.join(root, "index"))
        assert not os.path.exists(os.path.join(root, "elsewhere"))
    finally:
        shutil.rmtree(root)


def test_build_index_defaults_unchanged():
    root = tmp_repo({"sourceRoot": "src"})
    try:
        write_class(root, "TopLevelOnly")
        write_class(os.path.join(root, "src"), "SourceRootOnly")
        p = run([BUILD], cwd=root)
        assert p.returncode == 0, (p.returncode, p.stderr)
        names = node_names(os.path.join(root, "index"))
        assert "TopLevelOnly" in names and "SourceRootOnly" not in names, names
        p = run([BUILD, "--root", "src", "--out", "idx2"], cwd=root)
        assert p.returncode == 0, p.stderr
        assert node_names(os.path.join(root, "src", "idx2")) == {"SourceRootOnly"}
    finally:
        shutil.rmtree(root)


def test_pr_check_unknown_config_key_exits_2():
    root = tmp_repo({"startingPoint": "existing", "impactCheck": {"noImpact": "fail"}})
    try:
        os.makedirs(os.path.join(root, "index"))
        with open(os.path.join(root, "index", "metadata.json"), "w", encoding="utf-8",
                  newline="\n") as fh:
            json.dump({"stamp": {"commit": "abc1234"}, "nodes": {}, "edges": []}, fh)
        changed = os.path.join(root, "changed.txt")
        with open(changed, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("README.md\n")
        p = run([PR_CHECK, "--index", os.path.join(root, "index"), "--changed", changed,
                 "--branch", "feature/DEMO-201-x", "--root", root])
        assert p.returncode == 2, (p.returncode, p.stdout, p.stderr)
        assert p.stdout == "", p.stdout
        assert "unknown key" in p.stderr and "impactCheck" in p.stderr, p.stderr
        assert "Traceback" not in p.stderr, p.stderr
    finally:
        shutil.rmtree(root)


def test_repo_config_source_root():
    p = run([CONFIG_SCRIPT, "source-root"])
    assert p.returncode == 0 and p.stdout == "demo/org\n", (p.returncode, p.stdout, p.stderr)
    with open(os.path.join(CHECKOUT, ".ai-framework.json"), "rb") as fh:
        assert fh.read() == b'{"startingPoint": "existing", "sourceRoot": "demo/org"}\n'


def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL %s: %r" % (name, exc))
        else:
            passed += 1
    print("%d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

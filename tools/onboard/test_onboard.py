#!/usr/bin/env python3
"""Tests for onboard.py. Every repo is a temp tree; the checkout is only read.

Run: python3 tools/onboard/test_onboard.py
"""
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
ONBOARD = os.path.join(HERE, "onboard.py")
QUERY = os.path.join(REPO, "tools", "index", "query.py")
RENDER = os.path.join(REPO, "tools", "build", "render.py")
DEMO_ORG = os.path.join(REPO, "demo", "org")
STUBS = os.path.join("framework", "knowledge", "stubs")
ROLE = "Platform lead"
BANNED = ("we recommend", "should", "approve", "block")
BASELINE_EXISTING = ("Rule baseline: `tools/code/baseline.json` holds the check_rules.py findings "
                     "already in the source root; later runs report only new ones")
BASELINE = os.path.join("tools", "code", "baseline.json")
CHECK_RULES = os.path.join(REPO, "tools", "code", "check_rules.py")
BASELINE_GREENFIELD = "no baseline: rules are strict from the first commit"

TMP = tempfile.mkdtemp(prefix="onboard_")
atexit.register(shutil.rmtree, TMP, True)


def new_root(with_org=False):
    root = tempfile.mkdtemp(dir=TMP)
    if with_org:
        shutil.copytree(DEMO_ORG, os.path.join(root, "org"))
    return root


def run(args, root):
    p = subprocess.run([sys.executable, ONBOARD] + args + ["--root", root],
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def existing(root, *extra):
    return run(["--starting-point", "existing", "--source-root", "org", "--owner-role", ROLE]
               + list(extra), root)


def load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def snapshot(base):
    """{relative path: bytes} of every file under base."""
    out = {}
    for dirpath, _, files in os.walk(base):
        for f in files:
            p = os.path.join(dirpath, f)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, base)] = fh.read()
    return out


def split_stub(text):
    assert text.startswith("---\n"), text
    head, body = text[4:].split("\n---\n", 1)
    meta = dict(line.split(": ", 1) for line in head.splitlines())
    return meta, body


def import_onboard():
    sys.path.insert(0, HERE)
    import onboard
    return onboard


def no_banned(text):
    low = text.lower()
    hits = [w for w in BANNED if w in low]
    assert not hits, hits


# ---- cases -------------------------------------------------------------------------------------

def case_existing_prints_inventory_and_stubs():
    root = new_root(with_org=True)
    code, out, err = existing(root)
    assert code == 0, err
    no_banned(out)
    for heading in ("### Apex by API version", "### Apex by sharing", "### Aura vs LWC"):
        assert heading in out, out
    inv = load(os.path.join(root, "index", "inventory.json"))["inventory"]
    for k, v in inv["apexByApiVersion"].items():
        assert "| %s | %s |" % (k, v) in out, (k, v)
    for k, v in inv["apexBySharing"].items():
        assert "| %s | %s |" % (k, v) in out, (k, v)
    assert "| Aura | %s |" % inv["auraVsLwc"]["aura"] in out
    assert "| LWC | %s |" % inv["auraVsLwc"]["lwc"] in out
    assert out.rstrip().endswith(BASELINE_EXISTING), out
    nodes = load(os.path.join(root, "index", "metadata.json"))["nodes"]
    stub_dir = os.path.join(root, STUBS)
    names = sorted(os.listdir(stub_dir))
    assert len(names) == import_onboard().STUB_TOPICS, names
    for name in names:
        with open(os.path.join(stub_dir, name), encoding="utf-8") as fh:
            meta, body = split_stub(fh.read())
        assert meta == {"topic": meta["topic"], "owner": '"%s"' % ROLE, "last_verified": '""',
                        "verified_by": '""'}, meta
        lines = body.splitlines()
        assert lines[0] == "# " + meta["topic"] and lines[1] == "", lines
        assert lines[2] == "Leads to verify:", lines
        leads = lines[3:]
        assert 0 < len(leads) <= 10 and leads == sorted(leads), leads
        for line in leads:
            assert line.startswith("- ") and line[2:] in nodes, line
        assert "`%s/%s`" % (STUBS.replace(os.sep, "/"), name) in out, name
    assert not os.path.exists(os.path.join(root, ".ai-framework.json"))


def case_stubs_not_rendered():
    root = new_root(with_org=True)
    shutil.copytree(os.path.join(REPO, "framework"), os.path.join(root, "framework"),
                    ignore=shutil.ignore_patterns("stubs"))
    os.makedirs(os.path.join(root, "tools", "build"))
    shutil.copy(RENDER, os.path.join(root, "tools", "build", "render.py"))
    code, out, err = existing(root)
    assert code == 0, err
    stub_names = set(os.listdir(os.path.join(root, STUBS)))
    assert stub_names
    p = subprocess.run([sys.executable, os.path.join(root, "tools", "build", "render.py")],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    for top in (".claude", ".github"):
        for dirpath, dirs, files in os.walk(os.path.join(root, top)):
            assert "stubs" not in dirs, dirpath
            for f in files:
                with open(os.path.join(dirpath, f), encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                assert "Leads to verify:" not in text, os.path.join(dirpath, f)
                assert "knowledge/stubs" not in text, os.path.join(dirpath, f)
                if dirpath.endswith("knowledge"):
                    assert f not in stub_names, f


def case_stub_topics_by_inbound_edges():
    ob = import_onboard()
    nodes = {o: {"type": "CustomObject"} for o in ("Alpha", "Beta", "Delta", "Eps", "Omega", "Zeta")}
    nodes["Util"] = {"type": "ApexClass"}
    edges = []
    for i in range(20):  # an Apex class with more inbound edges than any object
        nodes["Caller%02d" % i] = {"type": "ApexClass"}
        edges.append({"from": "Caller%02d" % i, "to": "Util", "kind": "apexClassRef"})
    for i in range(12):  # field-targeted edges lift Zeta to the top
        edges.append({"from": "Caller%02d" % i, "to": "Zeta.Tier__c", "kind": "apexFieldRef"})
    edges.append({"from": "Caller19", "to": "Zeta", "kind": "objectPermission"})
    for obj, n in (("Beta", 3), ("Alpha", 3), ("Delta", 2), ("Omega", 1), ("Eps", 1)):
        for i in range(n):
            edges.append({"from": "Caller%02d" % i, "to": obj, "kind": "apexObjectRef"})
    topics = ob.stub_topics({"nodes": nodes, "edges": edges})
    assert [t for t, _ in topics] == ["Zeta", "Alpha", "Beta", "Delta", "Eps"], topics
    assert ob.STUB_TOPICS == 5
    zeta_leads = topics[0][1]
    assert zeta_leads == ["Caller%02d" % i for i in range(10)], zeta_leads
    assert ob.stub_text("Delta", ROLE, ["Caller00", "Caller01"]) == (
        '---\ntopic: Delta\nowner: "Platform lead"\nlast_verified: ""\nverified_by: ""\n---\n'
        "# Delta\n\nLeads to verify:\n- Caller00\n- Caller01\n")


def case_greenfield_refuses_existing_codebase():
    root = new_root(with_org=True)
    before = snapshot(root)
    code, out, err = run(["--starting-point", "greenfield", "--source-root", "org"], root)
    assert code == 1 and "existing codebase" in err and "Traceback" not in err, err
    assert snapshot(root) == before and not os.path.exists(os.path.join(root, "index"))
    with open(os.path.join(root, ".ai-framework.json"), "w", encoding="utf-8") as fh:
        json.dump({"sourceRoot": "org"}, fh)  # greenfield falls back to the config's root
    before = snapshot(root)
    code, out, err = run(["--starting-point", "greenfield"], root)
    assert code == 1 and "existing codebase" in err, err
    assert snapshot(root) == before
    # A different sfdx-project.json alone is enough.
    proj = new_root()
    os.makedirs(os.path.join(proj, "app"))
    with open(os.path.join(proj, "app", "sfdx-project.json"), "w", encoding="utf-8") as fh:
        fh.write('{"packageDirectories": []}\n')
    code, _, err = run(["--starting-point", "greenfield", "--source-root", "app"], proj)
    assert code == 1 and "sfdx-project.json" in err, err
    assert sorted(os.listdir(proj)) == ["app"]
    # The skeleton plus one class is a codebase; the skeleton alone is not.
    sk = new_root()
    assert run(["--starting-point", "greenfield", "--source-root", "app"], sk)[0] == 0
    cls = os.path.join(sk, "app", "force-app", "main", "default", "classes", "Extra.cls")
    with open(cls, "w", encoding="utf-8") as fh:
        fh.write("public with sharing class Extra {}\n")
    code, _, err = run(["--starting-point", "greenfield", "--source-root", "app"], sk)
    assert code == 1 and "force-app/main/default/classes/Extra.cls" in err, err
    os.remove(cls)
    code, out, _ = run(["--starting-point", "greenfield", "--source-root", "app"], sk)
    assert code == 0 and "Greenfield replaced `index/`" in out, out


def case_stub_owner_quoted_and_lint_reads_it():
    sys.path.insert(0, os.path.join(REPO, "tools", "build"))
    import lint
    import datetime
    for role in (ROLE, 'Lead: x #1 "q" \\b'):
        root = new_root(with_org=True)
        shutil.copytree(os.path.join(REPO, "framework"), os.path.join(root, "framework"),
                        ignore=shutil.ignore_patterns("stubs"))
        os.makedirs(os.path.join(root, "tools", "build"))
        shutil.copy(os.path.join(REPO, "tools", "build", "lint.py"),
                    os.path.join(root, "tools", "build", "lint.py"))
        code, out, err = run(["--starting-point", "existing", "--source-root", "org",
                              "--owner-role", role], root)
        assert code == 0, err
        stub_dir = os.path.join(root, STUBS)
        name = sorted(os.listdir(stub_dir))[0]
        with open(os.path.join(stub_dir, name), encoding="utf-8") as fh:
            text = fh.read()
        meta, _ = split_stub(text)
        assert json.loads(meta["owner"]) == role, meta  # double-quoted YAML, JSON-compatible here
        # A human fills the stub and moves it up a level, where lint applies.
        filled = text.replace('last_verified: ""', "last_verified: %s"
                              % datetime.date.today().isoformat())
        filled = filled.replace('verified_by: ""', "verified_by: xml-parse")
        moved = os.path.join(root, "framework", "knowledge", name)
        with open(moved, "w", encoding="utf-8") as fh:
            fh.write(filled)
        lmeta, _ = lint.fm(moved)
        assert lmeta["owner"], lmeta
        if role == ROLE:
            assert lmeta["owner"] == ROLE, lmeta
        else:
            assert lmeta["owner"].startswith("Lead: x #1"), lmeta
        p = subprocess.run([sys.executable, os.path.join(root, "tools", "build", "lint.py")],
                           capture_output=True, text=True)
        assert p.returncode == 0 and name not in p.stdout + p.stderr, p.stdout + p.stderr


def case_onboard_twice_is_stable():
    root = new_root(with_org=True)
    code1, out1, err1 = existing(root)
    stubs1 = snapshot(os.path.join(root, STUBS))
    code2, out2, err2 = existing(root)
    stubs2 = snapshot(os.path.join(root, STUBS))
    assert code1 == 0 and code2 == 0, err1 + err2
    assert out1 == out2, (out1, out2)
    assert stubs1 == stubs2 and stubs1


def case_edited_stub_kept_unless_replace():
    root = new_root(with_org=True)
    assert existing(root)[0] == 0
    stub_dir = os.path.join(root, STUBS)
    name = sorted(os.listdir(stub_dir))[0]
    path = os.path.join(stub_dir, name)
    with open(path, encoding="utf-8") as fh:
        original = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(original + "- a human note\n")
    code, out, _ = existing(root)
    assert code == 0 and "kept: the file on disk differs" in out, out
    with open(path, encoding="utf-8") as fh:
        assert fh.read().endswith("- a human note\n")
    code, out, _ = existing(root, "--replace")
    assert code == 0 and "(replaced)" in out, out
    with open(path, encoding="utf-8") as fh:
        assert fh.read() == original


def case_existing_writes_rule_baseline():
    root = new_root(with_org=True)
    code, out, err = existing(root)
    assert code == 0, err
    path = os.path.join(root, BASELINE)
    data = load(path)
    assert data["version"] == 1 and data["entries"], data
    assert all(e["path"].startswith("org/force-app/") for e in data["entries"]), data["entries"][:3]
    p = subprocess.run([sys.executable, CHECK_RULES, "--root", root, "--source-root", "org"],
                       capture_output=True, text=True)
    assert p.returncode == 0 and json.loads(p.stdout)["new"] == [], p.stdout[:400] + p.stderr
    # A shrunk baseline survives a re-run unless --replace.
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"version": 1, "entries": data["entries"][1:]}, fh)
    code, out, _ = existing(root)
    assert code == 0 and "kept: the file on disk differs" in out.splitlines()[-1], out
    assert len(load(path)["entries"]) == len(data["entries"]) - 1
    code, out, _ = existing(root, "--replace")
    assert code == 0 and load(path) == data, out


def case_baseline_symlink_refused():
    root = new_root(with_org=True)
    target = tempfile.mkdtemp(dir=TMP)
    os.makedirs(os.path.join(root, "tools"))
    os.symlink(target, os.path.join(root, "tools", "code"))
    code, _, err = existing(root)
    assert code == 2 and "symlink" in err, err
    assert os.listdir(target) == [] and not os.path.exists(os.path.join(root, "index"))
    assert not os.path.exists(os.path.join(root, STUBS))
    file_link = new_root(with_org=True)
    outside = os.path.join(target, "outside.json")
    with open(outside, "w", encoding="utf-8") as fh:
        fh.write("untouched\n")
    os.makedirs(os.path.join(file_link, "tools", "code"))
    os.symlink(outside, os.path.join(file_link, BASELINE))
    code, _, err = existing(file_link)
    assert code == 2 and "symlink" in err, err
    with open(outside, encoding="utf-8") as fh:
        assert fh.read() == "untouched\n"


def case_greenfield_creates_layout():
    ob = import_onboard()
    root = new_root()
    code, out, err = run(["--starting-point", "greenfield", "--source-root", "app"], root)
    assert code == 0, err
    no_banned(out)
    project = load(os.path.join(root, "app", "sfdx-project.json"))
    assert project == {"packageDirectories": [{"path": "force-app", "default": True}],
                       "sourceApiVersion": ob.SOURCE_API_VERSION}, project
    demo = load(os.path.join(DEMO_ORG, "sfdx-project.json"))
    assert ob.SOURCE_API_VERSION == demo["sourceApiVersion"], demo
    for folder in ("classes", "objects", "lwc", "flows", "permissionsets"):
        keep = os.path.join(root, "app", "force-app", "main", "default", folder, ".gitkeep")
        assert os.path.isfile(keep) and os.path.getsize(keep) == 0, keep
        assert "`app/force-app/main/default/%s/.gitkeep`: created" % folder in out, out
    idx = load(os.path.join(root, "index", "metadata.json"))
    assert idx["nodes"] == {} and idx["edges"] == [], idx
    assert out.rstrip().endswith(BASELINE_GREENFIELD), out
    assert not os.path.exists(os.path.join(root, "tools")), os.listdir(root)
    assert not os.path.exists(os.path.join(root, ".ai-framework.json"))
    assert not os.path.exists(os.path.join(root, "framework"))
    before = snapshot(os.path.join(root, "app"))
    code, out, err = run(["--starting-point", "greenfield", "--source-root", "app"], root)
    assert code == 0 and "created" not in out and ": present" in out, out
    assert snapshot(os.path.join(root, "app")) == before


def case_empty_source_root_indexes():
    root = new_root()
    os.makedirs(os.path.join(root, "org"))
    code, out, err = existing(root)
    assert code == 0, err
    assert "Zero objects in the index; no stubs written." in out, out
    index = os.path.join(root, "index")
    for args, check in ((["exists", "X"], lambda d: d["exists"] is False),
                        (["consumers", "X"], lambda d: d["count"] == 0 and d["consumers"] == []),
                        (["edge-seeds", "X"], lambda d: d["seeds"] == [])):
        p = subprocess.run([sys.executable, QUERY] + args + ["--index", index, "--root", root],
                           capture_output=True, text=True)
        assert p.returncode == 0, (args, p.stderr)
        assert check(json.loads(p.stdout)), (args, p.stdout)


def case_write_config_preserves_impact_checks():
    root = new_root()
    cfg = os.path.join(root, ".ai-framework.json")
    with open(cfg, "w", encoding="utf-8") as fh:
        json.dump({"startingPoint": "existing", "sourceRoot": ".",
                   "impactChecks": {"noImpact": "fail"}}, fh)
    code, out, err = run(["--starting-point", "greenfield", "--source-root", "app",
                          "--write-config"], root)
    assert code == 0, err
    assert load(cfg) == {"startingPoint": "greenfield", "sourceRoot": "app",
                         "impactChecks": {"noImpact": "fail"}}, load(cfg)
    fresh = new_root()
    code, out, err = run(["--starting-point", "greenfield", "--source-root", "app",
                          "--write-config"], fresh)
    assert code == 0, err
    assert load(os.path.join(fresh, ".ai-framework.json")) == {
        "startingPoint": "greenfield", "sourceRoot": "app"}
    bad = new_root()
    with open(os.path.join(bad, ".ai-framework.json"), "w", encoding="utf-8") as fh:
        fh.write('{"startingPoint": "sideways"}')
    code, out, err = run(["--starting-point", "greenfield", "--source-root", "app",
                          "--write-config"], bad)
    assert code == 2 and "Traceback" not in err, err
    assert sorted(os.listdir(bad)) == [".ai-framework.json"], os.listdir(bad)


def case_source_root_defaults_to_config():
    root = new_root(with_org=True)
    with open(os.path.join(root, ".ai-framework.json"), "w", encoding="utf-8") as fh:
        json.dump({"sourceRoot": "org"}, fh)
    code, out, err = run(["--starting-point", "existing", "--owner-role", ROLE], root)
    assert code == 0, err
    assert "Source root: `org`" in out, out


def case_owner_role_required_for_existing():
    for extra in ([], ["--owner-role", "  "], ["--owner-role", "a\nb"]):
        root = new_root(with_org=True)
        code, out, err = run(["--starting-point", "existing", "--source-root", "org"] + extra, root)
        assert code == 2 and "Traceback" not in err, (extra, err)
        assert sorted(os.listdir(root)) == ["org"], os.listdir(root)


def case_refuses_outside_root_and_symlinks():
    root = new_root(with_org=True)
    code, _, err = run(["--starting-point", "greenfield", "--source-root", "../elsewhere"], root)
    assert code == 2 and "outside" in err, err
    code, _, err = run(["--starting-point", "greenfield", "--source-root",
                        os.path.dirname(root)], root)
    assert code == 2 and "outside" in err, err
    target = tempfile.mkdtemp(dir=TMP)
    os.makedirs(os.path.join(root, "framework", "knowledge"))
    os.symlink(target, os.path.join(root, STUBS))
    code, _, err = existing(root)
    assert code == 2 and "symlink" in err, err
    assert os.listdir(target) == [] and not os.path.exists(os.path.join(root, "index"))
    linked = new_root()
    os.symlink(target, os.path.join(linked, "app"))
    code, _, err = run(["--starting-point", "greenfield", "--source-root", "app"], linked)
    assert code == 2 and "symlink" in err, err
    assert os.listdir(target) == []
    idx_link = new_root()
    os.symlink(target, os.path.join(idx_link, "index"))
    code, _, err = run(["--starting-point", "greenfield", "--source-root", "app"], idx_link)
    assert code == 2 and "symlink" in err, err
    assert os.listdir(target) == [] and not os.path.exists(os.path.join(idx_link, "app"))
    file_link = new_root()
    outside = os.path.join(target, "outside.json")
    with open(outside, "w", encoding="utf-8") as fh:
        fh.write("untouched\n")
    os.makedirs(os.path.join(file_link, "index"))
    for name in ("metadata.json", "inventory.json"):
        os.symlink(outside, os.path.join(file_link, "index", name))
        code, _, err = run(["--starting-point", "greenfield", "--source-root", "app"], file_link)
        assert code == 2 and "symlink" in err, (name, err)
        with open(outside, encoding="utf-8") as fh:
            assert fh.read() == "untouched\n", name
        assert not os.path.exists(os.path.join(file_link, "app"))
        os.remove(os.path.join(file_link, "index", name))


def case_absolute_source_root_inside_root():
    root = new_root(with_org=True)
    code, out, err = existing(root)
    assert code == 0, err
    code, out2, err = run(["--starting-point", "existing", "--source-root",
                           os.path.join(root, "org"), "--owner-role", ROLE], root)
    assert code == 0, err
    assert out == out2


def case_bad_usage_exits_2():
    root = new_root()
    for args in ([], ["--starting-point", "sideways"]):
        code, _, err = run(args, root)
        assert code == 2 and "Traceback" not in err, (args, err)
    assert os.listdir(root) == []


def main():
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("case_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {exc!r}"[:600])
    total = sum(1 for n in globals() if n.startswith("case_"))
    print(f"{total - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

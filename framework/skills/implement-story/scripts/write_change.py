#!/usr/bin/env python3
"""Deterministic change writer for implement-story. stdlib only.

  python3 write_change.py --id DEMO-202 --slug round-robin-assignment \
      --draft ai-context/DEMO-202-round-robin-assignment/scan/change-draft.json \
      [--package <path>] [--root .]

The draft is the change record without schemaVersion, slug and package (the writer fills those in; a
draft that carries any of them is refused):

  {storyId, files: [{path, component, changeType, evidence, confidence}],
   criteriaToTests: {criterionId: ["<test path>#<method>", ...]},
   done: [{command, exit}]}

The build package is --package, or by default the single impacts/<id>-*/build-package.json under --root
(zero or several folders, or an unreadable package, is exit 2). Its storyId and slug must equal --id and
--slug (exit 2 otherwise).

validate_change(doc, pkg, root) returns every finding; the writer writes nothing when there is one (exit 1):
  - storyId equals the package's;
  - files is a non-empty list; each path appears once and is in the package scope:
    scope.modify (changeType modify), scope.create paths (changeType new, component equal to the
    entry's api) or scope.tests (changeType modify or new); component is a non-empty string;
    confidence is Confirmed, Inferred or Unverifiable; evidence is "<the file's own path>:<line>" with a
    line inside the file as it stands under --root;
  - criteriaToTests has exactly the package's criterion ids as keys, each with at least one
    "<path>#<method>" entry whose path is in scope.tests, is not a -meta.xml companion, exists under
    --root and holds the method name and the criterion id as whole words;
  - done holds every package done[] command exactly once with an integer exit code (true and false are
    not integers here), and no command the package does not list.
The exit codes are the session's own report: the writer never runs or re-runs a done command, so change.md
labels them Inferred. A non-zero exit is recorded as reported, not refused. run_skill.py's
done_all_pass assertion is the check that every exit is 0. run_skill.py loads validate_change from this
file, so the writer and the eval check are one implementation.

On success it writes ai-context/<id>-<slug>/change.json and change.md, never through a symlink, and prints
{changeJson, changeMd, package, doneFailed}. Both outputs are rendered to bytes before either is written;
a failed change.md write removes change.json (exit 2). The output folder must resolve (realpath) inside
<root>/ai-context/ and inside this checkout's ai-context/ (safe_write.checkout_out_dir). Output is
byte-identical across runs (sorted keys, "\\n" endings, no timestamps).

The writer never deploys, pushes or commits, and never widens the package scope. Exit codes: 0 written,
1 validation findings, 2 bad usage.
Code comes from this checkout (located from __file__); data comes from --root.
"""
import argparse
import glob
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# scripts -> implement-story -> skills -> framework|.claude|.github -> repo root
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, os.path.join(REPO, "tools", "impacts"))

from safe_write import checkout_out_dir, write_nofollow  # noqa: E402

STORY_RE = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]+$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LABELS = ("Confirmed", "Inferred", "Unverifiable")
FILLED = ("schemaVersion", "slug", "package")
KEYS = ("storyId", "files", "criteriaToTests", "done")
METHOD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
META_SUFFIX = "-meta.xml"
OUT_JSON = "change.json"
OUT_MD = "change.md"
DONE_SOURCE = ("Exit codes are the session's own report in the draft; write_change.py does not run or re-run "
               "the commands. Confidence: Inferred. CI re-runs them.")


def _show(value):
    try:
        text = json.dumps(value, ensure_ascii=True)
    except (TypeError, ValueError, RecursionError):
        text = type(value).__name__
    return text if len(text) <= 120 else text[:120] + "..."


def _read_text(root, rel):
    """Text of <root>/<rel>, or None when it is missing, a symlink or unreadable."""
    full = os.path.join(root, rel)
    if os.path.islink(full) or not os.path.isfile(full):
        return None
    try:
        with open(full, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _word(token):
    return re.compile(r"(?<![A-Za-z0-9_-])" + re.escape(token) + r"(?![A-Za-z0-9_])")


# ---- the package ----

def package_scope(pkg):
    """(modify set, {create path: api}, tests set, criterion ids, done commands) or ValueError."""
    if not isinstance(pkg, dict):
        raise ValueError("the build package is not a JSON object")
    scope = pkg.get("scope")
    if not isinstance(scope, dict):
        raise ValueError("the build package has no scope object")
    modify, tests, create = scope.get("modify"), scope.get("tests"), scope.get("create")
    if not (isinstance(modify, list) and all(isinstance(x, str) for x in modify)):
        raise ValueError("the build package scope.modify is not a list of paths")
    if not (isinstance(tests, list) and all(isinstance(x, str) for x in tests)):
        raise ValueError("the build package scope.tests is not a list of paths")
    if not (isinstance(create, list) and all(isinstance(e, dict) and isinstance(e.get("path"), str)
                                             and isinstance(e.get("api"), str) for e in create)):
        raise ValueError("the build package scope.create is not a list of {api, type, path}")
    criteria = pkg.get("criteria")
    if not (isinstance(criteria, list) and criteria
            and all(isinstance(c, dict) and isinstance(c.get("id"), str) for c in criteria)):
        raise ValueError("the build package criteria is not a non-empty list with string ids")
    done = pkg.get("done")
    if not (isinstance(done, list) and all(isinstance(d, str) for d in done)):
        raise ValueError("the build package done is not a list of commands")
    return (set(modify), {e["path"]: e["api"] for e in create}, set(tests),
            [c["id"] for c in criteria], list(done))


def find_package(root, story):
    """Path of the single impacts/<story>-*/build-package.json under root, or ValueError."""
    folders = sorted(d for d in glob.glob(os.path.join(glob.escape(root), "impacts", glob.escape(story) + "-*"))
                     if os.path.isdir(d) and SLUG_RE.fullmatch(os.path.basename(d)[len(story) + 1:]))
    if len(folders) != 1:
        raise ValueError("expected exactly one impacts/%s-*/ folder under %s, found %s"
                         % (story, root, ", ".join(os.path.basename(d) for d in folders) or "none"))
    path = os.path.join(folders[0], "build-package.json")
    if not os.path.isfile(path):
        raise ValueError("no build-package.json in %s; a maintainer runs tools/impacts/package.py %s"
                         % (os.path.relpath(folders[0], root), story))
    return path


def load_package(path):
    """(package dict, sha1 of its bytes) or ValueError."""
    if os.path.islink(path):
        raise ValueError("%s is a symlink" % path)
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        pkg = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise ValueError("build package %s cannot be read: %s" % (path, type(exc).__name__))
    package_scope(pkg)
    return pkg, hashlib.sha1(data).hexdigest()


# ---- validation (shared with tools/evals/run_skill.py) ----

def scope_errors(doc, pkg):
    """Findings for files outside the package scope; [] when every file is inside it."""
    modify, create, tests, _, _ = package_scope(pkg)
    allowed = modify | set(create) | tests
    files = doc.get("files") if isinstance(doc, dict) else None
    if not isinstance(files, list):
        return ["files is not a list"]
    return ["file %s is outside the package scope (scope.modify, scope.create, scope.tests)" % _show(f.get("path"))
            for f in files if isinstance(f, dict) and f.get("path") not in allowed]


def done_errors(doc, pkg):
    """Findings for package done[] commands that are missing, repeated, unknown or without an integer exit."""
    _, _, _, _, wanted = package_scope(pkg)
    done = doc.get("done") if isinstance(doc, dict) else None
    if not isinstance(done, list):
        return ["done is not a list of {command, exit}"]
    errors, seen = [], set()
    for d in done:
        if not isinstance(d, dict) or not isinstance(d.get("command"), str):
            errors.append("done entry %s is not {command, exit}" % _show(d))
            continue
        cmd = d["command"]
        if cmd not in wanted:
            errors.append("done command %s is not in the package done[]" % _show(cmd))
        elif cmd in seen:
            errors.append("done command %s appears more than once" % _show(cmd))
        seen.add(cmd)
        if type(d.get("exit")) is not int:
            errors.append("done command %s has exit %s, not an integer" % (_show(cmd), _show(d.get("exit"))))
    errors += ["package done command %s was not run (no entry in done)" % _show(c) for c in wanted if c not in seen]
    return errors


def validate_change(doc, pkg, root=None):
    """Every finding for change record doc against build package pkg; [] when it is valid.

    With root, evidence lines, test files, method names and criterion ids are checked in the files under root."""
    if not isinstance(doc, dict):
        return ["change record is not a JSON object"]
    try:
        modify, create, tests, ids, _ = package_scope(pkg)
    except ValueError as exc:
        return [str(exc)]
    errors = []
    if doc.get("storyId") != pkg.get("storyId"):
        errors.append("storyId %s differs from the package storyId %s" % (_show(doc.get("storyId")),
                                                                         _show(pkg.get("storyId"))))
    files = doc.get("files")
    if not isinstance(files, list) or not files:
        errors.append("files is not a non-empty list")
        files = files if isinstance(files, list) else []
    seen = set()
    for f in files:
        if not isinstance(f, dict):
            errors.append("files entry %s is not an object" % _show(f))
            continue
        path = f.get("path")
        if not isinstance(path, str) or not path:
            errors.append("files entry %s has no path" % _show(f))
            continue
        if path in seen:
            errors.append("file %s is listed more than once" % _show(path))
        seen.add(path)
        ct = f.get("changeType")
        if path in modify:
            if ct != "modify":
                errors.append("file %s is in scope.modify; changeType is %s, not modify" % (path, _show(ct)))
        elif path in create:
            if ct != "new":
                errors.append("file %s is in scope.create; changeType is %s, not new" % (path, _show(ct)))
            if f.get("component") != create[path]:
                errors.append("file %s is scope.create for %s; component is %s"
                              % (path, create[path], _show(f.get("component"))))
        elif path in tests:
            if ct not in ("modify", "new"):
                errors.append("file %s: changeType %s is not modify or new" % (path, _show(ct)))
        else:
            errors.append("file %s is outside the package scope (scope.modify, scope.create, scope.tests)" % path)
        comp = f.get("component")
        if not isinstance(comp, str) or not comp.strip():
            errors.append("file %s has no component" % path)
        if f.get("confidence") not in LABELS:
            errors.append("file %s: confidence %s is not one of %s" % (path, _show(f.get("confidence")),
                                                                    ", ".join(LABELS)))
        ev = f.get("evidence")
        m = re.fullmatch(r"(.+):([1-9][0-9]*)", ev) if isinstance(ev, str) else None
        if not m or m.group(1) != path:
            errors.append("file %s: evidence %s is not '%s:<line>'" % (path, _show(ev), path))
        elif root is not None:
            text = _read_text(root, path)
            if text is None:
                errors.append("file %s: not found under %s" % (path, root))
            elif int(m.group(2)) > len(text.splitlines()):
                errors.append("file %s: evidence line %s is past the end of the file" % (path, m.group(2)))
    c2t = doc.get("criteriaToTests")
    if not isinstance(c2t, dict):
        errors.append("criteriaToTests is not an object")
        c2t = {}
    for key in sorted(k for k in c2t if k not in ids):
        errors.append("criteriaToTests key %s is not a package criterion id" % _show(key))
    for cid in ids:
        refs = c2t.get(cid)
        if not isinstance(refs, list) or not refs:
            errors.append("criterion %s maps to no test" % cid)
            continue
        for ref in refs:
            path, sep, method = ref.partition("#") if isinstance(ref, str) else ("", "", "")
            if not sep or not METHOD_RE.fullmatch(method):
                errors.append("criterion %s: test %s is not '<path>#<method>'" % (cid, _show(ref)))
                continue
            if path not in tests:
                errors.append("criterion %s: test file %s is not in scope.tests" % (cid, _show(path)))
                continue
            if path.endswith(META_SUFFIX):
                errors.append("criterion %s: %s is a metadata companion and cannot hold a test" % (cid, path))
                continue
            if root is not None:
                text = _read_text(root, path)
                if text is None:
                    errors.append("criterion %s: test file %s not found under %s" % (cid, path, root))
                    continue
                if not _word(method).search(text):
                    errors.append("criterion %s: method %s not found in %s" % (cid, method, path))
                if not _word(cid).search(text):
                    errors.append("criterion %s: id not found in %s (each test method carries a // %s comment)"
                                  % (cid, path, cid))
    errors += done_errors(doc, pkg)
    return errors


# ---- markdown ----

def _cell(value):
    text = " ".join(str(value).split())
    return text.replace("\\", "\\\\").replace("|", "\\|")


def render_md(doc):
    failed = [d for d in doc["done"] if d["exit"] != 0]
    lines = ["# Change: %s %s" % (doc["storyId"], doc["slug"]), "",
             "Built from `%s` (sha1 %s). Every file below is inside that package's scope."
             % (doc["package"]["path"], doc["package"]["sha1"]), "",
             "## Files", "",
             "| File | Component | Change | Evidence | Confidence |",
             "|---|---|---|---|---|"]
    for f in sorted(doc["files"], key=lambda x: x["path"]):
        lines.append("| `%s` | %s | %s | `%s` | %s |" % (_cell(f["path"]), _cell(f["component"]),
                                                       _cell(f["changeType"]), _cell(f["evidence"]),
                                                       f["confidence"]))
    lines += ["", "## Criteria to tests", "", "| Criterion | Tests |", "|---|---|"]
    for cid in sorted(doc["criteriaToTests"]):
        lines.append("| %s | %s |" % (cid, ", ".join("`%s`" % _cell(t) for t in doc["criteriaToTests"][cid])))
    lines += ["", "## Done commands", "", "| Order | Command | Exit |", "|---|---|---|"]
    for i, d in enumerate(doc["done"], 1):
        lines.append("| %d | `%s` | %d |" % (i, _cell(d["command"]), d["exit"]))
    lines += ["", DONE_SOURCE, ""]
    if failed:
        lines.append("Not done (Inferred): %s reported a non-zero exit."
                     % ", ".join("`%s`" % _cell(d["command"]) for d in failed))
    else:
        lines.append("Every done command was reported with exit 0 (Inferred).")
    lines += ["", "Apex compiles and runs only in the org-connected CI; the done commands are offline checks. "
              "The change is unreviewed until a named reviewer reviews the pull request. The assistant does "
              "not deploy, push or merge it.", "",
              "_Generated by write_change.py from change.json._", ""]
    return "\n".join(lines)


# ---- main ----

def usage(msg):
    print(msg, file=sys.stderr)
    return 2


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write change.json and change.md for one story's build.",
                                 allow_abbrev=False)
    ap.add_argument("--id", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--draft", required=True)
    ap.add_argument("--package", default=None,
                    help="build-package.json (default: the single impacts/<id>-*/build-package.json under --root)")
    ap.add_argument("--root", default=".")
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if not STORY_RE.match(a.id):
        return usage("--id '%s' does not match %s" % (a.id, STORY_RE.pattern))
    if not SLUG_RE.match(a.slug):
        return usage("--slug '%s' does not match %s" % (a.slug, SLUG_RE.pattern))
    try:
        out_dir = checkout_out_dir(a.root, "%s-%s" % (a.id, a.slug))
    except ValueError:
        return usage("output folder for %s-%s resolves outside <root>/ai-context/ or outside the "
                     "checkout's ai-context/; nothing written" % (a.id, a.slug))
    try:
        pkg_path = a.package or find_package(a.root, a.id)
        pkg, sha = load_package(pkg_path)
    except ValueError as exc:
        return usage("%s; nothing written" % exc)
    if pkg.get("storyId") != a.id or pkg.get("slug") != a.slug:
        return usage("build package is for %s-%s, not %s-%s; nothing written"
                     % (pkg.get("storyId"), pkg.get("slug"), a.id, a.slug))
    try:
        with open(a.draft, encoding="utf-8") as fh:
            draft = json.load(fh)
    except (OSError, ValueError) as exc:
        return usage("cannot read draft JSON: %s" % exc)
    if not isinstance(draft, dict):
        return usage("--draft is not a JSON object")

    errors = ["draft carries '%s'; write_change.py fills it in" % k for k in FILLED if k in draft]
    errors += ["draft carries unknown key %s" % _show(k) for k in sorted(draft) if k not in KEYS + FILLED]
    if "storyId" in draft and draft["storyId"] != a.id:
        errors.append("draft storyId %s differs from --id '%s'" % (_show(draft["storyId"]), a.id))
    if not errors:
        doc = dict(draft)
        doc.setdefault("storyId", a.id)
        errors = validate_change(doc, pkg, a.root)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1

    top = os.path.realpath(a.root)
    real_pkg = os.path.realpath(pkg_path)
    rel_pkg = (os.path.relpath(real_pkg, top) if os.path.commonpath([top, real_pkg]) == top
               else real_pkg).replace(os.sep, "/")
    doc.update({"schemaVersion": 1, "slug": a.slug, "package": {"path": rel_pkg, "sha1": sha}})
    jbytes = (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8")
    mbytes = render_md(doc).encode("utf-8")

    jpath = os.path.join(out_dir, OUT_JSON)
    mpath = os.path.join(out_dir, OUT_MD)
    for p in (jpath, mpath):
        if os.path.islink(p):
            return usage("%s is a symlink; nothing written" % p)
    os.makedirs(out_dir, exist_ok=True)
    try:
        write_nofollow(jpath, jbytes)
    except OSError as exc:
        return usage("cannot write output without following a symlink: %s" % exc)
    try:
        write_nofollow(mpath, mbytes)
    except OSError as exc:
        try:
            os.remove(jpath)
        except OSError:
            pass
        return usage("cannot write %s (%s); change.json removed, nothing written" % (mpath, exc))
    print(json.dumps({"changeJson": jpath, "changeMd": mpath, "package": rel_pkg,
                      "doneFailed": [d["command"] for d in doc["done"] if d["exit"] != 0]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

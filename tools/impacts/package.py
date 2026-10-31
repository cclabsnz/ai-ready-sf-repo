#!/usr/bin/env python3
"""Assemble a story's build package: the agent's only input for coding. A maintainer step. stdlib only.

  python3 tools/impacts/package.py <storyId> [--root .] [--index <dir>]

Runs in maintain mode only, as a human or maintainer step. It finds the single impacts/<storyId>-*/ folder
under --root and writes build-package.json and build-package.md into it, never through a symlink. The
package is committed with the impact PR; the guard's scope lock reads it from HEAD.

It refuses (exit 1, naming the reason, nothing written) unless:
  - story.json is a confirmed story (tools/stories/validate_story.py) and check_ac.py has no findings;
  - design.json is a confirmed design (tools/designs/validate_design.py, no index);
  - impact.json is a promoted, in-flight impact (tools/impacts/validate.py) whose chosenOption equals the
    design's chosenOption; the three records carry the folder's storyId and slug;
  - the impact's index stamp is not stale: the stamp commit exists (git cat-file -e) and
    `git diff --name-only <stamp> HEAD -- ':(literal)<sourceRoot>' ':(exclude,literal)impacts'` is empty.
    impacts/ is excluded, so committing the impact (or the package) never makes its own stamp stale, even
    with sourceRoot "."; any other change under the source root does. The same rule applies to the --index
    stamp;
  - --root is the top level of its git repo (git -C would otherwise read an enclosing repo's history);
  - no impact component is a delete ("deletes are done by a human in this version");
  - .ai-framework.json names sourceRoot explicitly, as the guard requires (no "." default);
  - every derived path passes validate_package(): the guard's own scope rules (scope_core).

Scope (exact repo-relative file paths, no directories, no globs; sorted):
  modify  impact components with changeType modify, located through the index (--index, default
          <checkout>/index; exit 2 when it cannot be loaded):
            ApexClass, ApexTrigger      the node path and <path>-meta.xml
            LightningComponentBundle,
            AuraDefinitionBundle        every regular file in the bundle folder (not __tests__/, no dotfiles,
                                        no symlinks)
            any other type              the node path (CustomField: the field-meta file)
          A component missing from the index, of another type than its node, or with no node path (a
          standard object) is refused by name. Every listed file exists in the work tree.
  create  impact components with changeType new, as {api, type, path}, one entry per file. Design
          components carry no path (validate_design rejects the key), so paths come from this table, with
          <base> = <sourceRoot>/force-app/main/default:
            ApexClass                   <base>/classes/<Api>.cls and <Api>.cls-meta.xml
            CustomField Obj.F           <base>/objects/Obj/fields/F.field-meta.xml
            CustomObject                <base>/objects/<Api>/<Api>.object-meta.xml
            LightningComponentBundle    <base>/lwc/<name>/<name>.js, <name>.html and <name>.js-meta.xml
          Any other type is refused, naming it. When the impact component's path is set, it must be one of
          the derived paths (or the LWC bundle folder); otherwise it is refused. A path that already exists
          is refused.
  tests   for each Apex class in modify or create: <Name>_Test.cls and its -meta.xml, at the index path of
          <Name>_Test when it exists, else beside the class. For each LWC: <bundle>/__tests__/<name>.test.js.
          An Apex class named *_Test, or indexed with isTest true, is itself a test: its files go to tests,
          never to modify or create, and no test is derived from it. tests may list files still to create.

The new-component path table above and the edge-case mapping below were accepted at the WS8 Task 2 review.

criteria: every acceptance criterion as {id, given, when, then, examples}, then every kept edge case
(becameCriterion null) mapped without new text: given = its component, when = its category, then = its
detail, examples = [its evidence] (or [] when evidence is null). An edge case that became a criterion is
covered by that AC. Open questions never count.

design: {chosenOption, reasons, rejected: [{id, title}]}. reasons are the recommendation's reasons when
the chosen option is the recommended one, else [] (they argue for another option).

rules: [{id, check: "python3 tools/code/check_rules.py"}] for every Apex rule id in check_rules.RULE_IDS,
when scope holds a .cls or .trigger file; else [].
done: the fixed commands, plus "pnpm exec sfdx-lwc-jest" when scope holds an LWC.
provenance: sha1 of the story, design and impact files as read, the impact's indexStamp, the framework
version (<root>/VERSION), and each record's confirmedBy.

Output is byte-identical across runs (sorted keys, "\\n" endings, no timestamps). Both files are scanned
with the data guard before writing.
A new component whose api is already an index node (compared case-insensitively) is refused, naming the
node's path. git runs with every GIT_* variable of the caller's environment removed (register._git_env), so
GIT_DIR, GIT_LITERAL_PATHSPECS and the like cannot redirect it or switch off the stale check.
Exit codes: 0 written, 1 refused, 2 bad usage (bad storyId, unloadable index) or a failed build-package.md
write (the build-package.json just written is removed).
Code comes from this checkout (located from __file__); data comes from --root.
"""
import argparse
import glob
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(1, os.path.join(REPO, "tools", "stories"))
sys.path.insert(2, os.path.join(REPO, "tools", "designs"))
sys.path.insert(3, os.path.join(REPO, "tools", "config"))

from validate import STORY_RE, validate  # noqa: E402
from validate_story import validate_story  # noqa: E402
from check_ac import check_ac, load_vague  # noqa: E402
from validate_design import load_index, validate_design  # noqa: E402
import framework_config  # noqa: E402
from register import GIT_SAFE, _git_env  # noqa: E402  (the same git hardening as register.py)
from safe_write import write_nofollow  # noqa: E402
from promote import scan_final  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RULE_IDS = _load("check_rules", os.path.join(REPO, "tools", "code", "check_rules.py")).RULE_IDS
DEFAULT_INDEX = os.path.join(REPO, "index")
RULE_CHECK = "python3 tools/code/check_rules.py"
LWC_JEST = "pnpm exec sfdx-lwc-jest"
RECORDS = ("story.json", "design.json", "impact.json")
OUT_JSON = "build-package.json"
OUT_MD = "build-package.md"
API_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
COMMIT_RE = re.compile(r"^[0-9a-fA-F]{4,64}$")
BUNDLE_TYPES = ("LightningComponentBundle", "AuraDefinitionBundle")
APEX_TYPES = ("ApexClass", "ApexTrigger")
NEW_TYPES = ("ApexClass", "CustomField", "CustomObject", "LightningComponentBundle")

# ---- the guard's scope rules (mirrors scope_core._validate; a drift check keeps the two equal) ----

MAX_BLOB = 1024 * 1024
MAX_ENTRIES = 2000
ACTIVE_STORY_RE = re.compile(r"^[A-Z][A-Z0-9]*-[0-9]+$")
ACTIVE_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CRITERION_RE = re.compile(r"^(?:AC|EC)-[0-9]+$")
GLOB_CHARS = set("*?[]{}")
RESERVED_PREFIXES = ("impacts/", "tools/", "framework/", ".claude/", ".github/", "ai-context/")
RESERVED_EXACT = (".ai-framework.json",)
RESERVED_PARTS = (".git",)
RESERVED_NAMES = ("codeowners",)


def _bad_char(text):
    """True when text holds a C0/C1 control character, DEL, or a bidi embedding/override/isolate."""
    for ch in text:
        o = ord(ch)
        if o < 32 or 127 <= o <= 159 or 0x202A <= o <= 0x202E or 0x2066 <= o <= 0x2069:
            return True
    return False


def _show(value):
    try:
        text = json.dumps(value, ensure_ascii=True)
    except (TypeError, ValueError, RecursionError):
        text = type(value).__name__
    return text if len(text) <= 200 else text[:200] + "..."


def _resolved(top, rel):
    try:
        return os.path.relpath(os.path.realpath(os.path.join(top, rel)), top).replace("\\", "/")
    except ValueError:
        return None


def _entry_problem(top, src, where, item):
    """None when item is an exact, canonical, repo-relative file path under src, outside the reserved paths."""
    if not isinstance(item, str):
        return "%s: entry %s is not a string" % (where, _show(item))
    if item == "":
        return "%s: empty entry" % where
    if _bad_char(item):
        return "%s: entry %s contains a control character" % (where, _show(item))
    if "\\" in item:
        return "%s: entry %s contains a backslash" % (where, _show(item))
    if item.startswith("/") or os.path.isabs(item):
        return "%s: entry %s is absolute" % (where, _show(item))
    if GLOB_CHARS & set(item):
        return "%s: entry %s contains a glob character" % (where, _show(item))
    parts = item.split("/")
    if ".." in parts:
        return "%s: entry %s contains '..'" % (where, _show(item))
    if "." in parts:
        return "%s: entry %s contains a '.' segment" % (where, _show(item))
    if "" in parts:
        return "%s: entry %s has an empty segment" % (where, _show(item))
    low = item.lower()
    if (low.startswith(RESERVED_PREFIXES) or low in RESERVED_EXACT
            or any(p.lower() in RESERVED_PARTS for p in parts) or parts[-1].lower() in RESERVED_NAMES):
        return "%s: entry %s is a reserved framework path" % (where, _show(item))
    if not (src == "." or item.startswith(src + "/")):
        return "%s: entry %s is outside sourceRoot %s" % (where, _show(item), _show(src))
    if top is not None and _resolved(top, item) != item:
        return "%s: entry %s resolves through a symlink" % (where, _show(item))
    return None


def validate_package(pkg, source_root, root=None):
    """Problems with pkg under the guard's scope rules, [] when the guard accepts it.

    source_root is the repo-relative source root as the guard computes it ("." or a/b). With root, entries
    that resolve through a symlink under root are problems too, as they are for the guard. The guard stops
    at its first finding; this returns every finding it reaches (a malformed top level stops early)."""
    errors = []
    if not isinstance(pkg, dict):
        return ["build-package.json is not a JSON object"]
    version = pkg.get("schemaVersion")
    if type(version) is not int or version != 1:
        errors.append("build-package.json: schemaVersion %s is not 1" % _show(version))
    story, slug = pkg.get("storyId"), pkg.get("slug")
    if not (isinstance(story, str) and ACTIVE_STORY_RE.fullmatch(story)):
        errors.append("build-package.json: storyId %s is not <PREFIX>-<n>" % _show(story))
    if not (isinstance(slug, str) and ACTIVE_SLUG_RE.fullmatch(slug)):
        errors.append("build-package.json: slug %s is not a lowercase slug" % _show(slug))
    scope = pkg.get("scope")
    if not isinstance(scope, dict):
        return errors + ["build-package.json: scope is not an object"]
    lists = {}
    for key in ("modify", "create", "tests"):
        value = scope.get(key)
        if not isinstance(value, list):
            errors.append("build-package.json: scope.%s is not a list" % key)
        else:
            lists[key] = value
    criteria = pkg.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        errors.append("build-package.json: criteria is not a non-empty list")
        criteria = criteria if isinstance(criteria, list) else []
    if len(lists) < 3:
        return errors
    total = sum(len(v) for v in lists.values()) + len(criteria)
    if total > MAX_ENTRIES:
        errors.append("build-package.json: %d scope and criteria entries is more than %d" % (total, MAX_ENTRIES))
    top = os.path.realpath(root) if root is not None else None
    for key in ("modify", "tests"):
        where = "scope." + key
        seen = set()
        for item in lists[key]:
            problem = _entry_problem(top, source_root, where, item)
            if problem:
                errors.append("build-package.json: " + problem)
                continue
            if item in seen:
                errors.append("build-package.json: %s: duplicate entry %s" % (where, _show(item)))
            seen.add(item)
    seen = set()
    for item in lists["create"]:
        if not isinstance(item, dict):
            errors.append("build-package.json: scope.create: entry %s is not an object with api, type and path"
                          % _show(item))
            continue
        missing = [f for f in ("api", "type", "path") if not isinstance(item.get(f), str) or not item.get(f)]
        if missing:
            errors.append("build-package.json: scope.create: entry %s has no string %s" % (_show(item), missing[0]))
            continue
        problem = _entry_problem(top, source_root, "scope.create", item["path"])
        if problem:
            errors.append("build-package.json: " + problem)
        elif item["path"] in seen:
            errors.append("build-package.json: scope.create: duplicate entry %s" % _show(item["path"]))
        seen.add(item["path"])
    ids = set()
    for c in criteria:
        if not isinstance(c, dict):
            errors.append("build-package.json: criterion %s is not an object" % _show(c))
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not CRITERION_RE.fullmatch(cid):
            errors.append("build-package.json: criterion id %s is not AC-<n> or EC-<n>" % _show(cid))
        elif cid in ids:
            errors.append("build-package.json: duplicate criterion id %s" % cid)
        else:
            ids.add(cid)
    try:
        size = len(package_bytes(pkg))
    except (TypeError, ValueError, RecursionError):
        size = None
        errors.append("build-package.json: the package is not serialisable as JSON")
    if size is not None and size > MAX_BLOB:
        errors.append("build-package.json is %d bytes, larger than %d" % (size, MAX_BLOB))
    return errors


def package_bytes(pkg):
    return (json.dumps(pkg, indent=2, sort_keys=True) + "\n").encode("utf-8")


# ---- source root, as the guard reads it (explicit, realpath'd, relative to the repo) ----

def source_root_rel(root):
    """(rel_source_root, None) or (None, problem). Like scope_core, a missing sourceRoot is a problem."""
    path = os.path.join(root, framework_config.FILENAME)
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except FileNotFoundError:
        return None, "%s is missing; scoped writes need an explicit sourceRoot" % framework_config.FILENAME
    except (OSError, ValueError, RecursionError) as exc:
        return None, "%s cannot be read: %s" % (framework_config.FILENAME, type(exc).__name__)
    if not isinstance(raw, dict) or "sourceRoot" not in raw:
        return None, "%s has no sourceRoot; scoped writes need an explicit sourceRoot" % framework_config.FILENAME
    src = raw["sourceRoot"]
    if not isinstance(src, str) or not src.strip():
        return None, "%s: sourceRoot %s is not a non-empty string" % (framework_config.FILENAME, _show(src))
    if _bad_char(src) or "\\" in src or src.startswith("/") or os.path.isabs(src) or ".." in src.split("/"):
        return None, "%s: sourceRoot %s is not a plain repo-relative path" % (framework_config.FILENAME, _show(src))
    try:
        real = framework_config.source_root(root)
    except ValueError as exc:
        return None, str(exc)
    top = os.path.realpath(root)
    return os.path.relpath(real, top).replace(os.sep, "/"), None


# ---- git (read-only, hardened as register.py) ----

def _git(top, args):
    try:
        return subprocess.run(["git", "-C", top] + GIT_SAFE + args,
                              capture_output=True, text=True, timeout=30, env=_git_env())
    except (OSError, subprocess.SubprocessError):
        return None


def toplevel_problem(top):
    p = _git(top, ["rev-parse", "--show-toplevel"])
    if p is None or p.returncode != 0:
        return "%s is not inside a git repository; the stale check needs its history" % top
    found = os.path.realpath(p.stdout.strip())
    if found != top:
        return "%s is not the top level of its git repository (%s); pass the repository root as --root" % (top, found)
    return None


def stale_problem(top, commit, src, what):
    """None when commit exists and nothing under src changed between it and HEAD, else the finding."""
    if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit):
        return "%s %s is unknown or unreachable; the stamp is stale: rebuild the index and re-assess" % (
            what, _show(commit))
    p = _git(top, ["cat-file", "-e", commit + "^{commit}"])
    if p is None or p.returncode != 0:
        return "%s %s is unknown or unreachable; the stamp is stale: rebuild the index and re-assess" % (what, commit)
    # impacts/ is excluded: committing the impact (or this package) never makes its own stamp stale, even
    # with sourceRoot ".". The source root is matched literally, so a glob character in it is not magic.
    p = _git(top, ["diff", "--name-only", "--no-renames", commit, "HEAD", "--",
                   ":(literal)" + src, ":(exclude,literal)impacts"])
    if p is None or p.returncode != 0:
        return "git diff from %s %s to HEAD failed; the stamp cannot be checked" % (what, commit)
    changed = [line for line in p.stdout.splitlines() if line.strip()]
    if changed:
        shown = ", ".join(changed[:5]) + (", ..." if len(changed) > 5 else "")
        return ("%s %s is stale: the source root %s changed since (%s); rebuild the index and re-assess"
                % (what, commit[:12], src, shown))
    return None


# ---- records ----

class Refused(Exception):
    pass


def _read_record(folder, name):
    path = os.path.join(folder, name)
    if os.path.islink(path):
        raise Refused("%s is a symlink" % path)
    if not os.path.isfile(path):
        raise Refused("%s is missing" % path)
    with open(path, "rb") as fh:
        data = fh.read()
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise Refused("%s is not valid JSON: %s" % (path, type(exc).__name__))
    if not isinstance(doc, dict):
        raise Refused("%s is not a JSON object" % path)
    return doc, hashlib.sha1(data).hexdigest()


def _errors(name, what, errors):
    if errors:
        raise Refused("%s is not %s: %s" % (name, what, "; ".join(errors)))


def check_records(story, design, impact, root, folder_name):
    _errors("story.json", "a confirmed story", validate_story(story, "confirmed", root))
    findings = check_ac(story, load_vague())
    if findings:
        raise Refused("story.json: acceptance criteria have findings: %s" % "; ".join(
            "%s %s: %s" % (f["id"], f["rule"], f["detail"]) for f in findings))
    _errors("design.json", "a confirmed design", validate_design(design, "confirmed", root))
    _errors("impact.json", "a promoted impact", validate(impact, "promoted", root))
    if impact["status"] != "in-flight":
        raise Refused("impact.json status is %s; a package is built for an in-flight impact" % impact["status"])
    for name, doc in (("story.json", story), ("design.json", design), ("impact.json", impact)):
        if "%s-%s" % (doc["storyId"], doc["slug"]) != folder_name:
            raise Refused("%s is for %s-%s, the folder is %s" % (name, doc["storyId"], doc["slug"], folder_name))
    if "chosenOption" not in impact:
        raise Refused("impact.json has no chosenOption; promote it with its design first")
    if impact["chosenOption"] != design["chosenOption"]:
        raise Refused("impact.json chosenOption %s differs from design.json chosenOption %s"
                      % (impact["chosenOption"], design["chosenOption"]))
    deletes = [c["api"] for c in impact["components"] if c["changeType"] == "delete"]
    if deletes:
        raise Refused("deletes are done by a human in this version: %s" % ", ".join(deletes))


# ---- derivation ----

def _base(src):
    return "force-app/main/default" if src == "." else src + "/force-app/main/default"


def _dirname(path):
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _bundle_files(top, folder):
    full = os.path.join(top, folder)
    if os.path.islink(full) or not os.path.isdir(full):
        raise Refused("bundle folder %s from the index is not a folder in the work tree; rebuild the index" % folder)
    names = []
    for name in sorted(os.listdir(full)):
        p = os.path.join(full, name)
        if name.startswith(".") or os.path.islink(p) or not os.path.isfile(p):
            continue
        names.append(folder + "/" + name)
    return names


def _new_paths(src, comp):
    """The derived file paths for a new component, or Refused naming the type."""
    api, typ = comp["api"], comp["type"]
    base = _base(src)
    if typ not in NEW_TYPES:
        raise Refused("%s (changeType new) has type %s, which has no path rule in package.py; known types: %s"
                      % (api, typ, ", ".join(NEW_TYPES)))
    if typ == "CustomField":
        obj, _, field = api.partition(".")
        if not (API_RE.fullmatch(obj) and API_RE.fullmatch(field)):
            raise Refused("%s (CustomField, changeType new) is not Object.Field" % _show(api))
        return ["%s/objects/%s/fields/%s.field-meta.xml" % (base, obj, field)], None
    if not API_RE.fullmatch(api):
        raise Refused("%s (%s, changeType new) is not a plain API name" % (_show(api), typ))
    if typ == "ApexClass":
        cls = "%s/classes/%s.cls" % (base, api)
        return [cls, cls + "-meta.xml"], None
    if typ == "CustomObject":
        return ["%s/objects/%s/%s.object-meta.xml" % (base, api, api)], None
    folder = "%s/lwc/%s" % (base, api)
    return [folder + "/" + api + ext for ext in (".js", ".html", ".js-meta.xml")], folder


def derive_scope(impact, idx, src, top):
    """(modify, create, tests, has_lwc) from the impact's modify and new components."""
    nodes = idx["nodes"]
    modify, create, tests = [], [], []
    apex, lwc = [], []          # (name, main path) of non-test classes; (name, bundle folder)
    for c in impact["components"]:
        api, typ, ct = c["api"], c["type"], c["changeType"]
        if ct == "modify":
            node = nodes.get(api)
            if not isinstance(node, dict):
                raise Refused("%s (changeType modify) is not a node in the index; zero hits for the exact API name"
                              % api)
            if node.get("type") != typ:
                raise Refused("%s is %s in impact.json but %s in the index" % (api, typ, node.get("type")))
            npath = node.get("path")
            if not isinstance(npath, str) or not npath:
                raise Refused("%s (%s) has no path in the index (a standard object or org-only metadata); "
                              "it cannot be scoped" % (api, typ))
            if typ in APEX_TYPES:
                files = [npath, npath + "-meta.xml"]
                is_test = typ == "ApexClass" and (api.endswith("_Test") or node.get("isTest") is True)
                (tests if is_test else modify).extend(files)
                if typ == "ApexClass" and not is_test:
                    apex.append((api, npath))
            elif typ in BUNDLE_TYPES:
                modify.extend(_bundle_files(top, npath))
                if typ == "LightningComponentBundle":
                    lwc.append((api, npath))
            else:
                modify.append(npath)
        elif ct == "new":
            low = api.lower()
            clash = sorted(k for k in nodes if isinstance(k, str) and k.lower() == low)
            if clash:
                held = nodes[clash[0]] if isinstance(nodes[clash[0]], dict) else {}
                raise Refused("%s (changeType new) already exists as index node %s at %s; re-assess it as modify"
                              % (api, clash[0], _show(held.get("path"))))
            files, folder = _new_paths(src, c)
            given = c.get("path")
            if given is not None and given not in files and given != folder:
                raise Refused("%s: impact path %s is not the derived path %s (rule table in package.py)"
                              % (api, _show(given), files[0]))
            if typ == "ApexClass" and api.endswith("_Test"):
                tests.extend(files)
                continue
            create.extend({"api": api, "type": typ, "path": p} for p in files)
            if typ == "ApexClass":
                apex.append((api, files[0]))
            elif typ == "LightningComponentBundle":
                lwc.append((api, folder))
    for name, main in apex:
        node = nodes.get(name + "_Test")
        if isinstance(node, dict) and node.get("type") == "ApexClass" and isinstance(node.get("path"), str) \
                and node["path"]:
            tpath = node["path"]
        else:
            tpath = "%s/%s_Test.cls" % (_dirname(main), name)
        tests.extend([tpath, tpath + "-meta.xml"])
    for name, folder in lwc:
        tests.append("%s/__tests__/%s.test.js" % (folder, name))
    tests = sorted(set(tests))
    modify = sorted(set(modify) - set(tests))
    by_path = {}
    for e in create:
        if e["path"] not in tests:
            by_path.setdefault(e["path"], e)
    create = [by_path[p] for p in sorted(by_path)]
    return modify, create, tests, bool(lwc)


def criteria_of(story):
    out = [{"id": a["id"], "given": a["given"], "when": a["when"], "then": a["then"],
            "examples": list(a["examples"])} for a in story["acceptanceCriteria"]]
    for e in story["edgeCases"]:
        if e["becameCriterion"] is None:
            out.append({"id": e["id"], "given": e["component"], "when": e["category"], "then": e["detail"],
                        "examples": [e["evidence"]] if e["evidence"] is not None else []})
    return out


def design_of(design):
    chosen = design["chosenOption"]
    rec = design["recommendation"]
    return {"chosenOption": chosen,
            "reasons": list(rec["reasons"]) if rec["optionId"] == chosen else [],
            "rejected": [{"id": o["id"], "title": o["title"]} for o in design["options"] if o["id"] != chosen]}


def framework_version(root):
    try:
        with open(os.path.join(root, "VERSION"), encoding="utf-8") as fh:
            return fh.read().strip() or "unknown"
    except OSError:
        return "unknown"


def done_of(story_id, has_lwc):
    done = ["python3 tools/code/check_trace.py --skeletons %s" % story_id,
            "python3 tools/code/check_rules.py --from-config",
            "python3 tools/code/check_trace.py %s" % story_id]
    return done + [LWC_JEST] if has_lwc else done


# ---- markdown ----

def _one(v):
    return " ".join(str(v).split())


def render_md(pkg, top):
    p = pkg["provenance"]
    lines = ["# Build package: %s %s" % (pkg["storyId"], pkg["slug"]), "",
             "Assembled by tools/impacts/package.py from the confirmed story, design and impact. "
             "The agent builds from build-package.json; this file is the readable copy.", "",
             "## Criteria", ""]
    for c in pkg["criteria"]:
        lines += ["### %s" % c["id"], "",
                  "- Given: %s" % _one(c["given"]), "- When: %s" % _one(c["when"]),
                  "- Then: %s" % _one(c["then"]),
                  "- Examples: %s" % ("; ".join(_one(e) for e in c["examples"]) or "none"), ""]
    d = pkg["design"]
    lines += ["## Design", "", "Chosen option: %s" % d["chosenOption"], "", "Reasons:"]
    lines += ["- %s" % _one(r) for r in d["reasons"]] or ["- none recorded for the chosen option"]
    lines += ["", "Options not chosen:"]
    lines += ["- %s: %s" % (r["id"], _one(r["title"])) for r in d["rejected"]] or ["- none"]
    s = pkg["scope"]
    lines += ["", "## Scope", "", "### Modify", ""]
    lines += ["- `%s`" % x for x in s["modify"]] or ["- none"]
    lines += ["", "### Create", ""]
    lines += ["- `%s` (%s %s)" % (e["path"], e["type"], e["api"]) for e in s["create"]] or ["- none"]
    lines += ["", "### Tests", ""]
    lines += ["- `%s` (%s)" % (t, "exists" if os.path.isfile(os.path.join(top, t)) else "to create")
              for t in s["tests"]] or ["- none"]
    lines += ["", "## Rules", ""]
    lines += ["- %s: `%s`" % (r["id"], r["check"]) for r in pkg["rules"]] or ["- none"]
    lines += ["", "## Done", "", "Each command exits 0, in this order:", ""]
    lines += ["%d. `%s`" % (i + 1, cmd) for i, cmd in enumerate(pkg["done"])]
    cb = p["confirmedBy"]
    lines += ["", "## Provenance", "",
              "- story.json sha1: %s" % p["story"], "- design.json sha1: %s" % p["design"],
              "- impact.json sha1: %s" % p["impact"],
              "- Index stamp commit: %s" % _one(p["indexStamp"].get("commit", "unknown")),
              "- Framework version: %s" % _one(p["frameworkVersion"]),
              "- Confirmed by: story %s; design %s; impact %s" % (_one(cb["story"]), _one(cb["design"]),
                                                                 _one(cb["impact"])), ""]
    return "\n".join(lines)


# ---- main ----

def build(story_id, root, idx):
    """(package, folder) or Refused."""
    top = os.path.realpath(root)
    imp = os.path.join(root, "impacts")
    if os.path.islink(imp) or not os.path.isdir(imp):
        raise Refused("%s is not a folder" % imp)
    folders = sorted(f for f in glob.glob(os.path.join(glob.escape(imp), glob.escape(story_id) + "-*"))
                     if os.path.isdir(f) and not os.path.islink(f))
    if len(folders) != 1:
        raise Refused("expected exactly one impacts/%s-*/ folder, found %s" % (
            story_id, ", ".join(os.path.basename(f) for f in folders) or "none"))
    folder = folders[0]
    docs, sums = {}, {}
    for name in RECORDS:
        docs[name], sums[name] = _read_record(folder, name)
    story, design, impact = docs["story.json"], docs["design.json"], docs["impact.json"]
    check_records(story, design, impact, root, os.path.basename(folder))
    src, problem = source_root_rel(root)
    if problem:
        raise Refused(problem)
    problem = toplevel_problem(top)
    if problem:
        raise Refused(problem)
    stamp = impact["provenance"]["indexStamp"]
    problem = stale_problem(top, stamp.get("commit"), src, "impact.json index stamp")
    if problem:
        raise Refused(problem)
    istamp = idx.get("stamp") if isinstance(idx.get("stamp"), dict) else {}
    problem = stale_problem(top, istamp.get("commit"), src, "--index stamp")
    if problem:
        raise Refused(problem)
    modify, create, tests, has_lwc = derive_scope(impact, idx, src, top)
    if not modify and not create:
        raise Refused("nothing to build: the impact has no modify or new component outside tests")
    apex = any(x.endswith((".cls", ".trigger")) for x in modify + tests + [e["path"] for e in create])
    pkg = {"schemaVersion": 1, "storyId": story["storyId"], "slug": story["slug"],
           "criteria": criteria_of(story), "design": design_of(design),
           "scope": {"modify": modify, "create": create, "tests": tests},
           "rules": [{"id": r, "check": RULE_CHECK} for r in RULE_IDS] if apex else [],
           "done": done_of(story["storyId"], has_lwc),
           "provenance": {"story": sums["story.json"], "design": sums["design.json"], "impact": sums["impact.json"],
                          "indexStamp": stamp, "frameworkVersion": framework_version(root),
                          "confirmedBy": {"story": story["confirmedBy"], "design": design["confirmedBy"],
                                          "impact": impact["confirmedBy"]}}}
    errors = validate_package(pkg, src, root=root)
    if errors:
        raise Refused("the package fails the guard's scope rules: %s" % "; ".join(errors))
    for x in modify:
        if not os.path.isfile(os.path.join(top, x)):
            raise Refused("%s (from the index) is not a file in the work tree; rebuild the index" % x)
    for e in create:
        if os.path.lexists(os.path.join(top, e["path"])):
            raise Refused("%s (changeType new) already exists at %s; re-assess it as modify" % (e["api"], e["path"]))
    return pkg, folder


def main(argv=None):
    ap = argparse.ArgumentParser(description="Assemble a story's build package from its confirmed records.")
    ap.add_argument("story_id")
    ap.add_argument("--root", default=".")
    ap.add_argument("--index", default=None, help="index dir (default <checkout>/index)")
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if not STORY_RE.fullmatch(a.story_id):
        print("storyId %s does not match %s" % (_show(a.story_id), STORY_RE.pattern), file=sys.stderr)
        return 2
    idx, problem = load_index(a.index or DEFAULT_INDEX)
    if problem:
        print("%s; nothing written" % problem, file=sys.stderr)
        return 2
    try:
        pkg, folder = build(a.story_id, a.root, idx)
    except Refused as exc:
        print("%s; nothing written" % exc, file=sys.stderr)
        return 1
    top = os.path.realpath(a.root)
    json_bytes = package_bytes(pkg)
    md_bytes = render_md(pkg, top).encode("utf-8")
    djson, dmd = os.path.join(folder, OUT_JSON), os.path.join(folder, OUT_MD)
    for p in (os.path.join(a.root, "impacts"), folder, djson, dmd):
        if os.path.islink(p):
            print("%s is a symlink; nothing written" % p, file=sys.stderr)
            return 1
    imp_real = os.path.join(top, "impacts")
    if not os.path.realpath(folder).startswith(imp_real + os.sep):
        print("%s resolves outside <root>/impacts/; nothing written" % folder, file=sys.stderr)
        return 1
    hit = scan_final(json_bytes, md_bytes)
    if hit:
        sys.stderr.write(hit)
        print("data guard reported hits in the package; nothing written", file=sys.stderr)
        return 1
    # Both outputs are rendered to bytes above; a half-written pair never stays on disk.
    try:
        write_nofollow(djson, json_bytes)
    except OSError as exc:
        print("cannot write %s without following a symlink: %s; nothing written" % (OUT_JSON, exc), file=sys.stderr)
        return 1
    try:
        write_nofollow(dmd, md_bytes)
    except OSError as exc:
        try:
            os.remove(djson)
            undone = "%s removed" % OUT_JSON
        except OSError as rexc:
            undone = "%s could not be removed (%s); remove it by hand" % (OUT_JSON, type(rexc).__name__)
        print("cannot write %s: %s; %s" % (OUT_MD, exc, undone), file=sys.stderr)
        return 2
    print(djson)
    print(dmd)
    print("Next: git add %s and open a PR with the impact; a reviewer checks the package before merge."
          % os.path.relpath(folder, top).replace(os.sep, "/"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

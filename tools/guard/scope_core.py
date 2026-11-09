"""Scope core: the committed build package and source root, read from git HEAD and validated strictly.

Guard-owned (tools/guard/scope_core.py once the WS8 patch is applied). guard.py and tools/impacts/start.py load
this file by explicit path, never through sys.path. Stdlib only, no repo imports, no side effects at import.

Precondition: the caller has already verified the git state (the guard's git_state_problem(root) is None).
This module runs git, and a planted core.fsmonitor or hook must not get the chance to run.

  source_root_from_head(root, timeout)   (rel_source_root, None) or (None, error)
  read_package(root, active, timeout)    (package_dict, None) or (None, error)

Both read HEAD, never the work tree: a working-copy edit to .ai-framework.json or to a committed package is
ignored. read_package fetches HEAD:.ai-framework.json, the HEAD:impacts tree and
HEAD:impacts/<active>/build-package.json in one `git cat-file --batch` call (core.fsmonitor=false, GIT_* env
stripped, then GIT_NO_LAZY_FETCH=1, requests on stdin, bounded timeout). cat-file applies no textconv, filters, pager or diff drivers.

Deliberate divergence from tools/config/framework_config.py: a missing .ai-framework.json, or one with no
sourceRoot, means no source root (an error here), never the "." default. With "." every repo path, impacts/ and
tools/ included, would count as source.

Any bad entry rejects the whole package. Error strings are neutral findings; the guard adds its own prefix.
"""
import json
import os
import re
import subprocess

GIT_TIMEOUT = 3
MAX_BLOB = 1024 * 1024
MAX_ENTRIES = 2000
CONFIG = ".ai-framework.json"
CONFIG_KEYS = ("startingPoint", "sourceRoot", "impactChecks")
ACTIVE_RE = re.compile(r"^([A-Z][A-Z0-9]*-[0-9]+)-([a-z0-9]+(?:-[a-z0-9]+)*)$")
CRITERION_RE = re.compile(r"^(?:AC|EC)-[0-9]+$")
GLOB_CHARS = set("*?[]{}")
# Never scope: the framework's own files. Compared lowercased, as the guard's always_blocked_writes is.
RESERVED_PREFIXES = ("impacts/", "tools/", "framework/", ".claude/", ".github/", "ai-context/")
RESERVED_EXACT = (".ai-framework.json",)
RESERVED_PARTS = (".git",)
RESERVED_NAMES = ("codeowners",)
NO_SOURCE_ROOT = "no source root: %s at HEAD %s; scoped writes need a committed sourceRoot"


def _bad_char(text):
    """True when text holds a C0/C1 control character, DEL, or a bidi embedding/override/isolate."""
    for ch in text:
        o = ord(ch)
        if o < 32 or 127 <= o <= 159 or 0x202A <= o <= 0x202E or 0x2066 <= o <= 0x2069:
            return True
    return False


# ---- git ----

def _git_env():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_NO_LAZY_FETCH"] = "1"  # a partial clone must never fetch a missing object from a remote
    return env


def _cat_file(root, specs, timeout):
    """{spec: (type, bytes)} with None for a missing object, or raises RuntimeError with a finding."""
    cmd = ["git", "-C", root, "-c", "core.fsmonitor=false", "cat-file", "--batch"]
    data = "".join(s + "\n" for s in specs).encode("utf-8")
    try:
        p = subprocess.run(cmd, input=data, capture_output=True, timeout=timeout, env=_git_env())
    except subprocess.TimeoutExpired:
        raise RuntimeError("git cat-file timed out reading HEAD; failing closed")
    except OSError as exc:
        raise RuntimeError("git could not run (%s); failing closed" % type(exc).__name__)
    if p.returncode != 0:
        raise RuntimeError("git cat-file failed reading HEAD (exit %d); failing closed" % p.returncode)
    out, pos, result = p.stdout, 0, {}
    for spec in specs:
        nl = out.find(b"\n", pos)
        if nl < 0:
            raise RuntimeError("git cat-file output ended early; failing closed")
        header = out[pos:nl].decode("utf-8", errors="replace")
        pos = nl + 1
        if header.endswith(" missing") or header.endswith(" ambiguous"):
            result[spec] = None
            continue
        parts = header.split(" ")
        if len(parts) != 3 or not parts[2].isdigit():
            raise RuntimeError("git cat-file header not understood; failing closed")
        size = int(parts[2])
        if size > MAX_BLOB:
            raise RuntimeError("%s is larger than %d bytes" % (spec, MAX_BLOB))
        body = out[pos:pos + size]
        if len(body) != size or out[pos + size:pos + size + 1] != b"\n":
            raise RuntimeError("git cat-file output ended early; failing closed")
        pos += size + 1
        result[spec] = (parts[1], body, len(parts[0]) // 2)
    return result


def _tree_names(body, hash_len):
    """Names of the subtree entries in a raw git tree object."""
    names, pos = [], 0
    while pos < len(body):
        nul = body.find(b"\0", pos)
        if nul < 0:
            raise RuntimeError("HEAD:impacts tree not understood; failing closed")
        mode, _, name = body[pos:nul].partition(b" ")
        if mode in (b"40000", b"040000"):
            names.append(name.decode("utf-8", errors="replace"))
        pos = nul + 1 + hash_len
    return names


# ---- JSON ----

def _no_dup_pairs(pairs):
    obj = {}
    for k, v in pairs:
        if k in obj:
            raise ValueError("duplicate key %s" % json.dumps(k))
        obj[k] = v
    return obj


def _json(name, body):
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None, "%s at HEAD is not UTF-8" % name
    try:
        return json.loads(text, object_pairs_hook=_no_dup_pairs), None
    except ValueError as exc:
        if str(exc).startswith("duplicate key"):
            return None, "%s at HEAD: %s" % (name, exc)
        return None, "%s at HEAD is not valid JSON" % name
    except RecursionError:
        return None, "%s at HEAD is nested too deeply" % name


def _show(value):
    try:
        text = json.dumps(value, ensure_ascii=True)
    except (TypeError, ValueError, RecursionError):
        text = type(value).__name__
    return text if len(text) <= 200 else text[:200] + "..."


# ---- paths ----

def _resolved(top, rel):
    """rel resolved like the guard's rel_path: realpath, relative to top, forward slashes."""
    try:
        return os.path.relpath(os.path.realpath(os.path.join(top, rel)), top).replace("\\", "/")
    except ValueError:
        return None


def _inside(top, path):
    """True when path is top or below it. On Windows, paths on different drives are never inside."""
    try:
        return os.path.commonpath([top, path]) == top
    except ValueError:
        return False


def _parse_config(top, entry):
    """(source_root, None) or (None, error) from the cat-file result for HEAD:.ai-framework.json."""
    if entry is None:
        return None, NO_SOURCE_ROOT % (CONFIG, "is missing")
    kind, body, _ = entry
    if kind != "blob":
        return None, "%s at HEAD is not a file" % CONFIG
    data, err = _json(CONFIG, body)
    if err:
        return None, err
    if not isinstance(data, dict):
        return None, "%s at HEAD is not a JSON object" % CONFIG
    unknown = sorted(k for k in data if k not in CONFIG_KEYS)
    if unknown:
        return None, "%s at HEAD: unknown key %s" % (CONFIG, ", ".join(_show(k) for k in unknown))
    if "sourceRoot" not in data:
        return None, NO_SOURCE_ROOT % (CONFIG, "has no sourceRoot")
    src = data["sourceRoot"]
    if not isinstance(src, str) or not src.strip():
        return None, "%s at HEAD: sourceRoot %s is not a non-empty string" % (CONFIG, _show(src))
    if _bad_char(src):
        return None, "%s at HEAD: sourceRoot %s contains a control character" % (CONFIG, _show(src))
    if "\\" in src:
        return None, "%s at HEAD: sourceRoot %s contains a backslash" % (CONFIG, _show(src))
    if src.startswith("/") or os.path.isabs(src):
        return None, "%s at HEAD: sourceRoot %s is absolute" % (CONFIG, _show(src))
    if ".." in src.split("/"):
        return None, "%s at HEAD: sourceRoot %s contains '..'" % (CONFIG, _show(src))
    real = os.path.realpath(os.path.join(top, src))
    if not _inside(top, real):
        return None, "%s at HEAD: sourceRoot %s resolves outside the repo" % (CONFIG, _show(src))
    if not os.path.isdir(real):
        return None, "%s at HEAD: sourceRoot %s is not a directory" % (CONFIG, _show(src))
    return os.path.relpath(real, top).replace("\\", "/"), None


def _entry_problem(top, src, where, item):
    """None when item is an exact, canonical, repo-relative file path under src and outside the reserved paths."""
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
    if _resolved(top, item) != item:
        return "%s: entry %s resolves through a symlink" % (where, _show(item))
    return None


def _validate(top, src, active, pkg):
    """None when the package is valid, else the first finding."""
    if not isinstance(pkg, dict):
        return "build-package.json at HEAD is not a JSON object"
    version = pkg.get("schemaVersion")
    if type(version) is not int or version != 1:  # true and 1.0 compare equal to 1; neither is accepted
        return "build-package.json: schemaVersion %s is not 1" % _show(pkg.get("schemaVersion"))
    story, slug = ACTIVE_RE.fullmatch(active).groups()
    if pkg.get("storyId") != story:
        return "build-package.json: storyId %s does not match the active story %s" % (_show(pkg.get("storyId")), story)
    if pkg.get("slug") != slug:
        return "build-package.json: slug %s does not match the active story's slug %s" % (_show(pkg.get("slug")), slug)
    scope = pkg.get("scope")
    if not isinstance(scope, dict):
        return "build-package.json: scope is not an object"
    lists = {}
    for key in ("modify", "create", "tests"):
        value = scope.get(key)
        if not isinstance(value, list):
            return "build-package.json: scope.%s is not a list" % key
        lists[key] = value
    criteria = pkg.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        # Empty criteria[] is treated as invalid: tests-first would otherwise pass vacuously (owner decision).
        return "build-package.json: criteria is not a non-empty list"
    total = sum(len(v) for v in lists.values()) + len(criteria)
    if total > MAX_ENTRIES:
        return "build-package.json: %d scope and criteria entries is more than %d" % (total, MAX_ENTRIES)
    for key in ("modify", "tests"):
        where = "scope." + key
        seen = set()
        for item in lists[key]:
            problem = _entry_problem(top, src, where, item)
            if problem:
                return "build-package.json: " + problem
            if item in seen:
                return "build-package.json: %s: duplicate entry %s" % (where, _show(item))
            seen.add(item)
    seen = set()
    for item in lists["create"]:
        if not isinstance(item, dict):
            return "build-package.json: scope.create: entry %s is not an object with api, type and path" % _show(item)
        for field in ("api", "type", "path"):
            if not isinstance(item.get(field), str) or not item.get(field):
                return "build-package.json: scope.create: entry %s has no string %s" % (_show(item), field)
        problem = _entry_problem(top, src, "scope.create", item["path"])
        if problem:
            return "build-package.json: " + problem
        if item["path"] in seen:
            return "build-package.json: scope.create: duplicate entry %s" % _show(item["path"])
        seen.add(item["path"])
    # The same rule as trace_core.criteria_problem; a drift test keeps the two equal.
    ids = set()
    for c in criteria:
        if not isinstance(c, dict):
            return "build-package.json: criterion %s is not an object" % _show(c)
        cid = c.get("id")
        if not isinstance(cid, str) or not CRITERION_RE.fullmatch(cid):
            return "build-package.json: criterion id %s is not AC-<n> or EC-<n>" % _show(cid)
        if cid in ids:
            return "build-package.json: duplicate criterion id %s" % cid
        ids.add(cid)
    return None


# ---- public ----

def source_root_from_head(root, timeout=GIT_TIMEOUT):
    """(source_root, None): sourceRoot from HEAD:.ai-framework.json, realpath'd, relative to root ("." for the
    whole repo). (None, error) when the config is missing, has no sourceRoot, or is invalid. Never raises."""
    try:
        return _source_root_from_head(root, timeout)
    except Exception as exc:  # fail closed with a finding, never an exception into the guard
        return None, "source_root_from_head failed: %s" % type(exc).__name__


def read_package(root, active, timeout=GIT_TIMEOUT):
    """(package, None) for the valid package committed at HEAD:impacts/<active>/build-package.json, else
    (None, error). active is "<storyId>-<slug>"; exactly one impacts/<storyId>-* folder may exist at HEAD.
    Never raises."""
    try:
        return _read_package(root, active, timeout)
    except Exception as exc:  # fail closed with a finding, never an exception into the guard
        return None, "read_package failed: %s" % type(exc).__name__


def _source_root_from_head(root, timeout):
    top = os.path.realpath(root)
    try:
        got = _cat_file(top, ["HEAD:" + CONFIG], timeout)
    except RuntimeError as exc:
        return None, str(exc)
    return _parse_config(top, got["HEAD:" + CONFIG])


def _read_package(root, active, timeout):
    if not isinstance(active, str) or not ACTIVE_RE.fullmatch(active):
        return None, "active story %s is not <storyId>-<slug>" % _show(active)
    top = os.path.realpath(root)
    story = ACTIVE_RE.fullmatch(active).group(1)
    cfg_spec, tree_spec = "HEAD:" + CONFIG, "HEAD:impacts"
    pkg_path = "impacts/%s/build-package.json" % active
    pkg_spec = "HEAD:" + pkg_path
    try:
        got = _cat_file(top, [cfg_spec, tree_spec, pkg_spec], timeout)
    except RuntimeError as exc:
        return None, str(exc)
    entry = got[pkg_spec]
    if entry is None:
        return None, "%s is not committed at HEAD; the package is read from a commit, never the work tree" % pkg_path
    if entry[0] != "blob":
        return None, "%s at HEAD is not a file" % pkg_path
    src, err = _parse_config(top, got[cfg_spec])
    if err:
        return None, err
    tree = got[tree_spec]
    if tree is None or tree[0] != "tree":
        return None, "impacts/ at HEAD is not a folder"
    try:
        matches = [n for n in _tree_names(tree[1], tree[2]) if n.startswith(story + "-")]
    except RuntimeError as exc:
        return None, str(exc)
    if len(matches) > 1:
        return None, "two or more impacts folders at HEAD match %s: %s" % (story, ", ".join(sorted(matches)))
    pkg, err = _json(pkg_path, entry[1])
    if err:
        return None, err
    problem = _validate(top, src, active, pkg)
    if problem:
        return None, problem
    return pkg, None

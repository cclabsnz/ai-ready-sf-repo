#!/usr/bin/env python3
"""Onboard a repo from one of two starting points.

Usage:
  onboard.py --starting-point existing --owner-role <role> [--source-root <dir>] [--write-config]
             [--replace] [--root <repo>]
  onboard.py --starting-point greenfield [--source-root <dir>] [--write-config] [--replace]
             [--root <repo>]

existing    Builds the index of the source root into <root>/index, prints the inventory as
            markdown (read from index/inventory.json), and writes knowledge stubs to
            <root>/framework/knowledge/stubs/ with owner set to --owner-role (required).
greenfield  Creates the SFDX layout under the source root where it is absent (sfdx-project.json
            and force-app/main/default/<folder>/.gitkeep), then builds the empty index, which
            replaces <root>/index. It exits 1 with nothing written when the source root already
            holds a codebase: any force-app/main/default entry beyond the skeleton's .gitkeep
            files, or an sfdx-project.json that differs from the one greenfield writes.

--root defaults to . (the repo the data lives in). Code, including build_index.py, comes from
this file's own checkout, never from --root or the cwd.
--source-root defaults to sourceRoot in <root>/.ai-framework.json; a relative path is joined
to --root. It must resolve inside --root.
--write-config writes <root>/.ai-framework.json with startingPoint and sourceRoot, keeping any
impactChecks already there.
--replace overwrites a stub or skeleton file whose content differs from what onboarding
generates. Without it such a file is kept as it is and reported; an identical file is left
untouched either way, so a second run changes nothing.

Writes only <root>/index, <root>/framework/knowledge/stubs/, the skeleton under the source root
and (with --write-config) <root>/.ai-framework.json. A target that resolves outside --root, or
that passes through a symlink, exits 2 before anything is written.
Exit codes: 0 ok, 1 an existing codebase under a greenfield source root or a failed index build,
2 bad usage. Stdlib only. Offline.
"""
import argparse
import json
import os
import re
import subprocess
import sys

CHECKOUT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BUILD = os.path.join(CHECKOUT, "tools", "index", "build_index.py")
sys.path.insert(0, os.path.join(CHECKOUT, "tools", "config"))
import framework_config  # noqa: E402

# Matches demo/org/sfdx-project.json, so the greenfield skeleton and the demo org agree.
SOURCE_API_VERSION = "62.0"
# Five stubs: enough to cover the objects most of the metadata hangs off, few enough that an
# owner can verify each one. Every stub is work for a human; a long list goes unread.
STUB_TOPICS = 5
MAX_LEADS = 10
STUBS_DIR = "framework/knowledge/stubs"
SKELETON_FOLDERS = ("classes", "objects", "lwc", "flows", "permissionsets")
# Edge kinds whose target is always an object. An undotted target of any other kind (an Apex
# class, a flow, a component) is not an object, however many edges point at it.
OBJECT_KINDS = ("fieldOf", "triggerOn", "flowTriggerObject", "objectPermission", "apexObjectRef",
                "validationRuleOf", "recordTypeOf", "flexipageObject")
SAFE_API = re.compile(r"^[A-Za-z0-9_.]+$")
MAX_ROLE = 200


class Refused(Exception):
    """Bad usage or an unsafe target. The CLI prints it on stderr and exits 2."""


def checked(top, path, alias=None):
    """Absolute path of `path` (absolute, or relative to top) under the real path top.
    `alias` is the root as given, so an absolute path spelled through it (macOS /var for
    /private/var) is still recognised. Refused when the path lies outside top or when an
    existing component below top is a symlink."""
    raw = path if os.path.isabs(path) else os.path.join(top, path)
    raw = os.path.abspath(raw)
    rel = None
    for base in (top,) + ((alias,) if alias else ()):
        if os.path.commonpath([base, raw]) == base:
            rel = os.path.relpath(raw, base)
            break
    if rel is None:
        raise Refused("%s resolves outside the root %s" % (path, top))
    cur = top
    for part in rel.split(os.sep):
        if part in ("", "."):
            continue
        cur = os.path.join(cur, part)
        if os.path.islink(cur):
            raise Refused("%s passes through a symlink at %s" % (path, os.path.relpath(cur, top)))
    if os.path.commonpath([top, os.path.realpath(cur)]) != top:
        raise Refused("%s resolves outside the root %s" % (path, top))
    return cur


def resolve_top(root):
    """Real path of the outer root, which itself may sit behind a symlink (e.g. macOS /var)."""
    top = os.path.realpath(root)
    if not os.path.isdir(top):
        raise Refused("--root %s is not a directory" % root)
    if os.path.islink(os.path.join(top, ".ai-framework.json")):
        raise Refused(".ai-framework.json is a symlink")
    return top


def show(top, path):
    rel = os.path.relpath(path, top).replace(os.sep, "/")
    return rel


def write_text(top, path, content, replace):
    """Write content to path (already checked). Returns created, unchanged, kept or replaced."""
    path = checked(top, path)
    data = content.encode("utf-8")
    if os.path.lexists(path):
        if not os.path.isfile(path):
            raise Refused("%s exists and is not a regular file" % show(top, path))
        with open(path, "rb") as fh:
            if fh.read() == data:
                return "unchanged"
        if not replace:
            return "kept"
        status = "replaced"
    else:
        status = "created"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
    return status


def build_index(source, index_dir):
    """Run the checkout's build_index.py. Returns (exit code, its stdout line or stderr)."""
    p = subprocess.run([sys.executable, BUILD, "--root", source, "--out", index_dir],
                       capture_output=True, text=True)
    return p.returncode, (p.stdout if p.returncode == 0 else p.stderr).strip()


def read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---- greenfield --------------------------------------------------------------------------------

def skeleton_files():
    """[(path relative to the source root, content)] of the greenfield skeleton."""
    files = [("sfdx-project.json", json.dumps(
        {"packageDirectories": [{"path": "force-app", "default": True}],
         "sourceApiVersion": SOURCE_API_VERSION}, indent=2) + "\n")]
    files += [("force-app/main/default/%s/.gitkeep" % d, "") for d in SKELETON_FOLDERS]
    return files


def existing_codebase(source, files):
    """Sorted paths (relative to the source root) showing the source root already holds a
    codebase: any entry under force-app/main/default other than the skeleton's .gitkeep files
    and folders, and an sfdx-project.json that differs from the one greenfield writes."""
    found = []
    project = os.path.join(source, "sfdx-project.json")
    if os.path.lexists(project):
        expected = dict(files)["sfdx-project.json"].encode("utf-8")
        same = False
        if os.path.isfile(project) and not os.path.islink(project):
            with open(project, "rb") as fh:
                same = fh.read() == expected
        if not same:
            found.append("sfdx-project.json")
    allowed = {rel for rel, _ in files if rel.endswith(".gitkeep")}
    allowed_dirs = {os.path.dirname(rel) for rel in allowed}
    base = os.path.join(source, "force-app", "main", "default")
    for dirpath, dirs, names in os.walk(base):
        for name in dirs + names:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, source).replace(os.sep, "/")
            ok_dir = rel in allowed_dirs and os.path.isdir(path) and not os.path.islink(path)
            ok_file = rel in allowed and os.path.isfile(path) and not os.path.islink(path)
            if not (ok_dir or ok_file):
                found.append(rel)
    return sorted(found)


# ---- stubs -------------------------------------------------------------------------------------

def objects_of(idx):
    """Every object in the index: CustomObject nodes and undotted targets of object-only kinds."""
    objs = {k for k, v in idx["nodes"].items() if v.get("type") == "CustomObject"}
    objs |= {e["to"] for e in idx["edges"] if e["kind"] in OBJECT_KINDS and "." not in e["to"]}
    return {o for o in objs if SAFE_API.match(o)}


def stub_topics(idx):
    """[(object, [lead api, ...])] for the STUB_TOPICS objects with the most inbound edges.
    An edge counts toward an object when its `to` is the object or one of its fields
    (Object.Field). Ties break by name. Leads are the distinct edge sources, sorted, at most
    MAX_LEADS, and only names of indexed components."""
    objs = objects_of(idx)
    counts, sources = {}, {}
    for e in idx["edges"]:
        target = e["to"].split(".", 1)[0]
        if target in objs:
            counts[target] = counts.get(target, 0) + 1
            if e["from"] in idx["nodes"] and SAFE_API.match(e["from"]):
                sources.setdefault(target, set()).add(e["from"])
    ranked = sorted(counts, key=lambda o: (-counts[o], o))[:STUB_TOPICS]
    return [(o, sorted(sources.get(o, ()))[:MAX_LEADS]) for o in ranked]


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "object"


def stub_text(topic, owner, leads):
    # owner is a double-quoted YAML string (" and \ escaped; control characters are refused
    # earlier), so a role such as `Lead: x` or `#x` survives a YAML reader and lint.py's split.
    quoted = '"%s"' % owner.replace("\\", "\\\\").replace('"', '\\"')
    lines = ["---", "topic: %s" % topic, "owner: %s" % quoted, 'last_verified: ""',
             'verified_by: ""', "---", "# %s" % topic, "", "Leads to verify:"]
    lines += ["- %s" % api for api in leads]
    return "\n".join(lines) + "\n"


def stub_files(topics):
    """[(file name, object, leads)], names unique even if two objects share a slug."""
    out, used = [], set()
    for obj, leads in topics:
        base = slug(obj)
        name, n = base + ".md", 2
        while name in used:
            name, n = "%s-%d.md" % (base, n), n + 1
        used.add(name)
        out.append((name, obj, leads))
    return out


# ---- output ------------------------------------------------------------------------------------

def table(header, rows):
    if not rows:
        return ["Zero entries in inventory.json."]
    out = ["| %s | %s |" % header, "|---|---|"]
    out += ["| %s | %s |" % (k, v) for k, v in rows]
    return out


def inventory_lines(inv):
    by_version = inv.get("apexByApiVersion", {})
    by_sharing = inv.get("apexBySharing", {})
    aura_lwc = inv.get("auraVsLwc", {})
    lines = ["## Inventory (from index/inventory.json)", "", "### Apex by API version", ""]
    lines += table(("API version", "Classes and triggers"), sorted(by_version.items()))
    lines += ["", "### Apex by sharing", ""]
    lines += table(("Sharing", "Classes and triggers"), sorted(by_sharing.items()))
    lines += ["", "### Aura vs LWC", ""]
    lines += table(("Framework", "Bundles"),
                   [("Aura", aura_lwc.get("aura", 0)), ("LWC", aura_lwc.get("lwc", 0))])
    return lines


NOTE = {"created": "", "unchanged": "", "replaced": " (replaced)",
        "kept": " (kept: the file on disk differs; --replace overwrites it)"}


# ---- main --------------------------------------------------------------------------------------

def parse(argv):
    ap = argparse.ArgumentParser(description="Onboard a repo: existing or greenfield.")
    ap.add_argument("--starting-point", required=True, choices=framework_config.STARTING_POINTS)
    ap.add_argument("--source-root", default=None)
    ap.add_argument("--owner-role", default=None)
    ap.add_argument("--write-config", action="store_true")
    ap.add_argument("--replace", action="store_true")
    ap.add_argument("--root", default=".")
    return ap.parse_args(argv)


def owner_role(value):
    role = (value or "").strip()
    if not role:
        raise Refused("--owner-role is required for the existing starting point")
    if len(role) > MAX_ROLE or any(ord(c) < 32 or ord(c) == 127 for c in role):
        raise Refused("--owner-role holds a control character or exceeds %d characters" % MAX_ROLE)
    return role


def run(args):
    top = resolve_top(args.root)
    existing = args.starting_point == "existing"
    role = owner_role(args.owner_role) if existing else None
    config = None
    if args.source_root is None or args.write_config:
        try:
            config = framework_config.load(top)
        except ValueError as exc:
            raise Refused(str(exc))
    source_arg = args.source_root if args.source_root is not None else config["sourceRoot"]
    source = checked(top, source_arg, os.path.abspath(args.root))
    if existing and not os.path.isdir(source):
        raise Refused("source root %s is not a directory" % source_arg)
    if os.path.lexists(source) and not os.path.isdir(source):
        raise Refused("source root %s is not a directory" % source_arg)
    index_dir = checked(top, "index")
    for name in ("metadata.json", "inventory.json"):  # build_index.py opens these for writing
        target = checked(top, os.path.join(index_dir, name))
        if os.path.lexists(target) and not os.path.isfile(target):
            raise Refused("%s exists and is not a regular file" % show(top, target))
    stubs_dir = checked(top, STUBS_DIR) if existing else None
    config_path = checked(top, framework_config.FILENAME) if args.write_config else None
    source_rel = show(top, source)

    out = ["# Onboarding: %s" % args.starting_point, "", "Source root: `%s`" % source_rel, ""]

    if not existing:
        files = skeleton_files()
        found = existing_codebase(source, files)
        if found:
            print("greenfield found an existing codebase under %s: %s. Nothing was written; "
                  "the existing starting point covers this source root."
                  % (source_rel, ", ".join(found[:5]) + (" and more" if len(found) > 5 else "")),
                  file=sys.stderr)
            return 1
        out += ["## Greenfield layout", ""]
        label = {"created": "created", "unchanged": "present", "replaced": "replaced",
                 "kept": "kept: differs from the generated file; --replace overwrites it"}
        for rel, content in files:
            status = write_text(top, os.path.join(source, rel), content, args.replace)
            out.append("- `%s`: %s" % (show(top, os.path.join(source, rel)), label[status]))
        out.append("")

    code, message = build_index(source, index_dir)
    if code != 0:
        print("\n".join(out))
        print("build_index.py failed: %s" % message, file=sys.stderr)
        return 1
    out += ["Index: `%s` (build_index.py: %s)" % (show(top, index_dir), message), ""]
    if not existing:
        out += ["Greenfield replaced `%s/` with the index of `%s`; "
                "`python3 tools/index/build_index.py --from-config` rebuilds it from the "
                "configured source root." % (show(top, index_dir), source_rel), ""]

    if existing:
        inv = read_json(os.path.join(index_dir, "inventory.json")).get("inventory", {})
        out += inventory_lines(inv)
        idx = read_json(os.path.join(index_dir, "metadata.json"))
        out += ["", "## Knowledge stubs (%s/)" % STUBS_DIR, "",
                "Owner role: %s. Topics: the objects with the most inbound edges in the index; "
                "each stub names leads to verify, not facts." % role, ""]
        stubs = stub_files(stub_topics(idx))
        if not stubs:
            out.append("Zero objects in the index; no stubs written.")
        for name, obj, leads in stubs:
            status = write_text(top, os.path.join(stubs_dir, name), stub_text(obj, role, leads),
                                args.replace)
            out.append("- `%s/%s`: %s%s" % (STUBS_DIR, name, obj, NOTE[status]))
        out.append("")

    if args.write_config:
        new = {"startingPoint": args.starting_point, "sourceRoot": source_rel}
        if os.path.isfile(config_path):
            raw = read_json(config_path)
            if "impactChecks" in raw:
                new["impactChecks"] = raw["impactChecks"]
        status = write_text(top, config_path, json.dumps(new) + "\n", True)
        out += ["Config: `%s` %s" % (framework_config.FILENAME, status), ""]

    if existing:
        out.append("Rule baseline: arrives with WS8 (check_rules.py)")
    else:
        out.append("no baseline: rules are strict from the first commit")
    print("\n".join(out))
    return 0


def main(argv=None):
    try:
        args = parse(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    try:
        return run(args)
    except Refused as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())

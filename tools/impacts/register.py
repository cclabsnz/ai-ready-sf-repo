#!/usr/bin/env python3
"""Read committed impact records and answer overlaps, scope and view.

Usage:
  register.py overlaps <impact.json> [--root .]
  register.py scope <storyId> [--root .]
  register.py view [--root .]

The register is every <root>/impacts/*/impact.json that is a valid promoted record
whose status is not shipped. Files that fail JSON parsing or validation are listed
under "invalid" and never stop the run. Evidence files are not checked here.

Prints JSON on stdout (indent 2, sorted keys).
Exit codes: 0 ok, 2 bad usage, 4 nothing on record (scope only).
Stdlib only. Data comes from --root; code never does.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from validate import validate  # noqa: E402

CONFLICT_TYPES = ("new", "modify", "delete")

# `git -C <root>` reads the config of whatever repo encloses --root, which may be one planted
# under ai-context/. These overrides neutralise the config keys known to run a command.
# core.hooksPath points at a folder that does not exist, so no hook can be found.
_NO_HOOKS = os.path.join(os.path.abspath(os.sep), "nonexistent-ai-framework-hooks")
GIT_SAFE = ["--no-pager",
            "-c", "core.fsmonitor=false",
            "-c", "core.hooksPath=" + _NO_HOOKS,
            "-c", "core.pager=cat",
            "-c", "core.sshCommand=",
            "-c", "diff.external=",
            "-c", "core.editor=true"]


def _git_env():
    env = dict(os.environ)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def _git(root, args):
    """Run one read-only git command against root; "" on any failure."""
    try:
        out = subprocess.run(["git", "-C", root] + GIT_SAFE + args, capture_output=True,
                             text=True, timeout=30, env=_git_env())
    except (OSError, subprocess.SubprocessError):
        return ""
    if out.returncode != 0:
        return ""
    return out.stdout.strip()


def _commit(root, path):
    return _git(root, ["log", "-1", "--format=%h", "--", path]) or "uncommitted"


def register_commit(root):
    return _git(root, ["rev-parse", "--short", "HEAD"]) or "unknown"


def load_register(root):
    """Return {"impacts": [doc...], "invalid": [{"path", "errors"}]}.

    impacts holds valid promoted docs whose status is not shipped, each with the
    private keys _dir (repo-relative folder) and _commit.
    """
    impacts, invalid = [], []
    pattern = os.path.join(root, "impacts", "*", "impact.json")
    for full in sorted(glob.glob(pattern)):
        rel = os.path.relpath(full, root).replace(os.sep, "/")
        try:
            with open(full, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError, RecursionError, MemoryError) as exc:
            # RecursionError/MemoryError: deeply nested JSON; listed, never fatal.
            invalid.append({"path": rel, "errors": ["cannot read JSON: %s: %s"
                                                    % (type(exc).__name__, exc)]})
            continue
        errs = validate(doc, "promoted", root)
        if errs:
            invalid.append({"path": rel, "errors": errs})
            continue
        if doc.get("status") == "shipped":
            continue
        doc["_dir"] = os.path.dirname(rel)
        doc["_commit"] = _commit(root, rel)
        impacts.append(doc)
    return {"impacts": impacts, "invalid": invalid}


def _entry(doc, comp):
    return {"storyId": doc.get("storyId"), "squad": doc.get("squad"),
            "status": doc.get("status"), "changeType": comp.get("changeType"),
            "type": comp.get("type"), "commit": doc.get("_commit", "uncommitted")}


def _components(doc):
    comps = doc.get("components") if isinstance(doc, dict) else None
    if not isinstance(comps, list):
        return []
    return [c for c in comps if isinstance(c, dict) and isinstance(c.get("api"), str)]


def component_map(impacts):
    """api -> entries {storyId, squad, status, changeType, type, commit}, sorted by storyId."""
    result = {}
    for doc in impacts:
        for c in _components(doc):
            result.setdefault(c["api"], []).append(_entry(doc, c))
    for api in result:
        result[api].sort(key=lambda e: (str(e["storyId"]), str(e["changeType"])))
    return dict(sorted(result.items()))


def overlaps(impact, impacts):
    """Components of impact that other register stories also touch.

    kind is conflict when the impact's own changeType and a story's changeType are both
    in new/modify/delete (any such story makes the component a conflict), else watch.
    """
    cmap = component_map(impacts)
    own_id = impact.get("storyId") if isinstance(impact, dict) else None
    found = []
    for c in _components(impact):
        others = [e for e in cmap.get(c["api"], []) if e["storyId"] != own_id]
        if not others:
            continue
        conflict = c.get("changeType") in CONFLICT_TYPES and any(
            e["changeType"] in CONFLICT_TYPES for e in others)
        found.append({"api": c["api"], "type": c.get("type"),
                      "kind": "conflict" if conflict else "watch", "stories": others})
    found.sort(key=lambda o: (0 if o["kind"] == "conflict" else 1, o["api"]))
    return found


def scope(story_id, impacts):
    """{storyId, squad, status, components: [api...]} or None when not on record."""
    for doc in impacts:
        if doc.get("storyId") == story_id:
            return {"storyId": story_id, "squad": doc.get("squad"),
                    "status": doc.get("status"),
                    "components": [c["api"] for c in _components(doc)]}
    return None


def _out(obj):
    print(json.dumps(obj, indent=2, sort_keys=True))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Impact register: overlaps, scope, view.")
    sub = ap.add_subparsers(dest="cmd")
    p_ov = sub.add_parser("overlaps")
    p_ov.add_argument("file")
    p_sc = sub.add_parser("scope")
    p_sc.add_argument("story_id")
    p_vw = sub.add_parser("view")
    for p in (p_ov, p_sc, p_vw):
        p.add_argument("--root", default=ROOT)
    try:
        args = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if not args.cmd:
        print("usage: register.py overlaps|scope|view", file=sys.stderr)
        return 2

    if args.cmd == "overlaps":
        try:
            with open(args.file, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            print("cannot read JSON from %s: %s" % (args.file, exc), file=sys.stderr)
            return 2
        if not isinstance(doc, dict):
            print("%s: record is not a JSON object" % args.file, file=sys.stderr)
            return 2
        reg = load_register(args.root)
        _out({"overlaps": overlaps(doc, reg["impacts"]), "invalid": reg["invalid"],
              "registerCommit": register_commit(args.root)})
        return 0

    reg = load_register(args.root)
    if args.cmd == "scope":
        found = scope(args.story_id, reg["impacts"])
        if found is None:
            _out({"storyId": args.story_id, "found": False, "invalid": reg["invalid"]})
            return 4
        _out(found)
        return 0

    _out({"components": component_map(reg["impacts"]), "invalid": reg["invalid"]})
    return 0


if __name__ == "__main__":
    sys.exit(main())

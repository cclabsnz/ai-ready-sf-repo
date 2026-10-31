#!/usr/bin/env python3
"""Deterministic report writer for story-impact. stdlib only.

  python3 write_report.py --id DEMO-201 --slug premium-escalation \
      --classified classified.json --meta meta.json [--root .]

classified.json: list of {api, layer, type, ownership, changeType, impact, scale, hop, evidence,
confidence, note[, path]}
meta.json: {squad, hops, model, assistantVersion, decisions: [{text, ownerRole}], unknowns: [str]
[, designOption, recommendedBy]}

designOption ("OPT-<n>", the solution-design option this record assesses) passes through to the
top level of impact.json, and recommendedBy ("assistant") to its provenance. Each is written only
when meta.json carries it, so a record sized without a design is unchanged. impact.md names the
assessed option in its header when there is one.

Writes ai-context/<id>-<slug>/impact.json (a draft record) and impact.md. The record is validated
as a draft, with evidence checked against --root, before anything is written; on errors nothing is
written and the exit code is 1. Exit 2 is bad usage, including an output folder that resolves
(realpath) outside <root>/ai-context/ or outside this checkout's ai-context/ (located from
__file__). In normal use --root is . and the two are the same folder.

Code comes from this checkout (located from __file__); data comes from --root.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# scripts -> story-impact -> skills -> framework|.claude|.github -> repo root
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
sys.path.insert(0, os.path.join(REPO, "tools", "impacts"))

from validate import STORY_RE, SLUG_RE, COMP_KEYS, validate  # noqa: E402
from register import load_register, overlaps, register_commit  # noqa: E402
from safe_write import checkout_out_dir, write_nofollow  # noqa: E402

QUERY = os.path.join(REPO, "tools", "index", "query.py")


def stamp(root):
    try:
        out = subprocess.check_output([sys.executable, QUERY, "stamp", "--root", root,
                                       "--index", os.path.join(root, "index")],
                                      stderr=subprocess.DEVNULL)
        st = json.loads(out)
        if isinstance(st, dict) and isinstance(st.get("commit"), str) and st["commit"].strip():
            return st
        return {"commit": "unknown", "error": "stamp has no commit"}
    except Exception as e:
        return {"commit": "unknown", "error": str(e)}


def framework_version(root):
    try:
        with open(os.path.join(root, "VERSION"), encoding="utf-8") as fh:
            v = fh.read().strip()
        return v or "unknown"
    except OSError:
        return "unknown"


def to_hop(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def to_component(r):
    ev = r.get("evidence")
    if "path" in r:
        path = r["path"]
    elif isinstance(ev, str) and ":" in ev:
        path = ev.rpartition(":")[0] or None
    else:
        path = None
    c = {k: r.get(k) for k in COMP_KEYS}
    c["hop"] = to_hop(r.get("hop"))
    c["path"] = path
    return c


def out_dir_for(root, story, slug):
    """Return <root>/ai-context/<story>-<slug>, or None when it is refused.

    The check is safe_write.checkout_out_dir (tools/impacts/safe_write.py): refused when
    <root>/ai-context or this checkout's ai-context is a symlink, or when the folder resolves
    (realpath) outside <root>/ai-context/ or outside this checkout's ai-context/.
    """
    try:
        return checkout_out_dir(root, "%s-%s" % (story, slug))
    except ValueError:
        return None


def cell(v):
    """One markdown table cell: backslashes escaped first, then pipes; newlines become spaces."""
    return "" if v is None else str(v).replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def overlap_lines(found, invalid, reg_commit):
    lines = ["", "## Overlaps with other stories", ""]
    if found:
        lines += ["| Component | Kind | Other story | Squad | Status | Their change | Register commit |",
                  "|---|---|---|---|---|---|---|"]
        for o in found:
            for s in o["stories"]:
                lines.append("| `%s` | %s | %s | %s | %s | %s | `%s` |" % (
                    o["api"], o["kind"], cell(s.get("storyId")), cell(s.get("squad")),
                    cell(s.get("status")), cell(s.get("changeType")), cell(s.get("commit"))))
    else:
        lines.append("- none in the register at `%s`" % reg_commit)
    if invalid:
        lines += ["", "### Register files that failed validation", ""]
        for item in invalid:
            lines.append("- `%s`: %s" % (item["path"], "; ".join(cell(e) for e in item["errors"])))
    return lines


def render_md(doc, rows, st, found, invalid, reg_commit):
    by_impact = {}
    for r in rows:
        by_impact[r["impact"]] = by_impact.get(r["impact"], 0) + 1
    lines = ["# Impact: %s %s" % (doc["storyId"], doc["slug"]), "",
             "Index commit `%s`, index version %s, built %s." % (
                 str(st.get("commit", "unknown"))[:12], st.get("indexVersion", "?"),
                 st.get("builtAt", "?")), ""]
    if "designOption" in doc:
        rec = doc["provenance"].get("recommendedBy")
        lines += ["Assessed option: %s from design.json%s. A named owner confirms the option at "
                  "promotion." % (cell(doc["designOption"]),
                                  " (recommended by: %s)" % cell(rec) if rec else ""), ""]
    lines += ["| Impact | Count |", "|---|---|"]
    lines += ["| %s | %s |" % (k, v) for k, v in sorted(by_impact.items())]
    lines += ["", "| Component | Layer | Type | Ownership | Change | Impact | Scale | Hop | Evidence | Confidence |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| `%s` | %s | %s | %s | %s | %s | %s | %s | `%s` | %s |" % (
            r["api"], cell(r.get("layer")), cell(r.get("type")), cell(r.get("ownership")),
            cell(r.get("changeType")), r["impact"], cell(r.get("scale")), cell(r.get("hop")),
            cell(r.get("evidence")), r["confidence"]))
    lines += overlap_lines(found, invalid, reg_commit)
    unver = [r for r in rows if r["confidence"] == "Unverifiable"]
    lines += ["", "## Unverifiable", ""] + (
        ["- `%s`: %s" % (r["api"], cell(r.get("note"))) for r in unver] or ["- none"])
    lines += ["", "## Unknowns", ""] + (["- %s" % cell(u) for u in doc["unknowns"]] or ["- none"])
    lines += ["", "## Decisions required", ""] + (
        ["- (%s): %s" % (cell(d["ownerRole"]), cell(d["text"])) for d in doc["decisions"]]
        or ["- none"])
    lines += ["", "_Generated by write_report.py; the model adds framing, triage reasons and "
                  "manual-check findings above the tables. The Overlaps section comes from the "
                  "register and is reported as written._"]
    return "\n".join(lines) + "\n"


def usage(msg):
    print(msg, file=sys.stderr)
    return 2


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write impact.json and impact.md for one story.")
    ap.add_argument("--id", required=True)
    ap.add_argument("--slug", required=True)
    ap.add_argument("--classified", required=True)
    ap.add_argument("--meta", required=True)
    ap.add_argument("--root", default=".")
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    if not STORY_RE.match(a.id):
        return usage("--id '%s' does not match %s" % (a.id, STORY_RE.pattern))
    if not SLUG_RE.match(a.slug):
        return usage("--slug '%s' does not match %s" % (a.slug, SLUG_RE.pattern))
    out_dir = out_dir_for(a.root, a.id, a.slug)
    if out_dir is None:
        return usage("output folder for %s-%s resolves outside <root>/ai-context/ or outside the "
                     "checkout's ai-context/; nothing written" % (a.id, a.slug))
    try:
        with open(a.classified, encoding="utf-8") as fh:
            rows = json.load(fh)
        with open(a.meta, encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError) as exc:
        return usage("cannot read input JSON: %s" % exc)
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        return usage("--classified is not a list of objects")
    if not isinstance(meta, dict):
        return usage("--meta is not a JSON object")

    st = stamp(a.root)
    doc = {
        "schemaVersion": 1,
        "storyId": a.id,
        "slug": a.slug,
        "squad": meta.get("squad"),
        "status": "draft",
        "provenance": {"indexStamp": st, "frameworkVersion": framework_version(a.root),
                       "model": meta.get("model"), "assistantVersion": meta.get("assistantVersion"),
                       "hops": meta.get("hops")},
        "components": [to_component(r) for r in rows],
        "decisions": meta.get("decisions", []),
        "unknowns": meta.get("unknowns", []),
    }
    # Written only when meta.json carries them: a record sized without a design stays as before.
    if "designOption" in meta:
        doc["designOption"] = meta["designOption"]
    if "recommendedBy" in meta:
        doc["provenance"]["recommendedBy"] = meta["recommendedBy"]
    errors = validate(doc, "draft", a.root, check_evidence=True)
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1

    reg = load_register(a.root)
    found = overlaps(doc, reg["impacts"])
    reg_commit = register_commit(a.root)
    md = render_md(doc, rows, st, found, reg["invalid"], reg_commit)

    jpath = os.path.join(out_dir, "impact.json")
    mpath = os.path.join(out_dir, "impact.md")
    for p in (jpath, mpath):
        if os.path.islink(p):
            return usage("%s is a symlink; nothing written" % p)
    os.makedirs(out_dir, exist_ok=True)
    try:
        write_nofollow(jpath, (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode("utf-8"))
        write_nofollow(mpath, md.encode("utf-8"))
    except OSError as exc:
        return usage("cannot write output without following a symlink: %s" % exc)
    print(json.dumps({"impactJson": jpath, "impactMd": mpath, "overlaps": len(found),
                      "registerCommit": reg_commit}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

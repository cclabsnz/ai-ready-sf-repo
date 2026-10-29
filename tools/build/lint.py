#!/usr/bin/env python3
"""Lint framework/ for the rules that keep ten squads honest. Exit 1 on any error.

  knowledge:  front-matter has owner, last_verified, verified_by; no stored counts; not stale > 180 days
  skills:     SKILL.md description <= 200 chars; references/input-checklist.md exists; >= 3 eval cases
  agents:     no persona prose; no stored counts; tools listed
"""
import datetime as dt
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
FW = os.path.join(ROOT, "framework")
COUNT_RE = re.compile(r"\b~?\d{2,}\s+(flows?|profiles?|permission sets?|classes|triggers|fields|objects|report types)\b", re.I)
PERSONA_RE = re.compile(r"\byou are an? (elite|expert|world[- ]class|senior)\b", re.I)


def fm(path):
    with open(path, encoding="utf-8") as fh:
        txt = fh.read()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", txt, re.S)
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
        return meta, m.group(2)
    return meta, txt


def main():
    errors = []
    today = dt.date.today()

    kdir = os.path.join(FW, "knowledge")
    for f in sorted(os.listdir(kdir)):
        if not f.endswith(".md"):
            continue
        p = os.path.join(kdir, f)
        meta, body = fm(p)
        for k in ("owner", "last_verified", "verified_by", "topic"):
            if not meta.get(k):
                errors.append(f"{f}: missing front-matter '{k}'")
        if meta.get("last_verified"):
            try:
                age = (today - dt.date.fromisoformat(meta["last_verified"])).days
                if age > 180:
                    errors.append(f"{f}: last_verified is {age} days old (limit 180)")
                elif age > 90:
                    print(f"WARN {f}: last_verified is {age} days old")
            except ValueError:
                errors.append(f"{f}: last_verified is not YYYY-MM-DD")
        for i, line in enumerate(body.splitlines(), 1):
            if COUNT_RE.search(line):
                errors.append(f"{f}:{i}: stored count; point to tools/index/query.py instead")

    sdir = os.path.join(FW, "skills")
    for n in sorted(os.listdir(sdir)):
        d = os.path.join(sdir, n)
        if not os.path.isdir(d):
            continue
        skill = os.path.join(d, "SKILL.md")
        if not os.path.exists(skill):
            errors.append(f"skills/{n}: missing SKILL.md")
            continue
        meta, body = fm(skill)
        desc = meta.get("description", "")
        if len(desc) > 200:
            errors.append(f"skills/{n}: description is {len(desc)} chars (limit 200; detail goes in the body)")
        if "not for" not in desc.lower() and "use when" not in desc.lower():
            errors.append(f"skills/{n}: description should say when to use it and what it is not for")
        if not os.path.exists(os.path.join(d, "references", "input-checklist.md")):
            errors.append(f"skills/{n}: missing references/input-checklist.md")
        cases = os.path.join(d, "evals", "cases")
        n_cases = len([c for c in os.listdir(cases) if c.endswith(".json")]) if os.path.isdir(cases) else 0
        if n_cases < 3:
            errors.append(f"skills/{n}: {n_cases} eval case(s) (minimum 3)")
        for i, line in enumerate(body.splitlines(), 1):
            if COUNT_RE.search(line):
                errors.append(f"skills/{n}/SKILL.md:{i}: stored count")

    adir = os.path.join(FW, "agents")
    for f in sorted(os.listdir(adir)):
        if not f.endswith(".md"):
            continue
        meta, body = fm(os.path.join(adir, f))
        if not meta.get("tools"):
            errors.append(f"agents/{f}: no 'tools' in front-matter")
        for i, line in enumerate(body.splitlines(), 1):
            if PERSONA_RE.search(line):
                errors.append(f"agents/{f}:{i}: persona prose; state posture and skills only")
            if COUNT_RE.search(line):
                errors.append(f"agents/{f}:{i}: stored count")

    for e in errors:
        print("ERROR " + e)
    print(f"lint: {len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

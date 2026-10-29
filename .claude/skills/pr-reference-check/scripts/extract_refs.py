#!/usr/bin/env python3
"""List candidate API names referenced in files changed vs a base ref, with path:line. stdlib only.

  python3 extract_refs.py --base origin/develop
"""
import argparse, json, re, subprocess, sys
TOKEN = re.compile(r"\b([A-Za-z][A-Za-z0-9_]*__(?:c|r|mdt|e|b)|[A-Z][A-Za-z0-9]+(?:__[A-Za-z0-9_]+__c)?)\b")
SKIP = {"System", "Test", "Database", "Schema", "String", "Integer", "Boolean", "Id", "List", "Map", "Set", "Account", "Contact", "Opportunity"}
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--base", required=True); a = ap.parse_args()
    files = subprocess.check_output(["git", "diff", f"{a.base}...HEAD", "--name-only"]).decode().split()
    out = []
    for f in files:
        if not re.search(r"\.(cls|trigger|js|xml|flow-meta\.xml)$", f):
            continue
        try:
            diff = subprocess.check_output(["git", "diff", f"{a.base}...HEAD", "-U0", "--", f]).decode(errors="replace")
        except subprocess.CalledProcessError:
            continue
        line_no = 0
        for raw in diff.splitlines():
            m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)", raw)
            if m:
                line_no = int(m.group(1)); continue
            if raw.startswith("+") and not raw.startswith("+++"):
                for t in TOKEN.findall(raw):
                    if t not in SKIP and ("__" in t):
                        out.append({"token": t, "evidence": f"{f}:{line_no}"})
                line_no += 1
    seen, uniq = set(), []
    for o in out:
        k = (o["token"], o["evidence"])
        if k not in seen:
            seen.add(k); uniq.append(o)
    print(json.dumps({"base": a.base, "count": len(uniq), "refs": uniq}, indent=1))
if __name__ == "__main__":
    main()

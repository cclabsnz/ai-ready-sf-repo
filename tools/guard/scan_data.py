#!/usr/bin/env python3
"""Pre-commit and CI scan for real data. Exit 1 on any hit.

Deterministic patterns only. This is the control; the model's judgement is not.
Add org-specific patterns in scan_patterns.json next to this file.

Usage:
  python3 tools/guard/scan_data.py            # scans staged files
  python3 tools/guard/scan_data.py --all      # scans the whole tree
  python3 tools/guard/scan_data.py path ...   # scans given files
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PATTERNS = {
    "salesforce_id_18": r"\b(?:001|003|005|006|00Q|a[0-9A-Za-z]{2})[0-9A-Za-z]{12}[A-Z0-9]{3}\b",
    "nz_bank_account": r"\b\d{2}-\d{4}-\d{7}-\d{2,3}\b",
    "nz_ird_number": r"\bIRD[:\s#]*\d{2,3}-?\d{3}-?\d{3}\b",
    "email": r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net))[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "instance_url_with_creds": r"https?://[^/\s:]+:[^/\s@]+@[A-Za-z0-9.-]+\.salesforce\.com",
    "session_id": r"\b00D[0-9A-Za-z]{12}![A-Za-z0-9._]{20,}",
    "managed_record_name": r"\bLLC_BI__[A-Za-z_]+__c\s*:\s*\S+",
}
SKIP_DIRS = {".git", "node_modules", "index"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pptx", ".xlsx", ".docx", ".zip"}


def staged_files():
    out = subprocess.check_output(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]).decode()
    return [l for l in out.splitlines() if l.strip()]


def all_files(root="."):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            yield os.path.join(dirpath, f)


def load_patterns():
    pats = dict(DEFAULT_PATTERNS)
    extra = os.path.join(HERE, "scan_patterns.json")
    if os.path.exists(extra):
        with open(extra) as fh:
            pats.update(json.load(fh))
    return {k: re.compile(v) for k, v in pats.items()}


def main(argv):
    if "--all" in argv:
        files = list(all_files())
    elif len(argv) > 1:
        files = argv[1:]
    else:
        files = staged_files()
    pats = load_patterns()
    hits = 0
    for f in files:
        if os.path.splitext(f)[1].lower() in SKIP_EXT or not os.path.isfile(f):
            continue
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh, 1):
                    for name, pat in pats.items():
                        if pat.search(line):
                            hits += 1
                            print(f"{f}:{i}: {name}")
        except OSError:
            continue
    if hits:
        print(f"\n{hits} possible real-data hit(s). Remove them or add a reviewed exception before committing.", file=sys.stderr)
        return 1
    print("scan_data: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

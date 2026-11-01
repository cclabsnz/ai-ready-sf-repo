#!/usr/bin/env python3
"""Pre-commit and CI scan for real data. Exit 1 on any hit.

Deterministic patterns only. This is the control; the model's judgement is not.

Patterns come in packs:
  default  Salesforce record IDs, emails (example.com, .org and .net exempt), instance URLs with
           credentials, session IDs. Always on.
  nz       NZ bank account and IRD numbers. Opt-in.
  ncino    nCino managed-package record names (LLC_BI__...__c: value). Opt-in.
scan_packs.json next to this file lists the packs, {"packs": ["default"]} by default. Naming a pack
adds it; leaving "default" out does not turn the default pack off. A missing file means the default
pack only. A file that does not parse, or that names an unknown pack, exits 2.
Add org-specific patterns in scan_patterns.json next to this file; they apply on top of the packs.

Usage:
  python3 tools/guard/scan_data.py            # scans staged files
  python3 tools/guard/scan_data.py --all      # scans the whole tree under the current folder
  python3 tools/guard/scan_data.py --tracked  # scans the files git tracks (git ls-files), so local,
                                              # git-ignored exports are not read
  python3 tools/guard/scan_data.py path ...   # scans given files
Exit codes: 0 clean, 1 a possible hit, 2 bad usage, a bad pack file, or git unavailable for --tracked.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PACKS = {
    "default": {
        "salesforce_id_18": r"\b(?:001|003|005|006|00Q|a[0-9A-Za-z]{2})[0-9A-Za-z]{12}[A-Z0-9]{3}\b",
        "email": r"\b[A-Za-z0-9._%+-]+@(?!example\.(?:com|org|net))[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "instance_url_with_creds": r"https?://[^/\s:]+:[^/\s@]+@[A-Za-z0-9.-]+\.salesforce\.com",
        "session_id": r"\b00D[0-9A-Za-z]{12}![A-Za-z0-9._]{20,}",
    },
    "nz": {
        "nz_bank_account": r"\b\d{2}-\d{4}-\d{7}-\d{2,3}\b",
        "nz_ird_number": r"\bIRD[:\s#]*\d{2,3}-?\d{3}-?\d{3}\b",
    },
    "ncino": {
        "managed_record_name": r"\bLLC_BI__[A-Za-z_]+__c\s*:\s*\S+",
    },
}
SKIP_DIRS = {".git", "node_modules", "index"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".pptx", ".xlsx", ".docx", ".zip"}


class UsageError(Exception):
    pass


def staged_files():
    out = subprocess.check_output(["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]).decode()
    return [l for l in out.splitlines() if l.strip()]


def tracked_files():
    """The paths git tracks under the current folder, relative to it. -z keeps unusual names unquoted."""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=False)
    except OSError as exc:
        raise UsageError("--tracked needs git: %s" % exc)
    if out.returncode != 0:
        raise UsageError("--tracked needs a git work tree: %s" % out.stderr.decode(errors="replace").strip())
    return [p for p in out.stdout.decode("utf-8", errors="surrogateescape").split("\0") if p]


def all_files(root="."):
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            yield os.path.join(dirpath, f)


def enabled_packs():
    """The pack names to apply: default, plus any scan_packs.json names. Raises UsageError on a bad file."""
    path = os.path.join(HERE, "scan_packs.json")
    if not os.path.exists(path):
        return ["default"]
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        raise UsageError("scan_packs.json cannot be read: %s" % exc)
    names = doc.get("packs") if isinstance(doc, dict) else None
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise UsageError('scan_packs.json must be {"packs": [<pack name>, ...]}')
    unknown = sorted(set(names) - set(PACKS))
    if unknown:
        raise UsageError("scan_packs.json names unknown pack(s): %s; known: %s"
                         % (", ".join(unknown), ", ".join(sorted(PACKS))))
    return ["default"] + [n for n in sorted(set(names)) if n != "default"]


def load_patterns():
    pats = {}
    for name in enabled_packs():
        pats.update(PACKS[name])
    extra = os.path.join(HERE, "scan_patterns.json")
    if os.path.exists(extra):
        with open(extra) as fh:
            pats.update(json.load(fh))
    return {k: re.compile(v) for k, v in pats.items()}


def main(argv):
    try:
        if "--all" in argv and "--tracked" in argv:
            raise UsageError("--all and --tracked cannot be combined")
        if "--tracked" in argv:
            if len(argv) > 2:
                raise UsageError("--tracked takes no paths")
            files = tracked_files()
        elif "--all" in argv:
            files = list(all_files())
        elif len(argv) > 1:
            files = argv[1:]
        else:
            files = staged_files()
        pats = load_patterns()
    except UsageError as exc:
        print("scan_data: %s" % exc, file=sys.stderr)
        return 2
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

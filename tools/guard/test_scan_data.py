#!/usr/bin/env python3
"""Tests for scan_data.py: the packs, scan_packs.json and --tracked.

Run: python3 tools/guard/test_scan_data.py

Each case copies scan_data.py into a temp folder (the scanner reads scan_packs.json from its own folder),
writes the case's scan_packs.json there, and runs the copy as a subprocess in a temp project. Every value
that the scanner would flag is assembled at run time, so no line of this file is itself a hit. The values
are synthetic; the hit emails use the reserved .invalid domain.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCANNER = os.path.join(HERE, "scan_data.py")
GIT = ["git", "-c", "user.name=scan-test", "-c", "user.email=scan-test@example.com", "-c", "commit.gpgsign=false"]

# Synthetic values, joined at run time.
SF_ID = "001" + "Zz" * 6 + "QQQ"
EMAIL = "pat.lee" + "@" + "corp-sample.invalid"
EXEMPT_EMAIL = "pat.lee" + "@" + "example.com"
CRED_URL = "https://" + "user:secret" + "@" + "acme-sample.my.salesforce.com"
SESSION = "00D" + "Zz" * 6 + "!" + "A" * 24
NZ_BANK = "12" + "-" + "3456" + "-" + "7890123" + "-" + "00"
NZ_IRD = "IRD" + ": " + "123-456-789"
NCINO = "LLC_BI" + "__Loan__c: " + "Sample Loan 1"


def scanner_dir(packs):
    """A temp folder holding a copy of the scanner and, unless packs is None, scan_packs.json with that text."""
    d = tempfile.mkdtemp(prefix="scan-tool-")
    shutil.copy(SCANNER, os.path.join(d, "scan_data.py"))
    if packs is not None:
        with open(os.path.join(d, "scan_packs.json"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(packs)
    return d


def project(files, tracked=None):
    """A temp project with files {rel: text}. With tracked (a list of rels), it is a git repo committing those."""
    d = tempfile.mkdtemp(prefix="scan-proj-")
    for rel, text in files.items():
        path = os.path.join(d, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    if tracked is not None:
        for args in (["init", "-q"], ["add", "--"] + tracked, ["commit", "-q", "-m", "fixture"]):
            subprocess.run(GIT + args, cwd=d, check=True, capture_output=True)
    return d


def scan(files, args, packs=None, tracked=None):
    """(exit code, stdout + stderr) of the scanner copy run with args in a fresh project."""
    tool, proj = scanner_dir(packs), project(files, tracked)
    try:
        p = subprocess.run([sys.executable, os.path.join(tool, "scan_data.py")] + args, cwd=proj,
                           capture_output=True, text=True)
        return p.returncode, p.stdout + p.stderr
    finally:
        shutil.rmtree(tool, ignore_errors=True)
        shutil.rmtree(proj, ignore_errors=True)


RESULTS = []


def check(name, good, detail=""):
    print(f"[{'PASS' if good else 'FAIL'}] {name}{'' if good else ' ' + str(detail)}")
    RESULTS.append(bool(good))


def case_default_pack_hits():
    for label, value, pattern in (("Salesforce record ID", SF_ID, "salesforce_id_18"), ("email", EMAIL, "email"),
                                  ("instance URL with credentials", CRED_URL, "instance_url_with_creds"),
                                  ("session ID", SESSION, "session_id")):
        for packs in (None, '{"packs": ["default"]}\n'):
            code, out = scan({"notes.txt": f"x {value} y\n"}, ["--all"], packs)
            where = "no scan_packs.json" if packs is None else "default pack file"
            check(f"default pack: {label} is a hit ({where})", code == 1 and f"notes.txt:1: {pattern}" in out, f"exit {code} {out!r}")


def case_reserved_email_exempt():
    code, out = scan({"notes.txt": f"contact {EXEMPT_EMAIL}\n"}, ["--all"])
    check("default pack: an example.com email is exempt", code == 0 and "clean" in out, f"exit {code} {out!r}")


def case_nz_off_by_default():
    for packs in (None, '{"packs": ["default"]}\n'):
        code, out = scan({"notes.txt": f"{NZ_BANK}\n{NZ_IRD}\n"}, ["--all"], packs)
        check(f"nz patterns ignored unless enabled ({'no file' if packs is None else 'default only'})",
              code == 0 and "clean" in out, f"exit {code} {out!r}")


def case_nz_enabled():
    code, out = scan({"notes.txt": f"{NZ_BANK}\n{NZ_IRD}\n"}, ["--all"], '{"packs": ["default", "nz"]}\n')
    check("nz pack enabled: bank account and IRD number are hits",
          code == 1 and "notes.txt:1: nz_bank_account" in out and "notes.txt:2: nz_ird_number" in out, f"exit {code} {out!r}")


def case_ncino_opt_in():
    code, out = scan({"notes.txt": f"{NCINO}\n"}, ["--all"])
    check("ncino patterns ignored unless enabled", code == 0 and "clean" in out, f"exit {code} {out!r}")
    code, out = scan({"notes.txt": f"{NCINO}\n"}, ["--all"], '{"packs": ["default", "ncino"]}\n')
    check("ncino pack enabled: a managed record name is a hit", code == 1 and "managed_record_name" in out, f"exit {code} {out!r}")


def case_default_always_on():
    code, out = scan({"notes.txt": f"{SF_ID}\n"}, ["--all"], '{"packs": ["nz"]}\n')
    check("a pack file without default still applies the default pack", code == 1 and "salesforce_id_18" in out,
          f"exit {code} {out!r}")


def case_bad_pack_file():
    for label, text in (("unknown pack", '{"packs": ["default", "nope"]}\n'), ("not JSON", "packs: default\n"),
                        ("packs not a list", '{"packs": "default"}\n')):
        code, out = scan({"notes.txt": "nothing here\n"}, ["--all"], text)
        check(f"scan_packs.json {label} exits 2", code == 2 and "scan_packs.json" in out, f"exit {code} {out!r}")


def case_tracked_ignores_untracked():
    files = {"clean.txt": "nothing here\n", "data/export.csv": f"Id,Email\n{SF_ID},{EMAIL}\n"}
    code, out = scan(files, ["--tracked"], tracked=["clean.txt"])
    check("--tracked ignores an untracked file holding a hit", code == 0 and "clean" in out, f"exit {code} {out!r}")
    code, out = scan(files, ["--all"], tracked=["clean.txt"])
    check("--all still reads that untracked file", code == 1 and "export.csv" in out, f"exit {code} {out!r}")


def case_tracked_finds_tracked_hit():
    files = {"clean.txt": "nothing here\n", "tools/index/notes.md": f"owner {EMAIL}\n"}
    code, out = scan(files, ["--tracked"], tracked=["clean.txt", "tools/index/notes.md"])
    check("--tracked finds a hit in a tracked file (inside a folder named index too)",
          code == 1 and "tools/index/notes.md:1: email" in out, f"exit {code} {out!r}")


def case_tracked_needs_git():
    code, out = scan({"clean.txt": "nothing here\n"}, ["--tracked"])
    check("--tracked outside a git work tree exits 2, never clean", code == 2 and "scan_data: clean" not in out,
          f"exit {code} {out!r}")


def case_usage():
    code, out = scan({"clean.txt": "x\n"}, ["--all", "--tracked"], tracked=["clean.txt"])
    check("--all with --tracked exits 2", code == 2, f"exit {code} {out!r}")
    code, out = scan({"clean.txt": "x\n"}, ["--tracked", "clean.txt"], tracked=["clean.txt"])
    check("--tracked with a path exits 2", code == 2, f"exit {code} {out!r}")


def case_given_paths_and_staged():
    code, out = scan({"a.txt": f"{SF_ID}\n", "b.txt": "x\n"}, ["b.txt"])
    check("given paths: only the named file is read", code == 0 and "clean" in out, f"exit {code} {out!r}")
    code, out = scan({"a.txt": f"{SF_ID}\n"}, ["a.txt"])
    check("given paths: a hit in the named file", code == 1 and "a.txt:1: salesforce_id_18" in out, f"exit {code} {out!r}")
    tool, proj = scanner_dir(None), project({"a.txt": "x\n"}, tracked=["a.txt"])
    try:
        with open(os.path.join(proj, "b.txt"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f"{EMAIL}\n")
        subprocess.run(GIT + ["add", "b.txt"], cwd=proj, check=True, capture_output=True)
        p = subprocess.run([sys.executable, os.path.join(tool, "scan_data.py")], cwd=proj, capture_output=True, text=True)
        check("staged mode: a hit in a staged file", p.returncode == 1 and "b.txt:1: email" in p.stdout, f"exit {p.returncode} {p.stdout!r}")
    finally:
        shutil.rmtree(tool, ignore_errors=True)
        shutil.rmtree(proj, ignore_errors=True)


def main():
    for fn in (case_default_pack_hits, case_reserved_email_exempt, case_nz_off_by_default, case_nz_enabled, case_ncino_opt_in,
               case_default_always_on, case_bad_pack_file, case_tracked_ignores_untracked, case_tracked_finds_tracked_hit,
               case_tracked_needs_git, case_usage, case_given_paths_and_staged):
        try:
            fn()
        except Exception as e:  # a case that crashes is a failure, never an abort
            check(fn.__name__, False, f"{type(e).__name__}: {e}")
    failures = RESULTS.count(False)
    print(f"\n{len(RESULTS) - failures} passed, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

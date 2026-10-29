---
name: pr-reference-check
description: Find invented or mistyped API names in a PR diff against the metadata index and judge test meaningfulness. Use when reviewing a PR. Not for secrets, naming or coverage (CI does those).
---
# PR reference check

Audience: reviewers. Output: a table of referenced API names that do not exist or are used against their type, plus a judgement on test meaningfulness and scope. Verdict is **Ready for human review** or **Changes suggested**; never "Approve".

## What CI already does (do not repeat)
Secrets (gitleaks), `scan_data.py`, manifest completeness, `System.debug`, `SeeAllData`, naming, coverage floor, API-version bumps on untouched files. Link to the CI run instead.

## Steps
1. `python3 tools/index/query.py check-stale`; rebuild if exit 3.
2. Diff against the PR's **target** branch: `git diff origin/<target>...HEAD --name-only` (never hardcode `develop`).
3. `python3 framework/skills/pr-reference-check/scripts/extract_refs.py --base origin/<target>` lists every API name token in changed files with `path:line`.
4. For each token: `query.py exists` and `query.py type`. Names absent from the index and from `namespaces.json` prefixes are **invented** (Confirmed by zero hits). Names present but used against their field type (e.g. text compared as number, `ORDER BY` on an encrypted field) are **mistyped** (Inferred; cite the field node).
5. Judgement, briefly: does the diff match the work item; do new tests assert behaviour; does a bug-fix PR include a test that fails without the fix.

## Output
Table: Severity (Blocker / Should fix / Note), `path:line`, issue, evidence, suggested fix. Then the verdict, then the list of things that could not be verified (managed-package fields, org-only config).

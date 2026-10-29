---
name: story-impact
description: Quantified, evidenced impact of one work item (story, feature, defect) on this repo's metadata. Use when sizing or scoping a single item. Not for release or upgrade impact.
---
# Story impact

Audience: BAs, developers, tech leads, architects. Output: an evidenced list of what one work item touches, with confidence per claim. Not in scope: recommending solutions or estimating effort.

## Guardrails
Project rules apply (`00-precedence`, `20-no-real-data`). The guard in `.claude/settings.json` blocks org calls, writes outside `ai-context/`, and fetches off the allowlist; do not try to work around a block, report it.

## Step 0: freshness
Run `python3 tools/index/query.py check-stale`. If exit code is 3, run `python3 tools/index/build_index.py` first. Record the stamp in the output.

## Step 1: inputs
Build the table from `references/input-checklist.md` and show it. Ask **once** for missing required inputs. Missing optional inputs become unknowns and cap confidence at Inferred. Copy (never move) any attached files to `ai-context/<id>-<slug>/inputs/`.

## Step 2: frame
Two to four sentences: item type, persona and segment, trigger or symptom, what "affected" means for this item.

## Step 3: seed terms and scan
1. Derive API-name seed terms per `references/seed-terms.md`. Write them to `ai-context/<id>-<slug>/scan/terms.txt`.
2. For each term: `python3 tools/index/query.py exists <term>` then `python3 tools/index/query.py consumers <term> --hops <hops>` (`hops` is an optional input, 1 to 3, default 2).
3. Zero hits is valid evidence: record "zero consumers in index for `<term>`".
4. Triage: drop false positives with a one-line reason each, kept in the output.

## Step 4: classify
For each impacted component: layer, metadata type, ownership (Custom / Managed / Standard), change type, impact (High / Medium / Low / None), scale band (S / M / L / XL, a measure of surface area not effort), hop, evidence `path:line`, confidence (Confirmed / Inferred / Unverifiable).

## Step 5: write
`python3 framework/skills/story-impact/scripts/write_report.py --id <id> --slug <slug> --classified <json>` produces `impact.md`. Then run `references/manual-checks.md` for what the index cannot see (order of execution, dynamic SOQL, `without sharing` paths) and append findings.

## Response style
Lead with the numbers, then the evidence table. End with: inputs still missing, unknowns handed to humans, decisions required (owner role), and the artefact path.

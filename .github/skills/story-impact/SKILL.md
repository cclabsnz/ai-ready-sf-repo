---
name: story-impact
description: Quantified, evidenced impact of one work item (story, feature, defect) on this repo's metadata. Use when sizing or scoping a single item. Not for release or upgrade impact.
---
# Story impact

Audience: BAs, developers, tech leads, architects. Output: an evidenced list of what one work item touches, with confidence per claim. Not in scope: recommending solutions or estimating effort.

## Guardrails
Project rules apply (`00-precedence`, `20-no-real-data`). The guard in `.claude/settings.json` blocks org calls, writes outside `ai-context/`, and fetches off the allowlist; do not try to work around a block, report it.

## Step 0: freshness
Run `python3 tools/index/query.py check-stale`. If exit code is 3, run `python3 tools/index/build_index.py --from-config` first. Record the stamp in the output.

## Step 1: inputs
Build the table from `references/input-checklist.md` and show it. Ask **once** for missing required inputs. Missing optional inputs become unknowns and cap confidence at Inferred. Copy (never move) any attached files to `ai-context/<id>-<slug>/inputs/`.

## Step 2: frame
Two to four sentences: item type, persona and segment, trigger or symptom, what "affected" means for this item.

## Step 3: seed terms and scan
1. Derive API-name seed terms per `references/seed-terms.md`. Write them to `ai-context/<id>-<slug>/scan/terms.txt`.
2. For each term: `python3 tools/index/query.py exists <term>` then `python3 tools/index/query.py consumers <term> --hops <hops>` (`hops` is an optional input, 1 to 3, default 2).
3. Zero hits is valid evidence: record "zero consumers in index for `<term>`".
4. Triage: drop false positives with a one-line reason each, kept in the output.

## Step 3a: a design on record (when `ai-context/<id>-<slug>/design.json` exists)
solution-design wrote options and one provisional recommendation. Assess the recommended option (`recommendation.optionId`), or the option the owner named when you are re-run for another one. Use only that option's components:
- An existing component (`changeType` `modify`, `delete` or `review`) gets evidence `path:line` from the Step 3 scan, like any other row.
- A component the option adds is declared `changeType: new`, with null evidence.
- For a do-nothing option (`doNothing: true`), record only `review` components, or none. `promote.py` refuses a do-nothing choice whose impact has a `new`, `modify` or `delete` component.
- Seed terms from the rest of the story still apply. A component the scan finds outside the option is listed with its evidence, and the gap is named in the framing.

## Step 4: classify
For each impacted component: layer, metadata type, ownership (Custom / Managed / Standard), change type, impact (High / Medium / Low / None), scale band (S / M / L / XL, a measure of surface area not effort), hop, evidence `path:line`, confidence (Confirmed / Inferred / Unverifiable).

## Step 5: write
1. Write `classified.json` (the Step 4 rows) and `meta.json` side by side in `ai-context/<id>-<slug>/scan/`. `<id>` is the story id (`DEMO-201` form) and `<slug>` is lower-case words joined by `-`. meta.json is `{"squad", "hops", "model", "assistantVersion", "decisions": [{"text", "ownerRole"}], "unknowns": [...]}`. `model` is your own model id. `assistantVersion` is the assistant's version, or `"unknown"` when you can't read it. Change types are `new`, `modify`, `delete` or `review`. Validation (`tools/impacts/validate.py`) also enforces these rules:
   - `squad` is listed in `impacts/squads.json`.
   - `hops` is an integer from 1 to 3.
   - Each `api` appears once in `classified.json`.
   - `evidence` is null only when the change type is `new` or the confidence is Unverifiable.
   - With a design on record (Step 3a), meta.json also carries `"designOption": "OPT-<n>"` (the assessed option) and `"recommendedBy": "assistant"` when that option is the design's recommendation. For an option the owner named instead, leave `recommendedBy` out. `promote.py` refuses an impact whose `designOption` is not the option the owner confirms, so a different choice means re-running this skill for it, never hand-editing the record.
2. Run `python3 framework/skills/story-impact/scripts/write_report.py --id <id> --slug <slug> --classified ai-context/<id>-<slug>/scan/classified.json --meta ai-context/<id>-<slug>/scan/meta.json`. It validates the record first and writes nothing on errors (exit 1). Fix the inputs and run it again. On success it writes `impact.json` (a draft record) and `impact.md`.
3. `impact.md` has an `## Overlaps with other stories` section that the script builds from the register in `impacts/`. Report it as written and never rewrite it.
4. Run `references/manual-checks.md` for what the index cannot see (order of execution, dynamic SOQL, `without sharing` paths) and append findings.

## Response style
Lead with the numbers, then the evidence table. Name every overlap with its squad and the owner role who must talk to that squad. End with: inputs still missing, unknowns handed to humans, decisions required (owner role), and the artefact path.

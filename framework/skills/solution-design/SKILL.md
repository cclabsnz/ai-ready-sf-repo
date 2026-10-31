---
name: solution-design
description: Two to four evidenced solution options for one story, always including do nothing, with one provisional recommendation. Use before sizing a story. Not for sizing, estimates or code.
---
# Solution design

Audience: tech leads, architects, BAs, product owners. Output: a draft `design.json` and `design.md` with two to four options (one of them is always "do nothing"), trade-offs on named criteria, the components each option touches with evidence, and one recommended option with reasons. Not in scope: sizing the chosen option (that is `story-impact`), estimates, code.

## Guardrails
Project rules apply (`00-precedence`, `20-no-real-data`). The guard in `.claude/settings.json` blocks org calls, writes outside `ai-context/`, and fetches off the allowlist; do not try to work around a block, report it. This is the one skill that may recommend. The recommendation is provisional: the assistant proceeds with it, but never presents it as confirmed or binding. A named owner confirms an option at promotion; until then the design is a draft.

## Step 0: freshness
Run `python3 tools/index/query.py check-stale`. If exit code is 3, run `python3 tools/index/build_index.py --from-config` first.

## Step 1: inputs
Build the table from `references/input-checklist.md` and show it. Ask **once** for missing required inputs. Read `ai-context/<id>-<slug>/story.json` when it exists (from `story-refine`), and the Understand framing of any impact already written for this story (`impact.md`, its opening framing). Missing optional inputs become open points in the trade-off notes. Copy (never move) any attached files to `ai-context/<id>-<slug>/inputs/`.

## Step 2: candidate components
1. Derive API-name seed terms from the story's nouns (as in `story-impact`'s `references/seed-terms.md`).
2. For each term run `python3 tools/index/query.py exists <term>`, then `python3 tools/index/query.py consumers <term> --hops 2` for the ones that exist. Zero hits is a finding: record "zero hits in index for `<term>`". A component with zero hits can only appear in an option as `new`.
3. Run `python3 tools/impacts/register.py view` to see in-flight stories; a component another squad is changing is a trade-off note under `maintainability`.

## Step 3: options
Write two to four options per `references/option-template.md`, ids `OPT-1` to `OPT-n` with no gaps. Exactly one option has `doNothing: true` and no components; state plainly when the build already meets the story (as an evidenced trade-off note). Every other option lists at least one component:
- `changeType` is `new`, `modify`, `delete` or `review`. A component that is not `new` is a node in the index (the writer checks this) and carries `path:line` evidence.
- A `new` component has `evidence: null`.
- `confidence` is Confirmed, Inferred or Unverifiable.

Give each option at least one trade-off on the criteria in `references/trade-off-criteria.md`, and an `impactSummary` in one sentence.

## Step 4: recommendation
Name one option in `recommendation.optionId`, with at least one reason in `recommendation.reasons`. Reasons cite evidence (`path:line`) or a trade-off. "Do nothing" is a valid recommendation when the evidence shows the story is already met.

## Step 5: write
1. Write the draft to `ai-context/<id>-<slug>/scan/design-draft.json`: the design record without `schemaVersion`, `status`, `provenance`, `confirmedBy` and `chosenOption` (the writer fills the first three; promotion adds the last two; a draft that carries any of them is refused). Keys: `storyId`, `slug`, `options`, `recommendation`.
2. Run `python3 framework/skills/solution-design/scripts/write_design.py --id <id> --slug <slug> --draft ai-context/<id>-<slug>/scan/design-draft.json --model <your model id> --assistant-version <version or unknown>`. It loads the index (`--index`, default `index/`; a missing index is exit 2), validates the record with `tools/designs/validate_design.py` against that index with evidence checked, and writes nothing on errors (exit 1). Fix the draft and run it again until it exits 0. It records `provenance.sourceRoot`: `--source-root <dir>`, or the configured `sourceRoot` in `.ai-framework.json` by default. Pass the index built from that same root. The writer does not check this. For the greenfield demo, that means `--source-root demo/greenfield` with an index built by `python3 tools/index/build_index.py --root demo/greenfield --out <absolute dir>`. The `--from-config` index covers only the configured root (`demo/org`).
3. `design.md` is built by the script from `design.json`. Report it as written and never rewrite it.

## Step 6: proceed provisionally
Hand the recommended option to `story-impact` (its Assess step) and size that option. The handoff contract: story-impact reads `ai-context/<id>-<slug>/design.json`, and its `meta.json` carries `designOption` (the recommended `OPT-n`) and `recommendedBy: "assistant"`. `write_report.py` passes both into `impact.json` and names the assessed option in `impact.md`. At promotion, `tools/impacts/promote.py` confirms the design with the impact. The owner's choice is `--option OPT-k`, or the recommendation when the flag is omitted. If the impact assesses a different option, promotion refuses: `impact assesses OPT-a; re-run story-impact for OPT-b before promoting`. story-impact is then re-run for the owner's option, with `designOption` set to it and `recommendedBy` left out. The record is never hand-edited.

## Response style
Lead with the options table, then the recommendation and its reasons. Say plainly that the recommendation is provisional until a named owner confirms it at promotion, and that the assistant never confirms it. Then list each option's trade-offs and components with evidence, zero-hit terms, open points with owner roles, and the artefact paths.

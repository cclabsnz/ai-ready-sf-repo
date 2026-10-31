---
name: story-refine
description: Refine one story into testable acceptance criteria and evidenced edge cases from this repo's metadata. Use when a story is vague or before sizing it. Not for impact sizing or test scripts.
---
# Story refinement

Audience: product owners, BAs, developers, testers. Output: a draft `story.json` and `story.md` with Given/When/Then criteria, edge cases seeded from the index, dropped seeds with reasons, overlaps with other stories, and open questions with owner roles. Not in scope: sizing (that is `story-impact`), solution design, estimates, test scripts.

## Guardrails
Project rules apply (`00-precedence`, `20-no-real-data`). The guard in `.claude/settings.json` blocks org calls, writes outside `ai-context/`, and fetches off the allowlist; do not try to work around a block, report it. The assistant never confirms a story. The product owner confirms it by promoting it (`tools/impacts/promote.py --story`); until then it is a draft.

## Step 0: freshness
Run `python3 tools/index/query.py check-stale`. If exit code is 3, run `python3 tools/index/build_index.py` first.

## Step 1: inputs
Build the table from `references/input-checklist.md` and show it. Ask **once** for missing required inputs. Missing optional inputs become open questions. Copy (never move) any attached files to `ai-context/<id>-<slug>/inputs/`.

## Step 2: frame
Two to four sentences: persona, goal, benefit, and what the story leaves out. Quote the story's own words where they are vague; do not paraphrase them into something precise.

## Step 3: seed terms
1. Derive API-name seed terms from the nouns in the story (as in `story-impact`'s `references/seed-terms.md`). Write them one per line to `ai-context/<id>-<slug>/scan/terms.txt`.
2. For each term run `python3 tools/index/query.py exists <term>`. A term with zero hits stays in the story as a planned new component; it gets no seeds.

## Step 4: edge seeds
Run `python3 tools/index/query.py edge-seeds <term> [<term>...] > ai-context/<id>-<slug>/scan/edge-seeds.json` with every term from `terms.txt`. Terms the index does not hold come back under `unresolved`: those are the planned new components, and they produce no seeds. The seeds are the only source of edge cases; see `references/edge-seeds.md`. Greenfield: when the scan returns few or no seeds, say so in the report and invent none. Record every term passed in the story's `seeds` list.

## Step 5: judge each seed
Every seed in `scan/edge-seeds.json` is accounted for, one by one: either keep it as an edge case (`EC-n`, with the seed's `category`, `component`, `detail`, `evidence` and `confidence` copied verbatim) or drop it into `droppedSeeds` (`category`, `component` and `detail` copied verbatim) with a one-line reason. A seed is identified by its (component, category, detail); never reword `detail`. A kept edge case either becomes a criterion (`becameCriterion: "AC-n"`) or carries a `reason` why it stays an edge case only.

## Step 6: criteria
Write each criterion as Given/When/Then with at least one concrete example, per `references/criteria-style.md`. One observable outcome per `then`. `source` is `stated` (from the story text), `edge-case` (from a kept seed) or `assistant-proposed`. Anything you guessed becomes an `openQuestions` entry (`OQ-n`, `text`, `ownerRole`, `answer: null`, `deferred: false`, `deferredBy: null`), never a criterion stated as fact. You never set `deferred` or `deferredBy`: only the owner defers a question (`deferred: true`, `deferredBy` set to their role), before promotion. `promote.py --story` lists every deferred and answered question to the product owner before it writes.

## Step 7: write
1. Write the draft to `ai-context/<id>-<slug>/scan/draft.json`: the story record without `schemaVersion`, `status`, `overlaps` and `confirmedBy` (the writer fills those in; a draft that carries them is refused). Keys: `storyId`, `slug`, `squad` (listed in `impacts/squads.json`), `persona`, `goal`, `benefit`, `inScope`, `outOfScope`, `nonFunctional`, `openQuestions`, `acceptanceCriteria`, `edgeCases`, `droppedSeeds`, `seeds`.
2. Run `python3 framework/skills/story-refine/scripts/write_story.py --id <id> --slug <slug> --draft ai-context/<id>-<slug>/scan/draft.json`. It validates the record (`tools/stories/validate_story.py`, evidence checked) and the criteria (`tools/stories/check_ac.py`), and writes nothing on errors (exit 1). Fix the draft and run it again until it exits 0.
3. `story.md` has an `## Overlaps with other stories` section that the script builds from the register in `impacts/`, with every seed as a review component, so each overlap is a watch. Report it as written and never rewrite it.

## Response style
Lead with the refined story: persona, goal, benefit, then the criteria table. You may recommend this refined story and proceed with it provisionally, but say plainly that it is a draft: the product owner confirms it by promoting it, and the assistant never confirms it. Then list the edge cases kept and dropped with reasons, every overlap with its squad and the owner role who talks to that squad, open questions with owner roles, and the artefact paths. When the scan returned few or no seeds, say so.

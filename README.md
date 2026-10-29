# AI-ready Salesforce repo (example)

A reference layout for running AI assistants (Claude Code and GitHub Copilot) safely across many
Salesforce build squads. Everything a squad wants from the assistant (impact analysis, PR review,
discovery) is a consumer of one capability: a deterministic, SHA-stamped index of the checkout.

Principles, in order of precedence:

1. The checkout is the only source of truth. Knowledge files are leads to re-verify.
2. Deterministic before probabilistic: scripts count and check; the model interprets and judges.
3. Enforcement lives in project settings so every agent, skill and direct call inherits it.
4. Nothing from an org enters git.
5. Every claim carries `path:line` evidence and a label (Confirmed / Inferred / Unverifiable).
6. The assistant never approves, deploys, pushes or decides.

## Layout

```
framework/            the ONE source tree squads edit (guild-owned via CODEOWNERS)
  rules/              always-on rules; scope front-matter -> Copilot applyTo
  knowledge/          owned, dated facts; no counts allowed (lint enforces)
  skills/<name>/      SKILL.md + references/ + scripts/ + evals/
  agents/             posture + skill table, nothing else; evals/ holds trajectory specs
tools/
  index/              build_index.py (the index), query.py (what skills call instead of grep)
  guard/              guard.py + guard.sh/.cmd (fail-closed PreToolUse hook), scan_data.py, test_guard.py
  build/              render.py (framework/ -> .claude/ + .github/), lint.py
  evals/              run_skill.py (output assertions), run_agent.py (trajectory assertions)
.claude/              GENERATED, plus the hand-written settings.json (hooks, deny rules, kill switch)
.github/              GENERATED instructions/knowledge/skills/agents, plus workflows/ and hooks/
fixtures/             synthetic metadata and diffs for evals and CI; never real
ai-context/           every output lands here (inputs/ and binaries git-ignored)
index/                generated; never committed
```

## Try it

```sh
python3 tools/guard/test_guard.py                 # proves the guard blocks on this machine
python3 tools/build/lint.py                       # framework rules
python3 tools/build/render.py && python3 tools/build/render.py --check
python3 tools/index/build_index.py --root fixtures --out ../index
python3 tools/index/query.py consumers Account.Risk_Rating__c --hops 2 --index index
python3 tools/evals/run_agent.py --log framework/agents/evals/sample-run.jsonl --spec framework/agents/evals/analyst.json
```

On Windows use `py -3` in place of `python3`. The guard wrapper finds the interpreter itself and
exits 2 (block) if none is found, because Claude Code treats any other exit code as a warning
and lets the tool call through.

## Kill switch

Set `AI_FRAMEWORK_MODE=advise` in `.claude/settings.json` (or the environment) and the guard
blocks every write and every non-read-only command; the assistant can only output recommendations.
One line, programme-wide, no laptop changes.

## Onboarding a squad member (15 minutes)

1. Install and pin the assistant version named in `VERSION`.
2. Run `tools/guard/test_guard.py`; all cases must pass on their laptop.
3. Run one eval case end to end.
4. Read `framework/rules/00-precedence.md`.
5. Know who the guild is (see `CODEOWNERS`).

## What is deliberately absent

Seed-memory (pointers only), org facts inside agents or skills, any check a script could do done by
the model, any output path other than `ai-context/`, and any automation that votes, deploys or pushes.

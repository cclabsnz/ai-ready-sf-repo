# Handoff: continuing this build in Claude Code

Read this first, then `docs/DESIGN.md`, then `README.md`. Do not start a task until the smoke
test below passes on this machine.

## What this is

A reference implementation of an AI-ready Salesforce repo for 6–10 build squads using Claude Code
and GitHub Copilot. Five layers inside one control plane: the checkout, a deterministic metadata
index, three context tiers, thin skills, and a few agents. Design rationale and the eight-week
build order are in `docs/DESIGN.md`. Stack is stdlib Python 3 only; do not add dependencies
without a written reason in the PR.

## Non-negotiables (from docs/DESIGN.md, enforced by code in this repo)

1. The checkout is the only source of truth. No counts in markdown; `tools/index/query.py` answers them.
2. Deterministic before probabilistic: if a script can check it, a script does.
3. Enforcement in `.claude/settings.json`, not in prose. Every new tool the agent can use goes through the guard.
4. Nothing from an org enters git. Fixtures are synthetic. `tools/guard/scan_data.py` gates commits.
5. Every claim: `path:line` evidence + Confirmed / Inferred / Unverifiable.
6. The assistant never approves, deploys, pushes or decides.

## Smoke test (run before anything else)

```sh
python3 tools/guard/test_guard.py          # every case must pass
python3 tools/build/lint.py                # 0 errors
python3 tools/build/render.py --check      # "rendered outputs are current"
python3 tools/index/build_index.py --root fixtures --out ../index
python3 tools/index/test_index.py          # every path:line opens from the repo root
python3 tools/index/query.py consumers Account.Risk_Rating__c --hops 2 --index index   # 5 consumers
python3 tools/evals/run_agent.py --log framework/agents/evals/sample-run.jsonl --spec framework/agents/evals/analyst.json
```

On Windows use `py -3`. If the guard test fails here, fix that before touching anything else.

## Working rules for this repo

- Edit `framework/`, never `.claude/` or `.github/` directly (except `.claude/settings.json`,
  `.github/workflows/`, `.github/hooks/`). Run `python3 tools/build/render.py` after any
  `framework/` change and commit the rendered output with it.
- Any change under `framework/skills/` needs its eval cases to still pass. Add a case when you
  fix a behaviour, so it stays fixed.
- Any change to `tools/guard/` needs a new case in `test_guard.py`.
- Run `python3 tools/build/lint.py` before every commit.
- Keep `docs/DESIGN.md` in step with reality: if you change a layer's behaviour, change the doc in
  the same PR.

## Backlog, in order

### Gate 1 hardening (do first)
- [x] `tools/guard/test_guard.py`: add a case that runs the wrapper with PATH cleared of every
      Python and asserts exit 2 (proves fail-closed on a laptop with no interpreter).
- [ ] `tools/index/build_index.py`: add parsers for custom metadata records, custom labels,
      named credentials, record types and FlexiPages; add `@AuraEnabled` method → LWC edges.
- [ ] `tools/index/query.py`: add `inventory` subcommand that prints `inventory.json` sections.
- [ ] Copilot hook registration under `.github/hooks/` pointing at the same guard; document the
      exact file Copilot expects once confirmed against current docs.

### Skills
- [ ] `story-impact`: write `evals/expected/*.md` golden outputs for the three cases, produced by
      running the skill under Claude Code headless on the fixtures, reviewed by hand.
- [ ] `pr-reference-check`: the eval cases reference `fixtures/diffs/*.patch`; add a small runner
      that applies a patch to a temp branch so `extract_refs.py --base` works in CI.
- [ ] `release-impact`: new skill. Reads `inventory.json` plus user-supplied release-note text.
      Needs `references/input-checklist.md`, `scripts/baseline.py` (reads inventory, never greps),
      and three eval cases. Description ≤ 200 chars.

### Evals harness
- [ ] `tools/evals/run_all.py`: for each skill and case, invoke `claude -p` N times (default 5)
      with the repo as cwd, write outputs to a temp dir, call `run_skill.py`. Exit non-zero on
      any failure. This is the home-grown alternative to Promptfoo; keep assertions in
      `run_skill.py`, never in the runner.
- [ ] Optional: `promptfooconfig.yaml` that wraps the same cases and calls `run_skill.py` as a
      python assertion, for teams that already use Promptfoo.

### Packaging
- [ ] `.claude-plugin/plugin.json` (or current manifest format; verify against docs) so squads
      install a pinned version instead of copying files.
- [ ] `CHANGELOG.md` started at 0.1.0.

## Questions to resolve with the guild, not alone

- Exact Copilot hook file format and location for the organisation's Copilot version.
- Whether the org's SAST tool is updated for `WITH USER_MODE` (Checkmarx historically was not).
- The real managed-package namespace list for `namespaces.json`.
- Who owns `framework/knowledge/permissions-model.md` (replace the placeholder email).

## Commit conventions

Small PRs, one layer at a time. Every PR touching `tools/guard/` or `.claude/settings.json`
gets a second reviewer. Render output is committed alongside its source change.

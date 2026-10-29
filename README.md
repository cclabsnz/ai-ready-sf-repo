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
  guard/              guard.py + guard.sh/.cmd (fail-closed PreToolUse hook), policy.json (its rules),
                      scan_data.py, test_guard.py
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
and lets the tool call through. The hook is registered through `sh` (Git Bash on Windows, which is
Inferred, not yet tested there); `guard.cmd` is a fallback and Unverifiable until the Windows CI job runs.

## Kill switch

Set `AI_FRAMEWORK_MODE=advise` in `.claude/settings.json` and the guard blocks every write and
every non-read-only command; the assistant can only output recommendations. One line,
programme-wide, no laptop changes. The committed value is the ceiling: a committed `advise`
always wins over a local override, and a local mode applies only over a committed `normal`.

## Modes

The guard has four modes: `advise` (kill switch, read-only), `normal` (the committed default;
writes to `ai-context/` and `index/`, runs the framework scripts), `build` (adds local dev
tooling) and `maintain` (adds the framework paths and a maintainer command allowlist). To pick
`build` or `maintain` for yourself, put `{"env": {"AI_FRAMEWORK_MODE": "build"}}` in your own
git-ignored `.claude/settings.local.json`. Bash is allowlist-based outside `advise`. The hook runs
on every tool, MCP tools included; MCP tools are blocked in `advise`, and elsewhere when a
segment of their name is a write verb. Any tool other than Bash that takes a `command` (a PowerShell
tool, `Monitor`, an MCP shell) is blocked in every mode. In every mode, a Bash line holding `$`, braces
or a `[[:class:]]` bracket outside single quotes is blocked, and so is a heredoc: single-quote that
text or put it in a file (`git commit -F ai-context/<file>`). The full table is in
`docs/DESIGN.md` under "Modes"; what the guard does and does not guarantee is under "What the
guard guarantees". The laptop layer is best effort; CODEOWNERS, branch protection, CI and review
are the hard guarantee.

## One-time step after applying the guard patches

While the guard's tripwire has no recorded baseline for `.git/config` and `.git/hooks/`, every write
and every non-read-only command is blocked. A human records the baseline once, in a terminal
(the command refuses to run without one, and the hook blocks the assistant from running it):

```sh
python3 tools/guard/guard.py --rebaseline
```

Run it again whenever `.git/config` or `.git/hooks/` legitimately change, for example when
installing husky hooks, and once inside every new git worktree. Adding a remote or setting branch
tracking does not need it.

## Salesforce CLI levels

The assistant gets only local, offline `sf` commands by default (none at all in `advise`). A
programme can opt in to read-only metadata or data queries against named non-production orgs by a
reviewed change to `tools/guard/policy.json` (`sf.mode_level`, `sf.allowed_orgs`). Login, deploy,
data writes and `apex run` stay blocked at every level. Levels, the always-blocked list and the
`org-data` warning are in `docs/DESIGN.md` under "Salesforce CLI access levels".

## Onboarding a squad member (15 minutes)

1. Install and pin the assistant version named in `VERSION`.
2. Run `tools/guard/test_guard.py`; all cases must pass on their laptop.
3. Run one eval case end to end.
4. Read `framework/rules/00-precedence.md`.
5. Know who the guild is (see `CODEOWNERS`).

## What is deliberately absent

Seed-memory (pointers only), org facts inside agents or skills, any check a script could do done by
the model, any output path other than `ai-context/`, and any automation that votes, deploys or pushes.

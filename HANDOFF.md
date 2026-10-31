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
6. The assistant may recommend and proceed provisionally; it never approves, deploys, pushes or makes a binding decision. Every recommendation is confirmed by a named owner before it becomes a committed impact or a code scope.

## Where things stand

**Built, with tests:** the guard and its modes (WS0); the demo org, index and answer keys (WS1);
the impact record, register and PR check (WS2); story refinement (WS11), starting points and
solution design (WS10) and scoped code writing (WS8), whose guard and CI patches are not applied
yet (so, for example, `build` cannot write source today); the consistency comparer and the live-run
collector (WS3); the measurement kit (WS4); the walkthrough with its deterministic check and the
adoption guide (WS5); `CHANGELOG.md`, `CONTRIBUTING.md` and `SECURITY.md`. `CHANGELOG.md` lists
what each workstream delivered.

**Stated, not built:** the Copilot guard (WS6). Copilot users get the rendered instructions and
no guard; see "Copilot today" in `docs/DESIGN.md`.

**Waits on the owner.** Human-only steps are tracked in the maintainers' owner queue,
`ai-context/OWNER-QUEUE.md` (git-ignored workspace). In outline:

- apply the owner patches in order: WS11, WS10, WS8, then the publish patches
  (`ai-context/publish/patches/`), re-baselining the guard after each commit;
- confirm the DEMO-202 story, design and impact, build and commit its package, and start a
  build session, so the code walkthrough can run (and the same for the greenfield DEMO-301);
- pick the plugin layout, place the drafted files and tag the first release;
- run the live `run_all.py` series and any skill runs under Claude Code; no model has run
  story-refine, solution-design or implement-story here yet.

## Smoke test (run before anything else)

```sh
python3 tools/guard/test_guard.py          # every case must pass
python3 tools/build/lint.py                # 0 errors
python3 tools/build/render.py --check      # "rendered outputs are current"
python3 tools/index/build_index.py --root fixtures --out ../index
python3 tools/index/test_index.py          # every path:line opens from the repo root
python3 tools/index/test_parsers.py        # parsers build their own temp trees
python3 tools/demo/test_generate_filler.py # filler is seeded and deterministic
python3 tools/demo/test_check_answers.py   # answer-key checker
python3 tools/demo/test_answer_to_draft.py # key-derived draft through the real writer
python3 tools/impacts/test_validate.py     # impact.json schema
python3 tools/impacts/test_register.py     # register: overlaps, scope, view
python3 tools/impacts/test_write_report.py  # story-impact writer: impact.json and overlaps
python3 tools/impacts/test_promote.py      # promotion into impacts/
python3 tools/impacts/test_render_register.py # static register page
python3 tools/impacts/test_pr_check.py     # PR check: code overlap and scope drift
python3 tools/evals/test_run_skill.py      # skill output assertions
python3 tools/evals/test_consistency.py    # consistency comparer
python3 tools/evals/test_run_all.py        # live-run collector (an injected runner; claude never starts)
python3 demo/measure/test_score.py         # score.py: an impact against its key
python3 demo/measure/test_timing.py        # timing.py: a session transcript
python3 tools/demo/test_walkthrough_check.py # walkthrough check: normalising and diffing
python3 tools/index/test_edge_seeds.py     # edge seeds from the index
python3 tools/stories/test_validate_story.py # story.json schema
python3 tools/stories/test_check_ac.py     # vague-criteria check
python3 tools/stories/test_write_story.py  # story-refine writer: story.json and overlaps
python3 tools/config/test_framework_config.py # .ai-framework.json reader
python3 tools/onboard/test_onboard.py      # onboarding: existing and greenfield
python3 tools/designs/test_validate_design.py # design.json schema
python3 tools/designs/test_write_design.py # solution-design writer
python3 tools/code/test_check_rules.py     # Apex rule checks and the baseline
python3 tools/code/test_check_trace.py     # trace check CLI (stub core; real core once patched)
python3 tools/impacts/test_package.py      # build package from confirmed records
python3 tools/impacts/test_start.py        # start.py (stub core; real core once patched)
python3 tools/code/test_write_change.py    # implement-story writer: change.json
python3 tools/code/check_rules.py --from-config # exit 0: every demo finding is baselined
python3 tools/impacts/validate.py --all    # every committed record validates; "ok": true
python3 tools/stories/validate_story.py --all # every confirmed story validates; "ok": true
python3 tools/designs/validate_design.py --all # every confirmed design validates; "ok": true
python3 tools/index/query.py consumers Account.Risk_Rating__c --hops 2 --index index
python3 tools/evals/run_agent.py --log framework/agents/evals/sample-run.jsonl --spec framework/agents/evals/analyst.json
python3 tools/demo/walkthrough_check.py    # walkthrough's deterministic steps match demo/expected/
```

On Windows use `py -3`. If the guard test fails here, fix that before touching anything else.
The impact, story, config, onboarding, design, code, evals and measurement test scripts each end
with `<n> passed, 0 failed`; some add a skipped count for symlink cases. `walkthrough_check.py`
ends with `<n> passed, 0 failed` too, and builds its own index in a temp folder, so the fixtures
build above does not affect it. `test_check_trace.py` and
`test_start.py` also skip their real-core test until the WS8 guard patch puts
`tools/guard/trace_core.py` and `scope_core.py` in place. In `normal` and `build` modes
the assistant cannot run the `tools/demo/`, `tools/impacts/`, `tools/stories/`, `tools/config/`,
`tools/onboard/`, `tools/designs/` and `tools/code/` test scripts, `tools/index/test_edge_seeds.py`,
the `tools/evals/` test scripts, the `demo/measure/` tests, or `walkthrough_check.py`; run them
yourself or in `maintain`. `check_rules.py --from-config`
also needs `maintain` or your terminal until the WS8 guard patch adds it to `normal` and `build`. `validate.py --all` runs in
`normal`. `validate_story.py --all` joins `normal`'s allowlist only once the owner applies the
WS11 guard patch (`ai-context/ws11/patches/APPLY.md`), and `validate_design.py --all` only once
the owner applies the WS10 guard patch (`ai-context/ws10/patches/APPLY.md`); until then each
needs `maintain` or your own terminal. The fixtures build above replaces `index/`; rebuild the
demo index with `python3 tools/index/build_index.py --from-config` before using a skill.

## Working rules for this repo

- Edit `framework/`, never `.claude/` or `.github/` directly (except `.claude/settings.json`,
  `.github/workflows/`, `.github/hooks/`). Run `python3 tools/build/render.py` after any
  `framework/` change and commit the rendered output with it.
- Any change under `framework/skills/` needs its eval cases to still pass. Add a case when you
  fix a behaviour, so it stays fixed.
- Any change to `tools/guard/` needs a new case in `test_guard.py`.
- Run `python3 tools/build/lint.py` before every commit.
- The committed mode in `.claude/settings.json` stays `normal`. A framework maintainer enters
  `maintain` for themselves only, through a personal git-ignored `.claude/settings.local.json`
  containing `{"env": {"AI_FRAMEWORK_MODE": "maintain"}}`. It takes effect only over a committed
  `normal`; a committed `advise` (the kill switch) always wins. `maintain` can write the framework
  paths and run the maintainer command allowlist in `tools/guard/policy.json`.
- Changes to `tools/guard/`, `.claude/settings.json`, `.github/workflows/`, `.github/hooks/` and
  CODEOWNERS files are human-applied patches with a second reviewer (not enforced on this
  repository until it has a second maintainer; see "Commit conventions"): the guard blocks the
  assistant's write tools and its Bash write patterns from touching those paths in every mode. A
  change under `.github/workflows/` or `.github/hooks/`, or to a CODEOWNERS file, also trips the
  tripwire until a human commits it; the rendered `.github/instructions/` and similar trees that
  `maintain` writes do not. Raising a Salesforce CLI
  level (`sf.mode_level`, `sf.allowed_orgs`) is such a patch. The human applies and commits guard
  files together.
- The WS1 owner patches, `ai-context/ws1/patches/ci-ws1.patch` and
  `ai-context/ws1/patches/gitattributes-ws1.patch`, must be applied together. The CI patch adds the
  byte-comparing filler `--check` on Windows too; without the LF pin in `.gitattributes` a Windows
  checkout converts `demo/org/` to CRLF and that step fails.
- The WS2 owner patches (`ai-context/ws2/patches/`: `.gitignore`, the guard policy and its tests,
  and the CI workflow) went on after the WS1 patches; both sets are applied in `3fb9e73`.
- The WS11 owner patches (`ai-context/ws11/patches/`: the guard policy, its cases and the guard's
  modelling of `write_story.py`'s output, and the CI workflow) are **not applied yet**; apply them
  as `ai-context/ws11/patches/APPLY.md` gives. Until they land, CI runs none of the story checks,
  and the assistant runs `check_ac.py` and `validate_story.py` directly only in `maintain`.
  The guard's `normal` allowlist already admits what story-refine calls: `query.py edge-seeds`
  (read-only) and its writer `write_story.py`, which runs both checks in-process. That is
  Inferred from the policy; no story-refine run has gone through the guard in `normal` yet.
- Story promotion (`promote.py --story`) is the product owner's confirmation. The assistant never
  runs it to confirm a story and never supplies `--confirmed-by`.
- No model has run story-refine under Claude Code yet. Its eval case 002 has passed only on a
  hand-built draft fed through the writer, a smoke test of the writer, not of the skill.
- The WS10 owner patches (`ai-context/ws10/patches/`: the guard policy, its cases, the guard's
  modelling of `build_index.py --from-config` and `write_design.py`'s output, and the CI
  workflow) are **not applied yet**. They are cut on top of the WS11 patches, so apply WS11
  first, then WS10 as `ai-context/ws10/patches/APPLY.md` gives. Until they land, CI runs none of
  the new WS10 test scripts, and the assistant runs `validate_design.py` and `framework_config.py` directly
  only in `maintain`. `write_design.py` already runs in `normal` (the skill-scripts pattern), and
  `build_index.py --from-config` already runs there too: the guard models it as writing `index/`.
  `onboard.py` stays `maintain`-only after the patch; run it in your own terminal.
- The day-one workflow (refine, understand, design, assess, confirm) is in `docs/DESIGN.md`,
  "Day-one workflow". No model has run solution-design, or story-impact on a design option,
  under Claude Code yet; both are shown only by writer smoke tests. The owner's choice of option
  is `promote.py --option`, a human step like every promotion.
- Onboarding an existing codebase writes the rule baseline, `tools/code/baseline.json`, from
  `check_rules.py`; the baseline only shrinks. Onboarding's knowledge stubs go to
  `framework/knowledge/stubs/`, outside lint and rendering; a human fills one and moves it up a level.
- The WS8 owner patches (`ai-context/ws8/patches/`: the build-mode scope lock and tests-first,
  the guard-owned cores `tools/guard/trace_core.py` and `scope_core.py`, `.active-story` always
  blocked, the modelling of `start.py` and `write_change.py`, the `check_rules`/`check_trace`
  allowlist patterns, their cases, and the CI steps) are **not applied yet**. They are cut on top
  of WS11 and WS10, so the order is WS11, then WS10, then WS8, as
  `ai-context/ws8/patches/APPLY.md` gives, which also lists the owner decisions. Until WS8 lands,
  `check_trace.py` and `start.py` exit 2 (no core) and `build` allows no source write.
- `tools/impacts/package.py` and `start.py` are human steps: a maintainer builds the package
  from a confirmed story, design and impact and commits it; a human runs `start.py` in a real
  terminal and pastes the env lines. No package exists until the owner confirms DEMO-202's story,
  design and impact (`ai-context/OWNER-QUEUE.md` items 10 and 11). The builder never runs either.
- No model has run implement-story or the `builder` agent under Claude Code yet; they need a
  committed package. See "Scoped code writing" in `docs/DESIGN.md` for the honest limits.
- After applying guard patches, a human runs `python3 tools/guard/guard.py --rebaseline` once from a
  terminal, and again whenever `.git/config` or `.git/hooks/` legitimately change, and once inside
  every new git worktree (each worktree keeps its own baseline). Until then the tripwire blocks
  every write and non-read-only command. The guard blocks Bash lines that run it, and it also
  refuses to run without a terminal.
- The guard runs on every tool call, MCP tools included (see "What the guard guarantees" in
  `docs/DESIGN.md`). Any tool other than Bash that takes a `command` is blocked in every mode.
- The guard checks an internal 7-second deadline and blocks itself once past it; a cap of 64 glob
  words per line and a 20000-entry scan budget keep it under the 10-second hook timeout. Best
  effort, not a hard bound.
- In every mode, a Bash line with `$`, braces or a `[[:class:]]` bracket outside single quotes, or a
  heredoc, is blocked. Single-quote the text, or write it to a file under `ai-context/` (for a commit message:
  `git commit -F ai-context/<file>`).
- Code the assistant runs can bypass laptop controls (see `docs/DESIGN.md`, Layer 1). That is why
  the server-side layer (CODEOWNERS, branch protection, CI, review) exists and is the guarantee.
  Read "Modes" and "What the guard guarantees" before relying on the guard.
- Keep `docs/DESIGN.md` in step with reality: if you change a layer's behaviour, change the doc in
  the same PR.

## Backlog, in order

### Gate 1 hardening (do first)
- [x] `tools/guard/test_guard.py`: add a case that runs the wrapper with PATH cleared of every
      Python and asserts exit 2 (proves fail-closed on a laptop with no interpreter).
- [x] `tools/guard/guard.sh`: runs with an empty PATH (shell builtins only), and the hook is
      registered as `sh "$CLAUDE_PROJECT_DIR/tools/guard/guard.sh"`, so it needs no exec bit;
      `test_guard.py` covers both.
- [ ] `tools/index/build_index.py`: add parsers for custom metadata records, custom labels,
      named credentials, record types and FlexiPages; add `@AuraEnabled` method → LWC edges.
- [ ] `tools/index/query.py`: add `inventory` subcommand that prints `inventory.json` sections.
- [ ] Copilot hook registration under `.github/hooks/` pointing at the same guard; document the
      exact file Copilot expects once confirmed against current docs. Today (WS6) Copilot users
      get the rendered instructions but no guard; `docs/DESIGN.md`, "Copilot today", and
      `docs/ADOPTING.md` section 8 say so. `.github/hooks/` is an owner path.

### WS0 guard hardening
- [x] Four modes (advise, normal, build, maintain) with committed-`advise`-wins precedence.
- [x] Allowlist-based Bash per mode and a git subcommand allowlist, rules in `tools/guard/policy.json`.
- [x] Tripwire over guard, settings, CI workflow, GitHub hook and CODEOWNERS paths, `.git/config`,
      includes and hooks, with a human-only `--rebaseline`.
- [x] Final review fixes: glob words that expand to options, a 7-second internal deadline and one walk
      budget per call, `--amend` prefixes, framework-script output flags, every tool (MCP included)
      through the hook.
- [x] Extra fix round: shell expansion blocked in every mode, glob-word cap and charged glob scans,
      MCP verbs matched by whole name segments, unmodelled command tools blocked.
- [x] Salesforce CLI access levels (`none`, `offline`, `org-metadata`, `org-data`).
- [x] `.gitattributes` line-ending rules for the wrapper and guard files.
- [x] `docs/DESIGN.md`, `README.md` and this file describe the above.
- [ ] CODEOWNERS and branch protection on `tools/guard/`, `.claude/settings.json`, `.github/` and
      `CODEOWNERS`: the Layer 2 backstop. Human-owned; confirm it is enabled on the remote.
- [ ] First Windows CI run: confirms the Git Bash assumption (Inferred) and `guard.cmd` (Unverifiable
      until then).
- [ ] Optional: a human-owned jest config with `roots: ["<rootDir>/force-app"]` and
      `<rootDir>/ai-context/` in `testPathIgnorePatterns`.

### Skills
- [ ] `story-impact`: write `evals/expected/*.md` golden outputs for each eval case, produced by
      running the skill under Claude Code headless on the fixtures, reviewed by hand.
- [ ] `pr-reference-check`: the eval cases reference `fixtures/diffs/*.patch`; add a small runner
      that applies a patch to a temp branch so `extract_refs.py --base` works in CI.
- [ ] `release-impact`: new skill. Reads `inventory.json` plus user-supplied release-note text.
      Needs `references/input-checklist.md`, `scripts/baseline.py` (reads inventory, never greps),
      and three eval cases. Description ≤ 200 chars.

- [x] `story-refine` (WS11): skill, writer, eval cases 001, 002 and 003, `tools/stories/` checks,
      product-owner confirmation through `promote.py --story`.
- [ ] `story-refine`: run it under Claude Code on each of its eval cases and record the results;
      today only the writer smoke test exists.
- [x] `tools/code/check_trace.py` (WS8): built; it runs only after the WS8 guard patch, which
      ships its core, `tools/guard/trace_core.py`.
- [x] `implement-story` and the `builder` agent (WS8): skill, `write_change.py`, eval cases 001,
      002 and 003, `framework/agents/evals/builder.json`.
- [ ] `implement-story`: run it through the builder under Claude Code on each eval case once the
      owner's confirmations and a committed package exist, and record the results.
- [x] `solution-design` and starting points (WS10): skill, writer, eval cases 001, 002 and 003,
      `tools/designs/`, `tools/config/`, `tools/onboard/`, `demo/greenfield/`, the option choice
      at promotion.
- [ ] `solution-design`: run it, and story-impact on its recommended option, under Claude Code
      on each eval case and record the results; today only the writer smoke tests exist.
- [x] Rule-violation baseline in `onboard.py` for an existing codebase (WS8, from `check_rules.py`).

### Evals harness
- [x] `tools/evals/run_all.py` (WS3): runs one case N times with `claude -p` on a pinned model
      and collects each run into `ai-context/evals/<skill>-<case>/run-<i>/` with a `run.json`.
      `tools/evals/consistency.py` compares the runs on the must-agree fields. Assertions stay
      in `run_skill.py`, never in the runner.
- [ ] Live consistency series (owner): run `run_all.py` on the eval cases and compare with
      `consistency.py`; the assistant cannot run `claude -p` under the guard. No series has run,
      so no consistency figure for a skill is published. Operator notes: `tools/evals/README.md`.
- [ ] Optional: `promptfooconfig.yaml` that wraps the same cases and calls `run_skill.py` as a
      python assertion, for teams that already use Promptfoo.

### Packaging and publishing
- [x] Plugin manifest, hook registration and layout proposal drafted (WS7) in the maintainers'
      workspace, `ai-context/publish/drafts/` (`PLUGIN-LAYOUT.md`).
- [ ] Owner: pick the plugin layout, place the drafted files, run `claude plugin validate`, and
      tag the first release. Until then a full copy-in is the only install route.
- [x] `CHANGELOG.md` started at 0.1.0 (unreleased); `CONTRIBUTING.md` and `SECURITY.md` added.
- [x] `docs/ADOPTING.md` (the adoption guide) and `demo/WALKTHROUGH.md` with its deterministic
      check, `tools/demo/walkthrough_check.py` (WS5).
- [x] Measurement kit, `demo/measure/` (WS4). No time-saved figure until a measured baseline is
      committed with its source.

## Questions to resolve with the guild, not alone

- Exact Copilot hook file format and location for the organisation's Copilot version.
- Whether the org's SAST tool is updated for `WITH USER_MODE` (Checkmarx historically was not).
- The real managed-package namespace list for `namespaces.json`.

## Commit conventions

Small PRs, one layer at a time. A PR touching `tools/guard/` or `.claude/settings.json` needs a
second reviewer. Branch protection can enforce that only with at least two maintainers; until
this repository has a second maintainer the rule is not enforced here, and such a change merges
on one maintainer's review (`CONTRIBUTING.md`, "Review rules"). Render output is committed
alongside its source change.

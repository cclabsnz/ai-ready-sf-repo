# Changelog

All notable changes to this framework are recorded here. Versions follow `VERSION`. A release
date is set when the release is tagged.

## [0.1.0] - Unreleased

The first published version. Each entry names what a workstream delivered; the commits and
`docs/DESIGN.md` hold the detail.

### Foundation (initial import)

- One source tree, `framework/`, rendered into `.claude/` and `.github/` by
  `tools/build/render.py`, with `--check` for drift and `tools/build/lint.py` for skill, agent and
  knowledge hygiene.
- The first skills, `story-impact` and `pr-reference-check`, with eval cases, and the skill and
  agent eval runners in `tools/evals/`.
- The real-data scan, `tools/guard/scan_data.py`, run pre-commit and in CI.

### Guard modes and hardening (WS0)

- The guard runs as a PreToolUse hook with advise, normal, build and maintain modes. A committed
  `advise` always wins, so it serves as the kill switch.
- Its rules live in `tools/guard/policy.json`, and any internal error fails closed.
- Bash is allowlist-based outside `advise`. Commands are parsed into segments, and their write
  targets are checked against the mode's paths.
- Shell expansion and heredocs are blocked in every mode, and glob words have a budget.
- Pushes, `curl`, `wget` and `ssh` are blocked. Salesforce CLI commands are tiered by access
  level, and org-changing ones are never allowed.
- A tripwire covers the guard, settings, CI, GitHub hooks, CODEOWNERS and git config, with a
  human-only re-baseline.
- Wrappers for macOS, Linux and Windows always exit 0 or 2, including when no Python is found.
- `docs/DESIGN.md` states the two layers of protection: laptop best effort and server guarantee.

### Synthetic Sales/Service codebase and index (WS1)

- `demo/org/` is a synthetic Sales/Service org. It has escalation and customer-tier chains,
  deliberate signs of age, and seeded filler for realistic scale.
- `demo/stories/` holds the demo stories, each with a reviewed answer key and a check that the
  index finds what the key lists.
- The index parses validation rules, record types, flow Apex actions, FlexiPages, permission-set
  objects, trigger-to-object and class-to-class edges, invocable and `@AuraEnabled` methods, and
  sharing declared in code.
- `query.py` follows consumers up to three hops, and parse errors no longer stop a build.

### Impact record, register and overlap checks (WS2)

- `impact.json` has a schema and a validator.
- The register in `impacts/` shows overlaps, scope and a static view. A human promotion step adds
  records to it.
- A PR check flags code overlap and scope drift.
- `story-impact` writes `impact.json` and story-time overlaps, and its eval asserts both.

### Story refinement (WS11)

- `story.json` has a schema and a check for vague acceptance criteria.
- The `story-refine` skill comes with a writer, eval cases and the `discovery-lead` agent.
- A product owner confirms a refined story at promotion.
- The index adds picklist values and deterministic edge seeds.
- `validate_story.py` and `check_ac.py` join the `normal` and `build` allowlists, the guard models
  where `write_story.py` writes, and CI runs the story checks.

### Starting points and the day-one workflow (WS10)

- `.ai-framework.json` holds project configuration, and the non-negotiable is reworded.
- Onboarding covers both starting points: an existing codebase and a greenfield skeleton in
  `demo/greenfield/`.
- The `solution-design` skill always offers "do nothing" and recommends one option, and the
  `analyst` agent runs it.
- `story-impact` assesses the recommended option, and promotion records the choice.
- `validate_design.py` and `framework_config.py` join the `normal` and `build` allowlists, and the
  guard models `build_index.py --from-config` and `write_design.py`'s outputs. CI runs the config,
  onboarding and design checks, and `impact-checks` builds its index from the base branch's
  `sourceRoot`.

### Scoped code writing (WS8)

- `tools/code/check_rules.py` runs deterministic Apex rule checks against a baseline that only
  shrinks.
- `tools/code/check_trace.py`, the test traceability check. Its matching lives in the
  guard-owned core, `tools/guard/trace_core.py`, which the guard's tests-first rule uses too.
- `tools/impacts/package.py` makes a build package from a confirmed story, design and impact.
  `tools/impacts/start.py`, run by a human in a terminal, starts a build session from a
  committed package and writes `ai-context/.active-story`; the guard refuses it from the
  assistant in every mode.
- The guard's scope lock in `build` mode: a source write must be under the committed
  `sourceRoot` and equal a path in the active story's build package committed at `HEAD`, with
  `AI_FRAMEWORK_STORY` equal to `.active-story`. Tests first: code stays blocked until every
  criterion id is named in a `scope.tests` file. The package is read by the guard-owned
  `tools/guard/scope_core.py`. `check_rules.py --from-config` and `check_trace.py` join the
  `normal` and `build` allowlists.
- The `implement-story` skill and the `builder` agent, which write tests first inside the package
  scope. No package is committed in this repo yet, so neither has run.
- CI runs the code tests, the builder's sample eval and `check_rules.py --from-config` in
  `guard-and-lint`. `impact-checks` fails on a new rule finding or a grown baseline, and runs the
  trace check, report-only, for each changed build package.

### Consistency eval (WS3)

- `tools/evals/consistency.py` compares the must-agree fields across N runs of a skill and
  reports the agreement.
- `tools/evals/run_all.py` builds the live `claude -p` runs, which the owner performs. No live
  series has run yet, so no consistency figure for a skill is published.
- `demo/expected/consistency-fixture/` holds hand-built runs that show the grid's format; they
  are not model output.

### Measurement kit (WS4)

- `demo/measure/` scores an impact against an answer key and times a run from a session log.
- It includes an empty manual-baseline template. No time-saved figure is published.

### Walkthrough and adoption guide (WS5)

- `demo/WALKTHROUGH.md` goes through the framework on the demo org. Each step is labelled
  deterministic, needs Claude Code, or needs owner confirmations.
- `demo/expected/` holds the expected output of the deterministic steps, and
  `tools/demo/walkthrough_check.py` re-runs those steps and diffs them (`--show` prints one
  step's output for a reviewed refresh).
- `docs/ADOPTING.md` takes the framework into an adopter's own repository.
- `tools/index/build_index.py` walks folders and files in sorted order, so the order of nodes
  and edges in the index no longer depends on the filesystem.

### Copilot stance (WS6)

- No Copilot hook is registered. Copilot users get the rendered instructions and files under
  `.github/`, but no guard; the server-side controls and the instructions govern Copilot work.
- `docs/DESIGN.md` ("Copilot today") and `docs/ADOPTING.md` say so. The earlier claim that the
  guard was mirrored as a Copilot hook is corrected.

### Versioned install and public-repo readiness (WS7, WS9)

- This changelog, `CONTRIBUTING.md` and `SECURITY.md` are added.
- The MIT LICENSE, a CODEOWNERS covering the control paths, and issue and PR templates are
  added. The Claude Code plugin manifest and a layout proposal are drafted for the owner, who
  picks the layout; until then a full copy-in is the install route.
- An owner role replaces the placeholder owner in the knowledge files.
- `docs/DESIGN.md` loses its byline.

### Publish readiness (guard and CI)

- **Scanner packs:** `tools/guard/scan_data.py` groups its patterns into packs. The default pack
  is always on; the `nz` and `ncino` packs apply only when `tools/guard/scan_packs.json` names
  them, and it ships with the default pack only. A broken pack file exits 2. Its tests are in
  `tools/guard/test_scan_data.py`.
- **`scan_data.py --tracked`:** scans only the files git tracks. CI's real-data scan moved from
  `--all` to `--tracked`.
- **The `run_all` refusal:** the guard refuses `tools/evals/run_all.py` in every mode, so only the
  owner starts live runs.
- **CI:** the scanner, consistency, live-runner, measurement and walkthrough checks run in
  `guard-and-lint`, on Ubuntu and Windows. An optional `live-consistency` job can be started by
  hand from the default branch. It has not run, and on a fresh runner the guard has no baseline,
  so it is not expected to produce skill outputs; what to do with it is an owner decision.

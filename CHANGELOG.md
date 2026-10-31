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

### Starting points and the day-one workflow (WS10)

- `.ai-framework.json` holds project configuration, and the non-negotiable is reworded.
- Onboarding covers both starting points: an existing codebase and a greenfield skeleton in
  `demo/greenfield/`.
- The `solution-design` skill always offers "do nothing" and recommends one option, and the
  `analyst` agent runs it.
- `story-impact` assesses the recommended option, and promotion records the choice.

### Scoped code writing (WS8)

- `tools/code/check_rules.py` runs deterministic Apex rule checks against a baseline that only
  shrinks.
- `tools/code/check_trace.py` checks test traceability over a guard-owned core.
- A build package is made from a confirmed story, design and impact. A build session starts only
  from a committed package.
- The `implement-story` skill and the `builder` agent write tests first, inside the package
  scope.

### Consistency eval (WS3)

- `tools/evals/consistency.py` compares the must-agree fields across N runs of a skill and
  reports the agreement.
- `tools/evals/run_all.py` builds the live `claude -p` runs, which the owner performs.

### Measurement kit (WS4)

- `demo/measure/` scores an impact against an answer key and times a run from a session log.
- It includes an empty manual-baseline template. No time-saved figure is published.

### Versioned install and public-repo readiness (WS7, WS9)

- This changelog, `CONTRIBUTING.md` and `SECURITY.md` are added.
- The Claude Code plugin manifest, LICENSE, CODEOWNERS and the issue and PR templates are
  drafted for the owner to place.
- An owner role replaces the placeholder owner in the knowledge files.
- `docs/DESIGN.md` loses its byline.

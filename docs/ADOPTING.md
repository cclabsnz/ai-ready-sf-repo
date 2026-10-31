# Adopting the framework in your own Salesforce repo

This guide takes the framework from this reference repo into your own Salesforce repository. It
covers installing a pinned version, the policy and modes, the server-side controls, per-laptop
onboarding, the guild, your org-facing CI, measuring your own baseline, and what Copilot users
get today.

Claims carry the repo's labels:

- **Confirmed:** shown by a file or a run in this repo.
- **Inferred:** reasoned from evidence, not shown by a run.
- **Unverifiable:** depends on something this repo cannot check, such as Claude Code's plugin
  behaviour or your GitHub organisation's settings.

Try the [walkthrough](../demo/WALKTHROUGH.md) on the demo first. Everything below assumes you
have seen the guard test pass on your machine.

## 1. Install a pinned version

### What goes where

A Claude Code plugin can carry skills, agents and hooks. It cannot carry your project's rules,
and the skills call scripts by repo-relative paths that the guard admits only from your project.
So some parts always live in your repo.

The source for the plugin format is the maintainers' research notes,
`ai-context/publish/plugin-format.md`. They are taken from search summaries of the Claude Code
docs, not from the pages themselves. Every plugin claim below rests on those notes only.

- **The notes are not in your clone.** `ai-context/` is the maintainers' git-ignored workspace,
  and so are the other `ai-context/` paths named in this guide.
- **The pages the notes summarise:**
  - https://code.claude.com/docs/en/plugins-reference
  - https://code.claude.com/docs/en/plugins/create
  - https://code.claude.com/docs/en/hooks
  - https://code.claude.com/docs/en/plugins/marketplace-reference
  - https://code.claude.com/docs/en/plugins/install
- **Check them against the pages.**

| Part | In the plugin | Copied into your repo | Why |
| --- | --- | --- | --- |
| Skills (`SKILL.md` and references) | Yes | Only on the full copy-in route | Plugins carry skills (plugin-format notes, "Manifest and layout") |
| Agents | Yes | Only on the full copy-in route | Same |
| Guard hook | Possible (drafted) | `.claude/settings.json` registers it from `tools/guard/` | The project registration is the path `test_guard.py` tests. A plugin-hosted guard is **Unverifiable** until tested |
| Rules: rendered `CLAUDE.md`, `.github/instructions/` and `framework/rules/` | No | Always | The notes don't document rules or CLAUDE.md as a plugin component, so they have to be copied in. **Inferred** from that absence |
| `tools/` (index, impacts, stories, designs, code, guard, build, evals, config, onboard) | No | Always | Skills run `python3 tools/...` from the project root, and the guard's allowlist matches those project-relative paths (`tools/guard/policy.json`). **Confirmed** from the policy |
| Skill writer scripts (`framework/skills/<name>/scripts/`) | Copied, but not run from there | Always | The guard admits `python3 framework/skills/<name>/scripts/<script>.py` by that exact path. **Confirmed** from the policy |
| `.claude/settings.json` (mode, hook, deny rules) | No | Always | The guard reads the committed mode from your project. A missing or unreadable mode counts as `advise`. **Confirmed** from the guard code |
| `.ai-framework.json`, `namespaces.json`, `.gitignore` rules, `.pre-commit-config.yaml`, CI workflow | No | Always | Project config |
| `VERSION` | Plugin manifest `version` (drafted) | Always | `run_all.py` records `frameworkVersion` from the checkout's `VERSION`, so keep it equal to the tag you installed |

### Route A: the plugin at a tag, plus the copy-in

**Not available yet.** This repo has no `.claude-plugin/` and no release tag. The owner publishes
both (queued in `ai-context/OWNER-QUEUE.md`): the drafted manifest and marketplace, then the tag
`v0.1.0`. Every command in this route is **Unverifiable** until then. Check it against the Claude
Code plugin docs and `claude plugin validate`.

1. Add the marketplace pinned to a tag, in Claude Code:

   ```
   /plugin marketplace add <your-org>/<repo>#v0.1.0
   ```

2. Install the plugin. The drafted names are a plugin `ai-ready-sf-framework` in a marketplace
   `ai-ready-sf` (drafted in the maintainers' workspace); the published names may differ.

   ```
   /plugin install ai-ready-sf-framework@ai-ready-sf
   ```

3. From a checkout of the same tag, copy the parts in the table above into your repo:
   `tools/`, `framework/` (at least `rules/` and each skill's `scripts/`), the rendered
   `CLAUDE.md`, `.github/instructions/`, `.claude/settings.json`, `VERSION`, the `.gitignore`
   rules and `.pre-commit-config.yaml`. Then follow "After copying" below.

Known open points on this route, all **Unverifiable** or **Inferred** until the owner tests them:

- **The guard hook can run twice.** If both the plugin hook and the project hook in
  `.claude/settings.json` are registered, the guard probably runs twice per tool call. Both runs
  block the same things, at twice the latency (**Inferred**).
- **Which hook to keep is a decision for your guild.** `test_guard.py` tests only the project
  registration.
- **The tripwire does not watch the plugin's copy.** It watches project paths (`tools/guard`,
  `.claude/settings.json`, `.github/workflows`, `.github/hooks`, `CODEOWNERS`), not the plugin
  cache.
- **Duplicate skills.** How Claude Code resolves a skill that exists both in the plugin and in
  `.claude/skills/` is not covered by the notes. On this route, leave the rendered
  `.claude/skills/` and `.claude/agents/` out of your repo.

### Route B: full copy-in (works today)

From a checkout of the version you want (`git checkout v<version>` once tags exist; the default
branch until then):

1. **Copy these into your repo:**
   - `tools/`
   - `framework/`
   - `CLAUDE.md`
   - `.claude/`, minus any `settings.local.json`
   - `.github/instructions/`, `.github/knowledge/`, `.github/skills/`, `.github/agents/` and
     `.github/hooks/`
   - `.github/workflows/framework-ci.yml`, then adapt it (see section 6)
   - `VERSION`, `.pre-commit-config.yaml` and `.gitattributes`
   - the rules from `.gitignore`: `data/`, `/ai-context/`, `/index/`, `!/CLAUDE.md`,
     `.claude/settings.local.json`
2. **Leave these out,** because they belong to the demo:
   - `demo/` and `fixtures/`
   - the records in `impacts/`; keep only `impacts/squads.json` as a template and list your own
     squads in it
   - `framework/knowledge/*.md`; write your own knowledge files, each with an owner role and a
     date
   - `tools/code/baseline.json`; onboarding writes yours
3. **Commit the copy** as one reviewed PR that names the version.

Upgrading is the same copy from a newer tag, reviewed as one PR. Rolling back is the copy from an
older tag. `CHANGELOG.md` lists what each version changes.

### After copying

Run these in your own terminal. Windows uses `py -3` in place of `python3`; the Windows path is
**Inferred, not yet tested** in this repo's CI.

```sh
python3 tools/onboard/onboard.py --starting-point existing --owner-role "<role>" --source-root <folder holding force-app> --write-config --replace
python3 tools/build/render.py
python3 tools/build/lint.py
python3 tools/guard/test_guard.py
python3 tools/guard/scan_data.py --all
python3 tools/guard/guard.py --rebaseline
```

- **`onboard.py`, existing codebase:**
  - writes `.ai-framework.json`;
  - builds `index/`;
  - writes knowledge stubs to `framework/knowledge/stubs/`, with `--owner-role` as their owner;
  - writes your rule baseline, `tools/code/baseline.json`. `--replace` overwrites the demo's
    baseline.
- **`onboard.py`, no codebase yet:** use `--starting-point greenfield`. It needs no
  `--owner-role` and writes no baseline. See "Two starting points" in the README.
- **`render.py`** regenerates `CLAUDE.md`, `.claude/` and `.github/` from your `framework/`.
  Edit `framework/` only, never the rendered trees.
- **The test must end with `<n> passed, 0 failed`.**
- **Run the re-baseline yourself,** in a real terminal, before opening Claude Code in the repo.

## 2. The policy file and modes

**The guard's rules are data, in `tools/guard/policy.json`.** They hold:

- the blocked patterns;
- the git subcommand allowlist;
- the fetch allowlist;
- the tripwire paths;
- the always-blocked write paths;
- each mode's write paths and Bash allowlist;
- the Salesforce CLI levels.

Change it only through a reviewed PR. The assistant cannot write `tools/guard/`.

| Mode | For | Writes | Set by |
| --- | --- | --- | --- |
| `advise` | Everyone, when the kill switch is pulled | Nothing; read-only commands only | Committed `.claude/settings.json` |
| `normal` | Every squad member (the committed default) | `ai-context/`, `index/` | Committed `.claude/settings.json` |
| `build` | A developer on one story | `normal`, plus the story's build-package scope once the WS8 guard patch is in your copy | A personal `.claude/settings.local.json`, after `start.py` |
| `maintain` | A framework maintainer | Framework paths (`framework/`, `tools/` except `tools/guard/`, `docs/`, rendered trees, ...) | A personal `.claude/settings.local.json` |

- **The committed mode is the ceiling.** A committed `advise` always wins. A local mode applies
  only over a committed `normal`. A committed `build` or `maintain` is treated as `advise`.
- **The kill switch** is one line, `"AI_FRAMEWORK_MODE": "advise"`, in the committed
  `.claude/settings.json`. It is a programme-wide pause that touches no laptop.
- **Salesforce CLI levels** are `none`, `offline` (the default outside `advise`), and the opt-in
  `org-metadata` and `org-data`.
  - To raise a level, change `sf.mode_level` and list sandbox aliases in `sf.allowed_orgs`, in a
    reviewed PR.
  - Never list a production alias.
  - `org-data` puts real org data into the assistant's context.
  - Login, deploy, data writes and `apex run` stay blocked at every level.

`.ai-framework.json` holds the repo's own settings, read by `tools/config/framework_config.py`:

- `startingPoint`: `existing` or `greenfield`.
- `sourceRoot`: the folder holding `force-app/` and `pkg-*/`.
- `impactChecks`: `noImpact` and `outOfScope`, each `comment` (the default) or `fail`. Every
  check reports without failing unless you opt a finding class into `fail` here.

The full rules are in `docs/DESIGN.md`, under "Modes", "Salesforce CLI access levels" and "What
the guard guarantees".

## 3. CODEOWNERS, branch protection and required reviews

The guard is a laptop control, best effort. The hard guarantee is on the server: CODEOWNERS,
branch protection, CI, secret scanning and human review of every PR. This repo cannot set that up
for you. Until you enable and confirm it, that layer is a plan, not a guarantee.

### CODEOWNERS

Put the guild on the framework paths and on every control path. GitHub applies the last matching
line, so the narrower control paths come after `/tools/`:

```
/framework/            @<your-org>/<guild-team>
/tools/                @<your-org>/<guild-team>
/impacts/              @<your-org>/<guild-team>
/.claude/              @<your-org>/<guild-team>
/.github/instructions/ @<your-org>/<guild-team>
/.github/agents/       @<your-org>/<guild-team>
/.github/skills/       @<your-org>/<guild-team>
/.github/knowledge/    @<your-org>/<guild-team>
/.github/hooks/        @<your-org>/<guild-team>
/.github/workflows/    @<your-org>/<guild-team>
/tools/guard/          @<your-org>/<guild-team>
/CODEOWNERS            @<your-org>/<guild-team>
/.ai-framework.json    @<your-org>/<guild-team>
```

`docs/DESIGN.md` ("What the guard guarantees") names the control paths: `tools/guard/`,
`.claude/settings.json`, `.github/` and `CODEOWNERS`. This repo's own `CODEOWNERS` lacks
`/.github/workflows/`, `/tools/guard/` and `/CODEOWNERS` today. The corrected version is drafted
for the owner, so don't copy the current file as a model.

### Branch protection on your default branch

GitHub, Settings → Branches → a branch protection rule for the default branch (or an equivalent
ruleset). The setting names are as GitHub's UI shows them at the time of writing (**Inferred**;
GitHub renames settings from time to time).

| Setting | Value |
| --- | --- |
| Require a pull request before merging | On |
| Required number of approvals before merging | 1 (the minimum; raise it when the guild grows) |
| Dismiss stale pull request approvals when new commits are pushed | On |
| Require review from Code Owners | On |
| Require approval of the most recent reviewable push | On |
| Require status checks to pass before merging | On |
| Require branches to be up to date before merging | On |
| Required status checks | The jobs of `.github/workflows/framework-ci.yml`: `guard-and-lint (ubuntu-latest)`, `guard-and-lint (windows-latest)`, `impact-checks`, `secrets`, plus your org-facing jobs (section 6) |
| Require conversation resolution before merging | On |
| Do not allow bypassing the above settings | On (administrators included) |
| Allow force pushes | Off |
| Allow deletions | Off |

- **Status check names.** They are taken from the workflow's job ids and its `os` matrix. GitHub
  shows matrix jobs with the matrix value in brackets. Confirm the exact names in the PR checks
  list after the first run (**Inferred**).
- **The workflow's `paths` filter.** The workflow runs only on PRs that touch the listed paths. A
  required check whose workflow never starts stays pending, and the PR cannot merge
  (**Inferred** from GitHub's documented behaviour). Either drop the `paths` filter or add a
  catch-all job; that choice belongs to whoever owns the workflow.
- **Two maintainers at least.** Required reviews need two maintainers, because an author cannot
  approve their own PR. With one maintainer the rule cannot be met. This reference repo is in that
  state today, so the second-reviewer rule is not enforced on the repo itself.

Also in Settings:

- **Code security:**
  - secret scanning: on;
  - push protection: on;
  - private vulnerability reporting: on (see `SECURITY.md`).
- **Actions → General:**
  - workflow permissions: read repository contents only;
  - for fork pull requests, require approval before workflows run.

  The `impact-checks` job asks for its own `pull-requests: write`.

## 4. Per-laptop onboarding

Every squad member, once per laptop, in a clone of your repo:

1. Run the guard test: `python3 tools/guard/test_guard.py` (Windows: `py -3 ...`). The last line
   must read `<n> passed, 0 failed`. A squad is not onboarded until every member has passed it.
2. Record the tripwire baseline in a real terminal: `python3 tools/guard/guard.py --rebaseline`.
   Run it again in every new git worktree, and after any legitimate change to `.git/config` or
   `.git/hooks/`.
3. Build the index: `python3 tools/index/build_index.py --from-config`.
4. Run the sample agent eval:
   `python3 tools/evals/run_agent.py --log framework/agents/evals/sample-run.jsonl --spec framework/agents/evals/analyst.json`.
5. Read `framework/rules/00-precedence.md`. Know who the guild is: the `CODEOWNERS` team.
6. Install the pre-commit hooks (`.pre-commit-config.yaml` runs `scan_data.py` and gitleaks), if
   your programme uses pre-commit.

The mode switch, the kill switch and the guard's block messages are explained in the README
("Using the modes", "Troubleshooting the guard").

## 5. The guild operating model

From `docs/DESIGN.md`, "Packaging and operating model":

- **Ownership.** A guild of two or three people drawn from different squads, named in CODEOWNERS
  for `framework/`, `tools/` and the rendered trees. Every PR into those paths needs one guild
  reviewer.
- **Versioning.** Semantic:
  - patch: fact or template changes;
  - minor: a new skill or new eval cases;
  - major: a change to the evidence taxonomy, the output paths or the control plane.

  Squads stay on the current major.
- **Contradictions.** When a squad's finding contradicts a knowledge file:
  - the PR records both claims with evidence;
  - the file's owner arbitrates within the sprint;
  - the superseded claim stays as a dated correction with its reason.

  The index settles anything countable.
- **Cadence.**
  - Fortnightly, 30 minutes, with a rotating chair: stale knowledge files, failed evals, open
    contradictions and proposed skills.
  - Monthly: a one-page health note to squad leads, with eval pass rates and usage.
- **Decommissioning.** A skill with no use in two sprints and no owner moves to
  `framework/attic/` and leaves the render. The index and the control plane stay.
- **The kill switch** lives in one committed line, so the guild can pause the whole programme in
  minutes.

## 6. Your org-facing CI jobs

This repo has no org: nothing here compiles Apex, deploys or runs Apex tests. Those jobs are
yours.

- **Deploy validation:** a check-only deploy of the PR's metadata to a CI sandbox.
- **Apex tests:** the PR's tests in that sandbox, with your coverage gate.
- **Credentials:** held only by CI, as encrypted secrets scoped to the job, for sandboxes only.
  The assistant never holds or sees them. Under the guard, the assistant cannot run these jobs:
  the guard blocks every Salesforce CLI login, deploy and Apex run in Claude Code, at every
  level, as a best-effort laptop control. A human, or a Copilot session, can still run them on
  a laptop. Keep them in CI, with the credentials CI holds.
- **Forks:** run the org-facing jobs on trusted branches only, never on fork PRs, so a fork
  cannot reach your secrets.
- **Branch protection:** mark the jobs as required status checks (section 3).

Keep the framework's own jobs beside them. `guard-and-lint` runs on Ubuntu and Windows: the guard
test, the data scan, lint, the render check, the index and impact tests. `impact-checks` runs the
PR check from the base branch. `secrets` runs gitleaks. Drop the demo-only steps (the filler
`--check`, the answer-key tests) and point the index build at your `sourceRoot`. The workflow is a
control path: it changes only by a reviewed PR from a code owner.

## 7. Measuring your own baseline

`demo/measure/` measures an assistant run and a person working by hand in the same way. It
publishes no time-saved figure.

1. Write the answer key for a story before anyone starts, in the shape of
   `demo/stories/*.answer.json`.
2. Score each impact, the assistant's `impact.json` or a person's file of the same shape:
   `python3 demo/measure/score.py <impact.json> --key <answer.json>`. It prints found, missed and
   extra, with recall and precision computed by the script.
3. Time it. For an assistant run, `python3 demo/measure/timing.py <session.jsonl>` reads the
   Claude Code session transcript. For a person, use a clock. The reviewer records review time.
4. Copy `demo/measure/baseline-template.md` and keep one row per attempt, with its source.

Publish a time-saved figure only from committed rows with their source, computed by a script, not
typed. `demo/measure/README.md` has the method in full.

## 8. What Copilot users get today

- **They get:** the rendered instructions in `.github/instructions/` (from `framework/rules/`,
  with `applyTo` from each rule's scope), plus the rendered knowledge, skills and agents under
  `.github/`, as files. How Copilot uses the skill and agent files is Unverifiable here.
- **They don't get the guard.** Copilot users get no hook, no allowlist and no tripwire. No
  Copilot hook is registered: `.github/hooks/` holds only a README describing how one could be.
  Copilot is governed by the instructions and by the server-side controls in section 3.
- **The same scripts.** All framework logic lives in `tools/`, so a Copilot user runs the same
  scripts from a terminal. Nothing on the laptop stops a Copilot session from running a command
  the guard would block in Claude Code. Say so in your onboarding checklist.

## 9. Owner patches: a pattern for adopters

In this repo the assistant never edits the controls: `tools/guard/`, `.claude/settings.json`,
`.github/workflows/`, `.github/hooks/`, CODEOWNERS and `.git/`. Changes to them arrive as patches
that a human applies, in order:

1. **One patch set per change,** under `ai-context/<workstream>/patches/`, with an `APPLY.md`
   that gives the order, the commands and the owner decisions.
2. **Each patch is cut on the previous one.** In this repo the order is WS11, then WS10, then
   WS8, then the publish patches. Each is cut against the ones before it, so they apply only in
   that order.
3. **The human applies, reviews and commits** the guard files and their tests together, from a
   prepared commit message (`git commit -F ...`).
4. **Re-baseline** from a real terminal after each commit that touches the guard or git config.
5. **Track it in a queue.** Here, `ai-context/OWNER-QUEUE.md` (in the maintainers' git-ignored
   workspace) lists every human-only step top to bottom, so nothing waits silently. Keep yours
   wherever your programme tracks owner actions.

Use the same pattern for your own guard and CI changes: proposals as patches, a human applies
them, a second reviewer approves through CODEOWNERS, and the queue shows what is pending.

## What this guide does not claim

- **Plugin behaviour beyond the format notes is Unverifiable.** That covers installing, pinning,
  hook resolution and duplicate skills. `claude plugin validate` and a real install settle it.
- **Windows is Inferred.** The guard's Windows path, and the `py -3` commands, wait on the first
  Windows CI run.
- **The GitHub UI setting names are Inferred.** Your organisation may also enforce settings that
  override these.

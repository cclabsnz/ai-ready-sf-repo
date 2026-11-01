# Contributing

Thank you for helping. This framework is used to make Salesforce metadata legible to an AI
assistant without giving it org access, letting it invent a field or letting it leak a record. Read
[docs/DESIGN.md](docs/DESIGN.md) first. Its premise and principles decide most review questions.

## Before you start

- Open an issue first, using the bug or skill-proposal template, so the scope is agreed before
  any code is written.
- Edit `framework/`, never the rendered `.claude/` or `.github/` trees. `tools/build/render.py`
  writes those trees, and CI fails on drift.
- All tooling is stdlib Python 3. Don't add dependencies.
- Fixtures, demo data and eval cases are synthetic. Record names, IDs and emails must not match any
  real record. Use reserved example domains for emails and fictional squad names and story ids.

## Proposing a skill

A skill lives in `framework/skills/<name>/` and has a standard anatomy:

| Part | What it holds |
|---|---|
| `SKILL.md` | Front matter with `name` and a `description` of 200 characters or fewer that says when to use the skill and what it is not for, then the method. |
| `references/input-checklist.md` | What the skill needs before it starts, and what it does when an input is missing. |
| `references/` (other files) | Method detail the skill loads on demand. |
| `scripts/` | Stdlib Python for every step a script can do, such as writing the output, validating it or querying the index. Scripts print JSON or markdown and write only under `ai-context/`. |
| `evals/cases/` | At least 3 eval cases. Each case has an input and deterministic assertions, such as references that must appear, labels on every claim, banned phrases and cited `path:line` that must exist. |

Rules for the content:
- **Deterministic before probabilistic.** If a script can do a check, a script does it, and the
  model only interprets the result.
- **Evidence and labels.** Every claim carries evidence (`path:line`, or zero hits for a stated
  pattern) and one of the labels Confirmed, Inferred or Unverifiable.
- **Counts come from scripts.** Anything countable comes from `tools/index/query.py`, never from
  prose.
- **Neutral wording.** Skills and tools produce evidence and options and name the owner role who
  decides. They never approve, vote, deploy or push.
- **No org facts in skills or agents.** Org facts belong in the index or in knowledge files, which
  are treated as leads to re-verify.

## Proposing an agent

An agent lives in `framework/agents/<name>.md`. It lists its tools and states its posture and the
skills it runs, with no persona prose. Add a trajectory eval under `framework/agents/evals/`, with
must-call, must-not-call and must-block assertions over a tool-call log, run by
`tools/evals/run_agent.py`.

## Checks to run before every commit

```
python3 tools/build/render.py
python3 tools/build/render.py --check
python3 tools/build/lint.py
python3 tools/guard/scan_data.py --tracked
```

Check each exit code directly. Don't pipe the data scan, because a pipe hides its exit code. A hit
from the scan blocks the commit.

`--tracked` scans only the files git tracks, as CI does, so your git-ignored `ai-context/` and
`data/` are never read. (`--all` walks the whole working tree, those folders included.) The
default pack of patterns is always on. The `nz` and `ncino` packs apply only when
`tools/guard/scan_packs.json` names them, and this repo ships that file with the default pack
only. Fix the data, and don't add an exemption for real-looking values.
Also run the tests for every tool you touch (`python3 tools/<area>/test_<name>.py`) and the skill's
eval cases (`python3 tools/evals/run_skill.py`).

## Every behaviour change gets a guard or eval case

- A fix or change to a skill adds or updates an eval case that would have failed before the change.
- A fix or change to the guard adds a case to `tools/guard/test_guard.py`.
- A fix or change to a tool adds a test to that tool's `test_*.py`.

## Owner patches: guard, settings, CI and CODEOWNERS

The assistant can never write `tools/guard/`, `.claude/settings.json`, `.github/workflows/`,
`.github/hooks/`, CODEOWNERS files or `.git/`. Changes there arrive as patch files, for example
under `ai-context/<work>/patches/`, with an `APPLY.md` that gives the order and the commands. A
human applies them, reviews them and commits the guard files together, then runs the tripwire
re-baseline from a terminal. Say in your PR description which owner patches it depends on or adds.

## Review rules

- Every PR is reviewed by a human. CODEOWNERS routes `framework/`, `tools/`, `impacts/`, the
  rendered trees and the control paths (`tools/guard/`, workflows, GitHub hooks, CODEOWNERS
  itself) to the maintainers. GitHub enforces it once branch protection requires code-owner
  review on the remote.
- Changes to the guard, settings, CI, GitHub hooks and CODEOWNERS need a second reviewer.
  Branch protection can enforce that only with at least two maintainers. Until this public
  repository has a second maintainer, the second-reviewer rule is not enforced here, and a change
  merges on one maintainer's review. An adopting team enforces it on its own remote.
- CI must pass. That covers the guard tests, render check, lint, index and tool tests, the code
  rule checks on `demo/org/` and the data scan.
- Rendered output is committed in the same PR as its source change.
- `docs/DESIGN.md` changes in the same PR as any change to a layer's behaviour.
- Keep PRs small, with one layer at a time.

## Commit messages

- Use the form `area: lowercase summary`, where the area is the part of the repo or skill the
  change is about, for example `guard:`, `index:`, `impacts:`, `story-refine:` or `docs:`.
- Keep the summary short, without a trailing full stop, and add a body when the reason isn't
  obvious from the diff.
- No attribution or co-author lines are required.

## Reporting a security problem

Don't open a public issue for a guard bypass. See [SECURITY.md](SECURITY.md).

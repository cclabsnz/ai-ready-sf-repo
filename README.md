# AI-ready Salesforce repo (reference)

A reference way of working for large Salesforce programmes that let AI assistants (Claude Code
now, GitHub Copilot next) analyse and, later, build. It is for enterprise architects and squad
leads deciding whether and how to adopt AI across several build squads. Everything a squad wants
from the assistant (impact analysis, PR review, discovery) consumes one capability: a
deterministic, commit-stamped index of the checkout. A guard on every tool call keeps the
assistant inside fixed limits. You clone it, run it on a synthetic org on your own laptop, and
take what you need into your own repo.

Six principles, in order of precedence:

1. The checkout is the only source of truth. Knowledge files are leads to re-verify.
2. Deterministic before probabilistic: scripts count and check; the model interprets and judges.
3. Enforcement lives in project settings, so every agent, skill and direct call inherits it.
4. Nothing from an org enters git.
5. Every claim carries `path:line` evidence and a label (Confirmed / Inferred / Unverifiable).
6. The assistant never approves, deploys, pushes or decides.

## Status

**Works today**

- **Guard** (`tools/guard/`): a hook on every Claude Code tool call. It has four modes (`advise`,
  `normal`, `build`, `maintain`) and a committed kill switch. It also runs a tripwire over its own
  files and the git config, and enforces Salesforce CLI access levels.
- **Metadata index** (`tools/index/`): parses the checkout into nodes and reference edges. It
  answers `exists`, `type` and `consumers` queries to 3 hops.
- **Demo org** (`demo/`): a synthetic Sales/Service org with three stories and a reviewed answer
  key for each.
- **Skills**: `story-impact` (the evidenced impact of one story, written as `impact.md` plus a
  draft record, `impact.json`) and `pr-reference-check` (invented or mistyped API names in a diff).
- **Impact record and register** (`tools/impacts/`, `impacts/`): a validated `impact.json`
  schema, a human promotion step into `impacts/`, and the register of in-flight stories. Two
  overlap checks read it. At story time, story-impact lists the other stories that touch the same
  components; that section never fails anything. At PR time, `pr_check.py` reports code overlap
  and scope drift as comments, unless `.ai-framework.json` sets a finding class to `fail`. The PR
  check runs in CI only once the owner applies the WS2 patches (see
  [Running the checks](#running-the-checks)).
- **Framework build**: `render.py` turns `framework/` into the `.claude/` and `.github/` trees,
  and `lint.py` checks the framework rules.
- **Evals**: `run_agent.py` (trajectory assertions over a tool-call log) and `run_skill.py`
  (deterministic assertions on a skill's output).

**Planned, not built** (order and detail in the [spec](docs/superpowers/specs/2026-10-29-published-framework-design.md#order)
and [docs/DESIGN.md](docs/DESIGN.md)): story refinement (WS11), solution design and starting points (WS10), scoped code
writing in `build` mode (WS8; until then `build` cannot write source), consistency evals that
score repeated runs against the answer keys (WS3), versioned packaging and pinning (WS7), and the
Copilot hook (WS6; `.github/hooks/README.md` is a placeholder).

## Prerequisites

- **Python 3**, standard library only. CI uses Python 3.12
  (`.github/workflows/framework-ci.yml:13`).
- **git**.
- **Claude Code**, needed only for the AI step (quick start step 8). Every other step is plain
  Python.
- **A shell**: macOS or Linux, or Windows with Git Bash. Windows is **Inferred, not yet tested**:
  the hook is assumed to run through Git Bash, and no Windows CI run has confirmed it. On Windows,
  use `py -3` wherever this page says `python3`.
- You do **not** need Node, pnpm or the Salesforce CLI for the quick start.

## Quick start

Run every command from the repo root in your own terminal. The guard screens only the
assistant's tool calls, not your shell. The expected output follows each command. Where it
contains `<n>`, the number depends on the commit; this page never fixes counts.

**1. Clone.**

```sh
git clone <repo-url> ai-ready-sf-repo
cd ai-ready-sf-repo
```

**2. Prove the guard blocks on this machine.**

```sh
python3 tools/guard/test_guard.py
```

This takes a couple of minutes and prints a long list, one `[PASS] ...` line per case. Read the
last line. Expected: `<n> passed, 0 failed`. If any case fails, stop here: nothing below is safe
to rely on.

**3. Record the tripwire baseline (once, before you open Claude Code here).**

```sh
python3 tools/guard/guard.py --rebaseline
```

Expected: `baseline recorded in the git directory (ai-guard-baseline)`.

The guard compares `.git/config`, its includes and the hooks directory against a baseline that a
human records. There is none in a fresh clone, so the guard blocks every write and every
non-read-only command the assistant tries until you run this. Run it yourself in a real
terminal: it refuses to run without one, and the guard blocks the assistant from running it.
Re-run it whenever `.git/config` or `.git/hooks/` change for a legitimate reason (for example,
installing husky hooks or changing core settings), and once inside every new git worktree.
Adding a remote or setting branch tracking does not need it.

**4. Build the index of the demo org.**

Replace `/full/path/to/ai-ready-sf-repo` with your clone's absolute path:

```sh
python3 tools/index/build_index.py --root demo/org --out /full/path/to/ai-ready-sf-repo/index
```

This form works both in your terminal and inside Claude Code. In a plain terminal, you can use
`--out "$PWD/index"` as a shortcut. Claude Code's guard refuses any `$`, so there you must type
the path out.

Expected: `indexed <n> nodes, <n> edges at <commit>`.

`--out` must be absolute. A relative `--out` is joined to `--root`, so `--out index` writes
`demo/org/index/`, inside the tree being scanned. `index/` at the repo root is git-ignored. It is
also where `query.py`, `story-impact` and its report writer look by default. (On Windows, Git
Bash is expected to convert `$PWD` into a path `py -3` understands. This is Inferred, not
tested.)

**5. See the hidden 3-hop chain.**

```sh
python3 tools/index/query.py consumers Account.Service_Level__c --hops 3 | grep -o '"api": "[^"]*", "type": "[^"]*", "via": "[^"]*", "target": "[^"]*", "hop": 3'
```

Expected, four hop-3 lines:

```
"api": "Case_Agent_Console", "type": "FlexiPage", "via": "flexipageComponent", "target": "caseEscalationPanel", "hop": 3
"api": "Case_Escalate_Premium", "type": "Flow", "via": "flowApexAction", "target": "EscalationNotifier", "hop": 3
"api": "CaseTriggerHandler_Test", "type": "ApexClass", "via": "apexClassRef", "target": "CaseTriggerHandler", "hop": 3
"api": "CaseTrigger", "type": "ApexTrigger", "via": "apexClassRef", "target": "CaseTriggerHandler", "hop": 3
```

`Account.Service_Level__c` defines who counts as a premium customer. The escalation flow
`Case_Escalate_Premium`, the agent page `Case_Agent_Console` and the trigger `CaseTrigger` never
name that field, so searching for the field finds none of them. Only the reference chain finds
them: the field, then the escalation service that reads it, then the notifier, panel and handler
that call the service, then the flow, page and trigger that use those.

The fourth line, `CaseTriggerHandler_Test`, is the handler's test class. It reaches the field the
same way the trigger does, through `CaseTriggerHandler`. A test that exercises a changed path
belongs in the impact too; the DEMO-201 answer key lists it for review.

Drop the `| grep ...` to see the full JSON, with `path:line` evidence for every edge.

**6. Check the answer keys against the index.**

```sh
python3 tools/demo/check_answers.py --index index demo/stories/DEMO-101.answer.json demo/stories/DEMO-201.answer.json demo/stories/DEMO-202.answer.json
```

Expected:

```
[PASS] DEMO-101 (DEMO-101.answer.json)
[PASS] DEMO-201 (DEMO-201.answer.json)
[PASS] DEMO-202 (DEMO-202.answer.json)
```

This proves that the index finds exactly what each human-reviewed key lists. How the keys are
built is described in [demo/README.md](demo/README.md#answer-keys).

**7. See a story-time overlap with a story already on the register.**

`impacts/` is the register: impact records that a human reviewed, confirmed and promoted. It
holds DEMO-202 (round-robin assignment of new cases, squad Service Ops), which the owner
confirmed. This step drafts DEMO-201's impact from its reviewed answer key, using the same report
writer story-impact uses. The writer reads the register as it writes.

```sh
python3 tools/demo/answer_to_draft.py --key demo/stories/DEMO-201.answer.json --slug premium-escalation-key --index index
```

Expected (`<commit>` is the commit you have checked out):

```
{
  "impactJson": "./ai-context/DEMO-201-premium-escalation-key/impact.json",
  "impactMd": "./ai-context/DEMO-201-premium-escalation-key/impact.md",
  "overlaps": 3,
  "registerCommit": "<commit>"
}
```

Open `ai-context/DEMO-201-premium-escalation-key/impact.md` and find the
`## Overlaps with other stories` section. Or print just its rows:

```sh
grep '| watch |' ai-context/DEMO-201-premium-escalation-key/impact.md
```

Expected:

```
| `CaseTrigger` | watch | DEMO-202 | Service Ops | in-flight | modify | `b8cb1e9` |
| `CaseTriggerHandler` | watch | DEMO-202 | Service Ops | in-flight | modify | `b8cb1e9` |
| `CaseTriggerHandler_Test` | watch | DEMO-202 | Service Ops | in-flight | modify | `b8cb1e9` |
```

- **Each row:** a component both stories list, and the other story's squad, status and change
  type. That tells DEMO-201's squad (Customer Care) whom to talk to.
- **The last column:** the commit that last changed DEMO-202's record, not your `HEAD`. It stays
  the same until that record changes, or until history is rewritten.
- **Why watches, not conflicts:** DEMO-202 modifies these components, while DEMO-201's key marks
  them `review`. A conflict needs both stories to `new`, `modify` or `delete` the component.

The draft is derived from the reviewed key, not from a model run. Its `provenance.model` in
`impact.json` reads `none (derived from reviewed answer key)`. The slug `premium-escalation-key`
keeps it apart from the folder that step 8 writes. Re-running the command overwrites the same
files. Inside Claude Code, like `check_answers.py`, this script needs
`maintain` mode; in your own terminal it just runs.

**8. Run story-impact on DEMO-201 in Claude Code.**

Start Claude Code in the repo root. You are in `normal` mode, the committed default: the
assistant can read everything, run the framework scripts, and write only to `ai-context/` and
`index/`. Type:

```
/story-impact DEMO-201 Premium case escalation. Change case escalation for premium customers. Squad: Customer Care. hops: 3
```

(If the slash command is not offered, ask in plain words: "Use the story-impact skill on this
story: ..." with the same text.) This is the story text from `demo/stories/DEMO-201.md` and
nothing more. Do not name the field:
the point is to see whether the skill finds the chain from the story alone. `hops: 3` matters,
because the default of 2 stops before the hop-3 components in step 5.

The skill checks the index is current, derives seed terms, queries the index and classifies each
hit. It writes its output to `ai-context/<work-item-id>-<slug>/`: `impact.md` and the draft
record `impact.json`, plus `scan/` (`terms.txt`, `classified.json`, `meta.json`). The assistant
picks the slug, so the folder is something like `ai-context/DEMO-201-premium-escalation/`.
`impact.md` has the same `## Overlaps with other stories` section as step 7, built from the
register. Its rows can differ from step 7's. A row's kind follows the change type the assistant
assigns, so a component it marks `modify` shows as a conflict with DEMO-202, not a watch.

**If story-impact reports the index as stale, re-run step 4 yourself; don't let it rebuild from
the repo root.** Its fallback rebuilds with default arguments, which index the repo root, and
the repo root holds no `force-app/`. If you ask the assistant to run step 4 for you, give it the
literal absolute `--out` path.

To compare with the answer key:

- Open `demo/stories/DEMO-201.answer.json` next to `impact.md` and check each component, its
  change type and hop by hand.
- Run the automated part of eval case 004. It scores the files this step's story-impact run
  wrote: `ai-context/DEMO-201-<slug>/impact.md` and the `impact.json` beside it, where `<slug>`
  is the one the assistant picked. In a fresh clone, run story-impact first; the command has
  nothing to read until then. Any draft at that path works too. It checks that the report names
  the three hop-3 components, labels every table row, stays within 3 hops and avoids banned phrases. It also
  checks that `impact.json` is a valid draft record and that the report flags the overlap on
  `CaseTriggerHandler` and `CaseTrigger`:

  ```sh
  python3 tools/evals/run_skill.py --skill story-impact --case 004-escalation-hops-3 --output ai-context/DEMO-201-<slug>/impact.md
  ```

  Expected: `case 004-escalation-hops-3: PASS over 1 run(s)`.

Not automated yet: scoring a report against the answer key, and running the same story several
times to show the answers match (WS3). Today `run_skill.py` also checks that cited paths exist
only when they start with `force-app/`, `pkg-*/` or `fixtures/`, so it does not check the
`demo/org/...` evidence in this report. Spot-check a few `path:line` cites yourself.

## Promoting an impact

A draft in `ai-context/` is workspace output. Neither the register nor the PR check reads it. To
put a story on the register, a human reviews the draft and promotes it:

```sh
python3 tools/impacts/promote.py ai-context/<storyId>-<slug> --confirmed-by "<your name or role>"
```

- **What it checks first:** it validates the draft, including that every evidence file and line
  exists, and it runs `tools/guard/scan_data.py` over `impact.json` and `impact.md`.
- **What it writes:** `impacts/<storyId>-<slug>/`, holding `impact.json` (with `status`
  `in-flight` and your `confirmedBy`) and a copy of `impact.md`.
- **What it refuses:** a folder that already exists (unless you pass `--replace`), and symlinks.

Then `git add` the folder and open a PR; a reviewer checks the impact before merge. When the story
ships, edit its `status` to `shipped` in a later PR, and the register stops listing it.

**Promotion is a human step.** In `normal` mode the guard blocks the assistant both from running
`promote.py` and from writing `impacts/`. `maintain` allows both, so there it is a working rule
rather than a guard rule: run it yourself, with your own `--confirmed-by`. In Claude Code, prefix
the line with `!` so it runs as you, not as an assistant tool call. The assistant never supplies a
confirmation.

To look at the register:

- `python3 tools/impacts/register.py view` prints every component on record as JSON.
- `python3 tools/impacts/register.py scope <storyId>` prints one story's squad, status and
  components.
- `python3 tools/impacts/render_register.py` writes a static page,
  `ai-context/register/register.html`.

Until the owner applies the WS2 guard patch, run these from your own terminal, because the
assistant cannot run them in `normal` mode. To tell which mode you are in, read
`AI_FRAMEWORK_MODE` in the committed `.claude/settings.json`, then check for a git-ignored
`.claude/settings.local.json` that overrides it (see [Using the modes](#using-the-modes)). With
no local file you are in the committed mode, `normal` by default. The schema, the PR check and its `.ai-framework.json`
switch are described under
[Impact record and register](docs/DESIGN.md#impact-record-and-register) in `docs/DESIGN.md`.

## Using the modes

| Mode | For | Writes | Set by |
| --- | --- | --- | --- |
| `advise` | Everyone, when the kill switch is pulled | Nothing; read-only commands only | Committed `.claude/settings.json` |
| `normal` | Every squad member (default) | `ai-context/`, `index/` | Committed `.claude/settings.json` |
| `build` | A developer | Same as `normal` until WS8 adds story scope; adds local `git add`/`commit` and `pnpm` lint, format and test | Your local override |
| `maintain` | A framework maintainer | Framework paths (`framework/`, `tools/` except `tools/guard/`, `demo/`, `docs/`, rendered trees, ...) | Your local override |

- **Switch locally:** create `.claude/settings.local.json` (git-ignored, never committed)
  containing `{"env": {"AI_FRAMEWORK_MODE": "build"}}` or `"maintain"`, then restart the Claude
  Code session. Make this edit yourself: the guard blocks the assistant from writing that file.
  Delete the file to go back to `normal`.
- **Kill switch:** set `"AI_FRAMEWORK_MODE": "advise"` in the committed `.claude/settings.json`.
  A committed `advise` always wins over any local override. A local mode applies only over a
  committed `normal`, and a committed `build` or `maintain` is treated as `advise`.
- **Salesforce CLI levels:** `none` (advise), `offline` (every other mode: help, local
  generators, `code-analyzer`, `project convert source`), and the opt-in `org-metadata` and
  `org-data`. To raise a level, change `sf.mode_level` and list sandbox aliases in
  `sf.allowed_orgs` in `tools/guard/policy.json`, through a reviewed PR. The assistant cannot
  edit `tools/guard/`. Never list a production alias. `org-data` puts real org data into the
  assistant's context. Login, deploy, data writes and `apex run` stay blocked at every level.

Full rules: [Modes](docs/DESIGN.md#modes) and
[Salesforce CLI access levels](docs/DESIGN.md#salesforce-cli-access-levels) in `docs/DESIGN.md`.

## Troubleshooting the guard

When the guard blocks a tool call, Claude Code shows `BLOCKED by tools/guard/guard.py: <reason>`.
Common reasons:

| Message contains | Why | What to do |
| --- | --- | --- |
| `git config or hooks differ from the baseline a human recorded, or there is none` | No tripwire baseline yet (fresh clone, new worktree), or `.git/config` or hooks changed | Review `.git/config` and the hooks, then run quick start step 3 yourself |
| `guard files changed since the last commit: ...; commit or revert them to continue` | A file under `tools/guard/`, `.claude/settings.json`, `.github/workflows/`, `.github/hooks/` or a CODEOWNERS file differs from `HEAD` | Commit the reviewed change or revert it (`git checkout -- <path>`) |
| `the command holds a $, a brace or a [[:class:]] bracket outside single quotes` | The shell could expand it into something the guard never sees | For text, single-quote it or put it in a file. For commit messages: `git commit -F ai-context/<file>`. For a path such as `--out "$PWD/index"`, type the absolute path out literally (`--out /full/path/to/ai-ready-sf-repo/index`): single-quoting `$PWD` stops it expanding, so the path would be wrong |
| `a heredoc (<<) is not allowed in any mode` | The guard cannot read a heredoc's body | Write the text to a file under `ai-context/` and point the command at it |
| `command not on the <mode> allowlist (tools/guard/policy.json)` | Each mode allows a fixed list of commands. `advise` allows read-only commands only. `normal` adds the framework scripts (index build and query, evals, lint, `test_guard.py`, `scan_data.py`, skill scripts). `build` adds local `git add`/`commit` and `pnpm` lint, format and test. `maintain` adds `cp`, `mv`, `rm`, `sed`, `render.py` and any Python script under `tools/`, `framework/`, `fixtures/`, `demo/` or `ai-context/` (see [Using the modes](#using-the-modes)) | Switch to a mode that allows the command, or run it yourself. For example, `tools/demo/check_answers.py` and `render.py` need `maintain` |
| `cannot determine what this command writes; run it as a human` | The guard cannot work out a write target, so it blocks (`python3 -c`, `python3 --version`, `bash -c`, complex compound lines) | Split the line into simple commands, use a script file, or run it yourself |
| `scripts, pnpm and the Salesforce CLI run only from the project root, with no cd before them` | A `cd` came first | Drop the `cd`; use paths relative to the repo root |
| `write to '...' is outside (...) in NORMAL mode` | Write outside the mode's paths | Write under `ai-context/` or `index/`, or switch mode |
| `write to 'demo/org/index...' is outside ...` | A relative `--out` on `build_index.py` is joined to `--root` and lands in the scanned tree | Pass an absolute `--out` (step 4). In `maintain`, `demo/` is writable, so this is **not** blocked and silently writes into the demo; always use an absolute path |
| `write to '...' is never allowed (matches ...)` | Guard, settings, CI, CODEOWNERS and `.git/` change only by human-applied patch | Make the change yourself, reviewed |
| `command matches blocked pattern '(?<![A-Za-z0-9_])guard\\.py'` or `the guard's own script and --rebaseline are for a human at a terminal` | Any Bash line naming the guard script is blocked, even `cat` or `grep` | Open the file in your editor or with the Read tool |
| `framework is in ADVISE mode` | The kill switch is on | Nothing to fix locally; the assistant can only recommend |

## Troubleshooting the impact tools

| Symptom | Why | What to do |
| --- | --- | --- |
| `python3 tools/impacts/register.py scope <storyId>` exits 4 and prints `"found": false` | The story has no record on the register. Either it is still a draft in `ai-context/`, or its record is `shipped` (the register skips those), or its record failed validation (listed under `invalid` in the same output) | Promote the draft (see [Promoting an impact](#promoting-an-impact)). For an `invalid` entry, run `python3 tools/impacts/validate.py --all` and fix the record in a PR. Exit 4 is "nothing on record", not an error |
| The guard blocks `tools/impacts/register.py`, `validate.py`, `render_register.py` or `pr_check.py` in `normal` with `command not on the <mode> allowlist` | The WS2 guard patch is not applied yet, so these scripts are not on `normal`'s allowlist | Run them from your own terminal, or apply `ai-context/ws2/patches/` as `APPLY.md` there describes. Story-impact's overlap section works either way |
| The guard blocks `tools/impacts/promote.py` | Promotion is a human step and is never on `normal`'s allowlist | Run it yourself (see [Promoting an impact](#promoting-an-impact)) |

## Running the checks

The smoke test from [HANDOFF.md](HANDOFF.md#smoke-test-run-before-anything-else):

```sh
python3 tools/guard/test_guard.py          # every case passes
python3 tools/build/lint.py                # lint: 0 error(s)
python3 tools/build/render.py --check      # rendered outputs are current
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
python3 tools/impacts/validate.py --all    # every committed record validates; "ok": true
python3 tools/index/query.py consumers Account.Risk_Rating__c --hops 2 --index index
python3 tools/evals/run_agent.py --log framework/agents/evals/sample-run.jsonl --spec framework/agents/evals/analyst.json
```

The impact test scripts each end with a `<n> passed, 0 failed` line; some add a skipped count,
which covers symlink cases on machines without symlinks.

The fixtures build (`--root fixtures --out ../index`) overwrites `index/` with the fixtures
index. Re-run quick start step 4 before using story-impact on the demo again.

**CI today.** `.github/workflows/framework-ci.yml` runs on pull requests that touch `framework/`,
`tools/`, `.claude/`, `.github/`, `force-app/` or `fixtures/`. It runs on Ubuntu and Windows with
Python 3.12 and covers the guard test, `scan_data.py --all`, lint, the render check, the fixtures
index build, `test_index.py` and the sample agent eval, plus a gitleaks job. None of the impact
checks run in CI yet: not the impact test scripts, not `validate.py --all` and not the PR check.
A change only under `demo/` or `impacts/` does not trigger the workflow. The demo checks
(`test_parsers.py`, the filler and answer-key tests, the filler `--check`) are not in CI either.
Run all of them locally with the smoke test.

**CI after the owner patches land.** The workflow changes come as patches that a human applies,
in the order set out in `ai-context/ws2/patches/APPLY.md`: the WS1 patches first, then WS2.

- **Triggers:** the workflow also runs on changes under `demo/` and `impacts/`.
- **`guard-and-lint`:** runs every impact test script above, then `validate.py --all`.
- **New `impact-checks` job,** on pull requests:
  - It builds the index from the PR's `demo/org`.
  - It runs `pr_check.py` from the base branch with `--base-root`, so the check code, the
    `.ai-framework.json` settings and the register all come from base. A PR cannot change
    those, with two exceptions:
    - The PR that first adds `pr_check.py` runs its own copy, and its result says so.
    - A `pull_request` workflow runs the workflow file from the PR head. A PR that edits
      `.github/workflows/` can therefore change the job itself. Only review and CODEOWNERS catch
      that, not this check.
  - It writes the result to the job summary and to one PR comment.

Findings are comments unless `.ai-framework.json` sets them to `fail`. Until a remote exists, the
comment step is Unverifiable.

## Layout

```
framework/            the ONE source tree squads edit (guild-owned via CODEOWNERS)
  rules/              always-on rules; scope front-matter -> Copilot applyTo
  knowledge/          owned, dated facts; no counts allowed (lint enforces)
  skills/<name>/      SKILL.md + references/ + scripts/ + evals/ (story-impact, pr-reference-check)
  agents/             posture + skill table, nothing else; evals/ holds trajectory specs
tools/
  index/              build_index.py (the index), query.py (what skills call instead of grep),
                      test_index.py, test_parsers.py
  guard/              guard.py + guard.sh/.cmd (fail-closed PreToolUse hook), policy.json (modes,
                      allowlists, Salesforce CLI levels), scan_data.py, test_guard.py
  build/              render.py (framework/ -> .claude/ + .github/), lint.py
  evals/              run_skill.py (output assertions), run_agent.py (trajectory assertions)
  demo/               generate_filler.py (seeded filler), check_answers.py (answer keys vs index),
                      answer_to_draft.py (draft impact from a reviewed key), tests
  impacts/            validate.py (record schema), register.py (overlaps, scope, view),
                      promote.py (human step), render_register.py, pr_check.py, tests
demo/
  org/force-app/      synthetic Sales/Service org: hand-written story core + generated filler
  stories/            DEMO-*.md story text and DEMO-*.answer.json reviewed answer keys
impacts/              the register: squads.json and promoted <storyId>-<slug>/ records (in git)
docs/
  DESIGN.md           design, layers, modes, what the guard guarantees
  superpowers/        specs/ (the published-framework spec) and plans/ (per-workstream plans)
.claude/              GENERATED, plus the hand-written settings.json (hook, deny rules, kill switch)
.github/              GENERATED instructions/knowledge/skills/agents, plus workflows/ and hooks/
fixtures/             small synthetic metadata and diffs for tool tests and CI; never real
ai-context/           every assistant output lands here (today inputs/, scan/*.json and Office
                      files are git-ignored; all of it once the WS2 .gitignore patch lands)
index/                generated; git-ignored, never committed
VERSION               framework version (no install or pinning mechanism yet; WS7)
```

## Where to go next

- [demo/README.md](demo/README.md): the demo org, what the index models, the stories and how
  the answer keys work.
- [docs/DESIGN.md](docs/DESIGN.md): the five layers, the modes, the impact record and register,
  and what the guard does and does not guarantee.
- [HANDOFF.md](HANDOFF.md): working rules for contributors, the smoke test and the backlog.
- [The spec](docs/superpowers/specs/2026-10-29-published-framework-design.md): intent, owner
  decisions and the workstream order.

Onboarding a squad member today: run quick start steps 2 to 7, run the sample agent eval
(`python3 tools/evals/run_agent.py ...` above), read `framework/rules/00-precedence.md`, and know
who the guild is (`CODEOWNERS`). There is no versioned install yet: `VERSION` records the
framework version, but packaging and pinning are planned (WS7), so adopters copy the files.

## Contributing and safety

The guard is a **laptop control, best effort**. It stops accidents and makes a hostile
instruction harder to act on. It is not a boundary against code the assistant writes and then
runs. The hard guarantee is server-side: CODEOWNERS and branch protection on `tools/guard/`,
`.claude/settings.json`, `.github/` and `CODEOWNERS`, CI, secret scanning and human review of
every PR. This repo does not set that up for you. Whoever adopts it must enable and confirm it
on their remote (see
[What the guard guarantees](docs/DESIGN.md#what-the-guard-guarantees)). Until then, that layer is
a plan, not a guarantee.

Changes to `tools/guard/`, `.claude/settings.json`, `.github/workflows/`, `.github/hooks/` and
CODEOWNERS are human-applied patches with a second reviewer. Edit `framework/`, never the rendered
`.claude/` or `.github/` trees, and run `render.py` and `lint.py` before committing. Fixtures and
demo data are synthetic; `tools/guard/scan_data.py` gates commits. Deliberately absent: seed
memory, org facts inside agents or skills, model checks a script could do, outputs outside
`ai-context/`, and any automation that votes, deploys or pushes.

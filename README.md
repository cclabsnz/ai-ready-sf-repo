# AI-ready Salesforce repo (reference)

A reference way of working for large Salesforce programmes that let AI assistants (Claude Code
now, GitHub Copilot next) analyse and, later, build. It is for enterprise architects and squad
leads deciding whether and how to adopt AI across several build squads. Everything a squad wants
from the assistant (impact analysis, PR review, discovery) consumes one capability: a
deterministic, commit-stamped index of the checkout. A guard on every tool call keeps the
assistant inside fixed limits. You clone it, run it on a synthetic org on your own laptop, and
take what you need into your own repo.

- **Try it:** [demo/WALKTHROUGH.md](demo/WALKTHROUGH.md) goes step by step through the framework on
  the demo org. Each step says whether it is plain Python, needs Claude Code, or waits on an owner
  confirmation. `python3 tools/demo/walkthrough_check.py` re-runs the deterministic steps and
  diffs them against `demo/expected/`.
- **Adopt it:** [docs/ADOPTING.md](docs/ADOPTING.md) takes the framework into your own Salesforce
  repo: install routes, policy and modes, server-side controls, onboarding and what Copilot users
  get today.

Six principles, in order of precedence:

1. The checkout is the only source of truth. Knowledge files are leads to re-verify.
2. Deterministic before probabilistic: scripts count and check; the model interprets and judges.
3. Enforcement lives in project settings, so every agent, skill and direct call inherits it.
4. Nothing from an org enters git.
5. Every claim carries `path:line` evidence and a label (Confirmed / Inferred / Unverifiable).
6. The assistant may recommend and proceed provisionally; it never approves, deploys, pushes or makes a binding decision. Every recommendation is confirmed by a named owner before it becomes a committed impact or a code scope.

## Status

**Works today**

- **Guard** (`tools/guard/`): a hook on every Claude Code tool call. It has four modes (`advise`,
  `normal`, `build`, `maintain`) and a committed kill switch. It also runs a tripwire over its own
  files and the git config, and enforces Salesforce CLI access levels.
- **Metadata index** (`tools/index/`): parses the checkout into nodes and reference edges,
  including each picklist value with its active flag (index version `0.5.0`). It answers
  `exists`, `type` and `consumers` queries to 3 hops, and `edge-seeds`: candidate edge cases for
  a story's fields and objects, each with evidence.
- **Demo org** (`demo/`): a synthetic Sales/Service org with three stories and a reviewed answer
  key for each.
- **Skills**: `story-refine` (one rough story turned into Given/When/Then criteria and
  edge cases seeded from the index, written as a draft `story.json` and `story.md`),
  `solution-design` (evidenced options for one story, always including "do nothing", with one
  provisional recommendation, written as a draft `design.json` and `design.md`),
  `story-impact` (the evidenced impact of one story, or of one design option, written as
  `impact.md` plus a draft record, `impact.json`) and `pr-reference-check` (invented or mistyped
  API names in a diff). story-refine, solution-design and story-impact make up the
  [day-one workflow](#the-day-one-workflow) up to confirmation; `implement-story` (tests first,
  then code, inside a story's committed build package, run by the `builder` agent) continues it
  into code once a story has a committed build package (see [Scoped code writing](#scoped-code-writing)).
- **Starting points** (`tools/onboard/`, `tools/config/`, WS10): `.ai-framework.json` names the
  repo's starting point (`existing` or `greenfield`) and its source root, read by one module,
  `tools/config/framework_config.py`. `build_index.py --from-config` indexes that source root.
  `onboard.py` sets a repo up from either starting point (see
  [Two starting points](#two-starting-points)); `demo/greenfield/` is the committed greenfield
  skeleton.
- **Solution design** (`tools/designs/`, WS10): the `design.json` schema
  (`validate_design.py`), and the owner's choice of option at promotion
  (`promote.py --option`). No model has run solution-design, or story-impact on a design option,
  under Claude Code yet: they are shown only by writer smoke tests (see
  [Day-one workflow](docs/DESIGN.md#day-one-workflow)). The assistant runs `validate_design.py`
  and `framework_config.py` in `normal`, `build` and `maintain`, and CI runs the WS10 test scripts.
  Onboarding an existing codebase now also writes its rule baseline, `tools/code/baseline.json`.
- **Story refinement** (`tools/stories/`, WS11): the `story.json` schema
  (`validate_story.py`), a vague-criteria check (`check_ac.py`), and confirmation by the product
  owner, who promotes the story into `impacts/` (`promote.py --story`). No model has run
  story-refine under Claude Code yet; its writer and eval assertions are tested on a hand-built
  draft only (see [Story refinement](docs/DESIGN.md#story-refinement)). The assistant runs
  `check_ac.py` and `validate_story.py` in `normal`, `build` and `maintain`, and CI runs the story
  checks.
- **Impact record and register** (`tools/impacts/`, `impacts/`): a validated `impact.json`
  schema, a human promotion step into `impacts/`, and the register of in-flight stories. Two
  overlap checks read it. At story time, story-impact lists the other stories that touch the same
  components; that section never fails anything. At PR time, `pr_check.py` maps the changed
  files to components and lists the registered stories and other open PRs that touch the same
  components; that listing never fails anything. It also reports scope drift (`outOfScope`,
  `noImpact`) as comments, unless `impactChecks` in `.ai-framework.json` sets a finding class
  to `fail`. The PR
  check runs in CI (see [Running the checks](#running-the-checks)).
- **Scoped code writing** (`tools/code/`, `tools/impacts/package.py` and `start.py`,
  `framework/skills/implement-story/`, `framework/agents/builder.md`, WS8). The guard's scope
  lock and tests-first are in place in `build` mode. `check_rules.py`, the deterministic Apex rule
  check, runs on the demo with its committed baseline and exits 0 (see
  [Scoped code writing](#scoped-code-writing) for the real output). `package.py`, `start.py` and
  `check_trace.py` run, but there is no build package yet: one needs the owner to confirm the
  DEMO-202 story, design and impact first. Until a package is committed and a human runs
  `start.py`, `build` writes no source in this repo.
- **Framework build**: `render.py` turns `framework/` into the `.claude/` and `.github/` trees,
  and `lint.py` checks the framework rules.
- **Evals**: `run_agent.py` (trajectory assertions over a tool-call log), `run_skill.py`
  (deterministic assertions on a skill's output), and `consistency.py` (WS3), which compares
  several runs of one case on the fields that must agree and prints a `k/N identical` line.
  `run_all.py` produces those runs with `claude -p`; only the owner runs it, so no consistency
  figure for a skill exists yet. The committed runs in `demo/expected/consistency-fixture/` are
  hand-built to show the format, not model output.
- **Measurement kit** (`demo/measure/`, WS4): `score.py` scores an impact against its answer key
  and `timing.py` times a run from a session transcript. No time-saved figure is published (see
  [demo/measure/README.md](demo/measure/README.md)).
- **Walkthrough and adoption guide** (WS5): [demo/WALKTHROUGH.md](demo/WALKTHROUGH.md) with its
  deterministic check, `tools/demo/walkthrough_check.py`, and [docs/ADOPTING.md](docs/ADOPTING.md).
  [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and
  [CHANGELOG.md](CHANGELOG.md) cover contributions, private reports and releases.

**Not built** (order and detail in the design spec and plans, which are the maintainers'
workspace and not published in this repo, and in [docs/DESIGN.md](docs/DESIGN.md)):

- **The Copilot guard (WS6).** Copilot users get the rendered instructions but no guard:
  `.github/hooks/` holds only a README, and no Copilot hook is registered (see
  [Copilot today](docs/DESIGN.md#copilot-today-ws6)).
- **A placed plugin (WS7).** The plugin manifest and a layout proposal are drafted for the owner,
  who picks the layout; nothing is placed yet, and no release is tagged. Today you install by
  copying files (see [docs/ADOPTING.md](docs/ADOPTING.md)).

**Waits on the owner** (the maintainers' queue, `ai-context/OWNER-QUEUE.md`, in their git-ignored
workspace):

- the owner decisions listed with the applied guard and CI patches (`ai-context/ws8/patches/APPLY.md`
  and `ai-context/publish/patches/APPLY.md`): whether `maintain` keeps write access to the
  source root, whether the CI trace check stays report-only, whether `build` keeps
  `pnpm format` and `pnpm lint`, what to do with the `live-consistency` job, whether this repo
  enables the `nz` and `ncino` scan packs, and whether to add a schedule;
- the GitHub settings (private vulnerability reporting, branch protection with the required
  checks) and the full-history scans before the repository goes public;
- the confirmations the code walkthroughs need (items 10 and 11: confirm the DEMO-202 story,
  design and impact, run `package.py` and commit the package, then run `start.py` in a terminal;
  the greenfield walkthrough needs the same for DEMO-301);
- picking the plugin layout, placing the drafted files (LICENSE, CODEOWNERS, the plugin
  manifest, the issue and PR templates) and tagging the first release;
- the live `run_all.py` series and any golden outputs from them.

## The day-one workflow

This is the main path for one story, on an existing codebase or a greenfield one. The assistant
does the analysis and may recommend and proceed provisionally. A named owner confirms each
result by promoting it; the assistant never does.

1. **Refine** with `story-refine`. A rough story becomes Given/When/Then criteria, edge cases
   from the index and open questions with owner roles, written as a draft `story.json` and
   `story.md`. The product owner confirms it with `promote.py --story`
   (see [Confirming a refined story](#confirming-a-refined-story)).
2. **Understand** with the front half of `story-impact`. It checks that the index is current
   (rebuilding with `python3 tools/index/build_index.py --from-config` when it is stale), frames
   the story, derives seed terms and scans the index.
3. **Design** with `solution-design`. It writes options, exactly one of them "do nothing", each
   with trade-offs on named criteria and the components it touches with evidence. It names one
   provisional recommendation with reasons, written as a draft `design.json` and `design.md`.
4. **Assess** with `story-impact` on the recommended option. solution-design hands that option
   on, and story-impact sizes only its components. The draft `impact.json` names the option in
   `designOption`.
5. **Confirm**, a human step. The owner promotes the impact and chooses the option:
   `promote.py ai-context/<storyId>-<slug> --confirmed-by "<name or role>" --option OPT-<n>`.
   When step 1's story was promoted first, the impact goes into the same folder without
   `--replace`; the story files stay as they are.
   Leaving out `--option` chooses the recommendation. If the impact assessed a different option,
   promotion refuses and asks for story-impact to be re-run for the chosen one (see
   [Choosing a design option](#choosing-a-design-option)).
6. **Build the package**, a maintainer step in `maintain` or your terminal:
   `python3 tools/impacts/package.py <storyId>`. It writes `build-package.json` and
   `build-package.md` beside the confirmed records. Commit them with the impact PR.
7. **Start the build session**, a human step in a real terminal:
   `python3 tools/impacts/start.py <storyId>`. Add the env lines it prints to
   `.claude/settings.local.json` and restart Claude Code.
8. **Implement** with `implement-story`, through the `builder` agent: tests first, then code,
   only inside the package scope.
9. **Run the done commands.** The builder runs the package's `done[]` commands (the trace
   checks and `check_rules.py --from-config`) and records each exit code.
10. **Write the change summary.** `write_change.py` writes `change.json` and `change.md`, mapping
    every file, every criterion to its tests, and every done command to its exit.
11. **Open a PR.** A named reviewer reviews it, and CI re-runs the checks. The builder never
    approves its own work.

Steps 7 to 10 need a committed build package, so in this repo they wait on the owner's
confirmations (see [Scoped code writing](#scoped-code-writing)).

Steps 1 to 5 write to `ai-context/<storyId>-<slug>/`, and the promotions copy the confirmed
records into `impacts/<storyId>-<slug>/`. The skills run in Claude Code (`/story-refine`,
`/solution-design`, `/story-impact`, or through the `discovery-lead` and `analyst` agents). The
promotions run in your own terminal.

**What is proven.** The scripts behind each step have tests. The quick start below runs the
index and the refinement checks on the demo, and has you run story-impact on one demo story in
Claude Code. No model has run story-refine,
solution-design or story-impact's assessment of a design option under Claude Code yet. Their
writers and eval assertions are shown only by writer smoke tests on hand-built drafts. A story
can skip the design step: story-impact without a `design.json` sizes the story as before.

To set a repo up for this workflow, see [Two starting points](#two-starting-points).

## Prerequisites

- **Python 3**, standard library only. CI uses Python 3.12
  (`.github/workflows/framework-ci.yml:13`).
- **git**.
- **Claude Code**, needed only for the AI steps (quick start step 8 and the optional end of
  step 9). Every other step is plain Python.
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

To confirm the baseline is current, ask the assistant to run `git status`. The guard refuses
every git command, in every mode, while the baseline is missing or stale (`git is blocked: git
config or hooks differ from the baseline ...`). If `git status` runs, the baseline matches. The
guard has no other status option.

**4. Build the index of the demo org.**

```sh
python3 tools/index/build_index.py --from-config
```

Expected: `indexed <n> nodes, <n> edges at <commit>`.

`--from-config` indexes the `sourceRoot` named in `.ai-framework.json`, which this repo sets to
`demo/org`, into `index/` at the repo root. `index/` is git-ignored. It is also where `query.py`,
the skills and their writers look by default. The same command works in your terminal and inside
Claude Code, and it is what story-impact and solution-design run when they find the index stale.
To see the configured source root, run `python3 tools/config/framework_config.py source-root`
(expected: `demo/org`). It runs in your terminal and, inside Claude Code, in `normal`, `build`
and `maintain`.

`--from-config` refuses `--root` or `--out` alongside it (exit 2). If you build an index by hand
with `--root` instead, pass an absolute `--out`: a relative `--out` is joined to `--root`, so
`--root demo/org --out index` writes `demo/org/index/`, inside the tree being scanned.

**5. See the hidden 3-hop chain.**

```sh
python3 tools/index/query.py consumers Account.Service_Level__c --hops 3 | grep -o '"api": "[^"]*", "type": "[^"]*", "via": "[^"]*", "target": "[^"]*", "hop": 3'
```

Expected, the hop-3 lines:

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

Drop the `| grep ...` to see the full JSON, with `path:line` evidence for every edge. If the
command prints nothing, the index is missing, stale or built from another root (for example the
fixtures build in the smoke test). Re-run step 4 and try again.

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
| `CaseTrigger` | watch | DEMO-202 | Service Ops | in-flight | modify | `121a920` |
| `CaseTriggerHandler` | watch | DEMO-202 | Service Ops | in-flight | modify | `121a920` |
| `CaseTriggerHandler_Test` | watch | DEMO-202 | Service Ops | in-flight | modify | `121a920` |
```

- **Each row:** a component both stories list, and the other story's squad, status and change
  type. That tells DEMO-201's squad (Customer Care) whom to talk to.
- **The last column:** the commit that last changed DEMO-202's record, not your `HEAD`. It stays
  the same until that record changes, or until history is rewritten. The commit hashes pasted on
  this page (here and in `registerCommit` above) come from the reference checkout; on your clone
  they can differ, for example after a rebase or on a fork.
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

If story-impact finds the index stale, it rebuilds it with `build_index.py --from-config`, the
command from step 4, so the rebuild indexes `demo/org`. The guard admits that command in
`normal`, as a write to `index/`.

To compare with the answer key:

- Open `demo/stories/DEMO-201.answer.json` next to `impact.md` and check each component, its
  change type and hop by hand.
- Run the automated part of eval case 004. It scores the files the story-impact run in this
  step (quick start step 8) wrote: `ai-context/DEMO-201-<slug>/impact.md` and the `impact.json` beside it, where `<slug>`
  is the one the assistant picked. In a fresh clone, run story-impact first; `ai-context/` is
  git-ignored, so the command has nothing to read until then. Any draft at that path works too. It checks that the report names
  the hop-3 components in the case's `must_reference` list (`Case_Escalate_Premium`,
  `Case_Agent_Console` and `CaseTrigger`; step 5 shows the full hop-3 set), labels every table row, stays within 3 hops and avoids banned phrases. It also
  checks that `impact.json` is a valid draft record and that the report flags the overlap on
  `CaseTriggerHandler` and `CaseTrigger`:

  ```sh
  python3 tools/evals/run_skill.py --skill story-impact --case 004-escalation-hops-3 --output ai-context/DEMO-201-<slug>/impact.md
  ```

  Expected: `case 004-escalation-hops-3: PASS over 1 run(s)`.

To score the run against the answer key, use `demo/measure/score.py` on its `impact.json`
(walkthrough step 10). To see whether repeated runs agree, the owner runs the same case several
times with `tools/evals/run_all.py` and compares them with `tools/evals/consistency.py`
(walkthrough step 9); no such series has run yet. `run_skill.py` also checks each backticked `path:line`
cite that starts with `force-app/`, `pkg-*/`, `fixtures/` or `demo/`: the file must exist and
have at least that many lines. That covers the `demo/org/...` evidence in this report. It does
not check that the cited line says what the report claims, so spot-check a few cites yourself.

**9. Refinement: story-refine, step 0 of the workflow.**

In real use, refinement comes first. Step 0 is story-refine: it turns a rough story into testable
Given/When/Then criteria and edge cases from the index. story-impact then sizes the refined
story. The quick start shows refinement last because it needs only the index from step 4.

See the edge seeds the index gives for `Account.Service_Level__c`, the field behind "premium
customers":

```sh
python3 tools/index/query.py edge-seeds Account.Service_Level__c | grep -o '"category": "[^"]*", "component": "[^"]*", "detail": "[^"]*"'
```

Expected:

```
"category": "automation", "component": "Account", "detail": "flow Account_Churn_Flag (Active)"
"category": "automation", "component": "Account", "detail": "flow Account_Coverage_Check (Active)"
"category": "automation", "component": "Account", "detail": "flow Account_Plan_Review_Stamp (Active)"
"category": "automation", "component": "Account", "detail": "flow Account_Renewal_Stamp (Active)"
"category": "automation", "component": "Account", "detail": "flow Account_Seat_Flag (Active)"
"category": "automation", "component": "Account", "detail": "flow Account_Segment_Default (Active)"
"category": "automation", "component": "Account", "detail": "validation rule Account.Churn_Risk_Pct_In_Range (active)"
"category": "automation", "component": "Account", "detail": "validation rule Account.Expansion_Potential_Not_Negative (active)"
"category": "automation", "component": "Account", "detail": "validation rule Account.Health_Score_In_Range (active)"
"category": "automation", "component": "Account", "detail": "validation rule Account.Last_Review_Date_Not_Ancient (active)"
"category": "automation", "component": "Account", "detail": "validation rule Account.Seat_Count_Not_Negative (active)"
"category": "bulk", "component": "Account", "detail": "a bulk change of 200 records or more"
"category": "org-only", "component": "Account", "detail": "sharing settings and real data volumes are org configuration, not in this repo"
"category": "blank", "component": "Account.Service_Level__c", "detail": "field is not required; value left blank"
"category": "field-access", "component": "Account.Service_Level__c", "detail": "Sales_Rep edit"
"category": "field-access", "component": "Account.Service_Level__c", "detail": "Service_Agent read"
"category": "field-access", "component": "Account.Service_Level__c", "detail": "Team_Lead read"
"category": "picklist-value", "component": "Account.Service_Level__c", "detail": "Legacy Bronze (inactive)"
"category": "picklist-value", "component": "Account.Service_Level__c", "detail": "Premium"
"category": "picklist-value", "component": "Account.Service_Level__c", "detail": "Standard"
```

- **No lines at all** means the index is missing, stale or not the demo's (for example after the
  smoke test's fixtures build). Re-run step 4 and try again.
- **Each line is a candidate edge case.** Drop the `| grep ...` to see the full JSON, with
  `path:line` evidence and a confidence label on every seed.
- **A field covers its object too,** hence the `Account` flows, rules, bulk seed and org-only
  seed.
- **The `org-only` seed** is there for every object, with no evidence (`null`) and the label
  `Unverifiable`: sharing settings and real data volumes are org configuration, which this repo
  does not hold. Keep it as an edge case, or drop it with a reason; either way it often becomes
  an open question for the Salesforce Admin.
- **`Legacy Bronze (inactive)`** is a retired value, kept in the demo as a deliberate sign of age.
  Old records can still hold it, so a story that reads the field may need to handle it.
- **The `Account` bulk seed has no evidence** (`null`) and is `Unverifiable`: the demo holds
  neither a trigger on `Account` nor an `Account` object file to cite.

Then see what a vague criterion looks like.
`demo/stories/DEMO-101.vague-example.story.json` is a hand-written draft `story.json`. It is
valid apart from its criteria (`python3 tools/stories/validate_story.py` on it prints
`"ok": true`). Check its criteria:

```sh
python3 tools/stories/check_ac.py demo/stories/DEMO-101.vague-example.story.json
```

Expected (exit code 1, because there are findings):

```
{
  "ok": false,
  "findings": [
    {
      "id": "AC-1",
      "rule": "multiple-outcomes",
      "detail": "then states more than one outcome (the word 'and'); split into separate criteria"
    },
    {
      "id": "AC-1",
      "rule": "vague-word",
      "detail": "then contains 'quickly'"
    },
    {
      "id": "AC-1",
      "rule": "vague-word",
      "detail": "then contains 'properly'"
    },
    {
      "id": "AC-2",
      "rule": "vague-word",
      "detail": "then contains 'as needed'"
    }
  ]
}
```

story-refine's writer runs the same check and writes nothing until it passes. The fix is to
split AC-1 into one criterion per outcome and to state each outcome as something a tester can
observe, with a concrete example. Text in quotes is exempt, so a criterion can quote a value.

In Claude Code, `check_ac.py` and `validate_story.py` run in `normal`, `build` and `maintain`. In
your own terminal they just run. `query.py edge-seeds` runs in every mode, but the skill saves its output with a
`> ai-context/...` redirect, and that redirect is a write, which `advise` blocks.

Optional, in Claude Code. The guard's `normal` allowlist admits the commands the skill runs
(`query.py edge-seeds` and its writer, `write_story.py`); that is Inferred from the policy, not
yet shown by a run:

```
/story-refine DEMO-201 Premium case escalation. Change case escalation for premium customers. Squad: Customer Care
```

The skill writes `ai-context/DEMO-201-<slug>/story.json`, `story.md` and `scan/edge-seeds.json`.
Score it with eval case 002, which checks among other things that the `Escalation_Needs_Level`
validation rule on `Case` is kept as an edge case and becomes a criterion. It also recomputes the
edge seeds from `index/` (or `--index <dir>`) and fails when the saved `scan/edge-seeds.json`
differs, so keep the demo index from step 4. The eval reads the files the `/story-refine`
run above wrote. `ai-context/` is git-ignored, so on a fresh clone the folder does not exist and
the command has nothing to read until you run the skill:

```sh
python3 tools/evals/run_skill.py --skill story-refine --case 002-escalation-validation-rule --output ai-context/DEMO-201-<slug>/story.md
```

**This part is unproven.** No model has run story-refine under Claude Code yet, so this page
gives no expected output for it. Case 002 has passed only as a smoke test of the writer: a
hand-built draft fed through `write_story.py`. That shows the writer and the assertions work, not
that the skill does.

## Two starting points

A repo comes to this framework either with a codebase already in it (`existing`) or with none
(`greenfield`). `tools/onboard/onboard.py` sets it up from either. Run it in your own terminal:
in Claude Code it runs only in `maintain`. This
repo is already onboarded as `existing`, with `.ai-framework.json` reading
`{"startingPoint": "existing", "sourceRoot": "demo/org"}`.

What each run writes, in a clone of this repo:

- **existing** rebuilds `index/` from the source root and writes knowledge stubs to
  `framework/knowledge/stubs/`. That folder is not git-ignored, so the stubs show as untracked
  files. Delete them afterwards if you are only trying the command.
- **greenfield** replaces `index/` with the index of an empty source root. Run step 4's
  `python3 tools/index/build_index.py --from-config` afterwards, before anything that needs the
  demo index.
- Neither touches `.ai-framework.json` unless you pass `--write-config`, which writes
  `startingPoint` and `sourceRoot` and keeps any `impactChecks`.

The outputs below are real runs, with every count replaced by `<n>` and the commit by
`<commit>`.

**Existing codebase.** `--owner-role` is required: it becomes the `owner` of every stub. The
source root comes from `.ai-framework.json` unless you pass `--source-root`.

```sh
python3 tools/onboard/onboard.py --starting-point existing --owner-role "Salesforce Architect"
```

Expected:

```
# Onboarding: existing

Source root: `demo/org`

Index: `index` (build_index.py: indexed <n> nodes, <n> edges at <commit>)

## Inventory (from index/inventory.json)

### Apex by API version

| API version | Classes and triggers |
|---|---|
| 45.0 | <n> |
| 48.0 | <n> |
| 52.0 | <n> |
| 62.0 | <n> |

### Apex by sharing

| Sharing | Classes and triggers |
|---|---|
| inherited/unspecified | <n> |
| with sharing | <n> |
| without sharing | <n> |

### Aura vs LWC

| Framework | Bundles |
|---|---|
| Aura | <n> |
| LWC | <n> |

## Knowledge stubs (framework/knowledge/stubs/)

Owner role: Salesforce Architect. Topics: the objects with the most inbound edges in the index; each stub names leads to verify, not facts.

- `framework/knowledge/stubs/opportunity.md`: Opportunity
- `framework/knowledge/stubs/account.md`: Account
- `framework/knowledge/stubs/lead.md`: Lead
- `framework/knowledge/stubs/contact.md`: Contact
- `framework/knowledge/stubs/case.md`: Case

Rule baseline: `tools/code/baseline.json` holds the check_rules.py findings already in the source root; later runs report only new ones
```

- **The inventory** is read from `index/inventory.json`, not counted by the model.
- **A stub holds leads, not facts.** `framework/knowledge/stubs/case.md` lists index components
  under "Leads to verify:", with `last_verified` and `verified_by` empty. A human verifies the
  leads, fills the stub and moves it up a level into `framework/knowledge/`. Lint and rendering
  skip `stubs/`; they apply once the file is moved.
- **Running it again** changes no stub or config. A stub you have edited is kept and reported; `--replace`
  overwrites it.
- **The rule baseline** records which existing rule violations are accepted as debt:
  `tools/code/baseline.json`, written from `check_rules.py`. The last line above is taken from
  `tools/onboard/onboard.py:384-385` for an unchanged baseline, not from a re-run. When the file
  on disk differs from what onboarding would write, the line ends with
  `(kept: the file on disk differs; --replace overwrites it)`. A finding outside the baseline makes
  `check_rules.py` exit 1, and the baseline only shrinks (see
  [Scoped code writing](#scoped-code-writing)).

**Greenfield.** This repo keeps its greenfield skeleton in `demo/greenfield/`, so pass that as
the source root. Without `--write-config` the repo's `.ai-framework.json` stays as it is.

```sh
python3 tools/onboard/onboard.py --starting-point greenfield --source-root demo/greenfield
```

Expected, in a clone where `demo/greenfield/` is already committed:

```
# Onboarding: greenfield

Source root: `demo/greenfield`

## Greenfield layout

- `demo/greenfield/sfdx-project.json`: present
- `demo/greenfield/force-app/main/default/classes/.gitkeep`: present
- `demo/greenfield/force-app/main/default/objects/.gitkeep`: present
- `demo/greenfield/force-app/main/default/lwc/.gitkeep`: present
- `demo/greenfield/force-app/main/default/flows/.gitkeep`: present
- `demo/greenfield/force-app/main/default/permissionsets/.gitkeep`: present

Index: `index` (build_index.py: indexed <n> nodes, <n> edges at <commit>)

Greenfield replaced `index/` with the index of `demo/greenfield`; `python3 tools/index/build_index.py --from-config` rebuilds it from the configured source root.

no baseline: rules are strict from the first commit
```

- **On an empty folder** each line reads `created` instead of `present`.
- **On a folder that already holds a codebase**, greenfield writes nothing and exits 1, naming
  the files it found and pointing to the existing starting point. Try it on the demo org:
  `python3 tools/onboard/onboard.py --starting-point greenfield --source-root demo/org`.
- **No baseline is needed:** with no code yet, the rules apply in full from the first commit.

Now rebuild the demo index: `python3 tools/index/build_index.py --from-config`.

## Promoting an impact

A draft in `ai-context/` is workspace output. Neither the register nor the PR check reads it. To
put a story on the register, a human reviews the draft and promotes it:

```sh
python3 tools/impacts/promote.py ai-context/<storyId>-<slug> --confirmed-by "<your name or role>"
```

- **What it checks first:** it validates the draft, including that every evidence file and line
  exists, and it runs `tools/guard/scan_data.py` over `impact.json` and `impact.md`.
- **What it writes:** `impacts/<storyId>-<slug>/`, holding `impact.json` (with `status`
  `in-flight` and your `confirmedBy`) and a copy of `impact.md`, plus the confirmed design files
  when the draft holds `design.json` (see [Choosing a design option](#choosing-a-design-option)).
- **What it refuses:** a folder that already holds `impact.json`, `impact.md`, `design.json` or
  `design.md` (unless you pass `--replace`; a folder holding only the confirmed story's
  `story.json` and `story.md` is fine); a symlinked
  source, destination or `impacts/`; JSON it cannot parse, deeply nested JSON included; a story
  id that already has a record (`impact.json`, `story.json` or `design.json`) in another
  `impacts/` folder; and
  a data-scan hit in the sources or in the exact bytes it would write. That last scan includes
  your `--confirmed-by`, so give a name or a role, never an email address.

Then `git add` the folder and open a PR; a reviewer checks the impact before merge. When the story
ships, edit its `status` to `shipped` in a later PR, and the register stops listing it.

### Choosing a design option

When solution-design ran for the story, the draft folder also holds `design.json`, and promotion
is where the owner chooses the option. This is step 5 of the
[day-one workflow](#the-day-one-workflow).

```sh
python3 tools/impacts/promote.py ai-context/<storyId>-<slug> --confirmed-by "<name or role>" --option OPT-<n>
```

- **The choice:** `--option`, or the design's recommendation when you leave it out.
- **What it checks first:** `design.json` validates as a draft against the index (`--index`,
  default `index/`) with evidence checked, and names the same story id and slug as the impact.
  Keep the index the design was written against: the greenfield onboarding run above replaces it.
  On success promotion prints the design's `sourceRoot` and the `--index` it used. It does not
  check that the index was built from that root. For a greenfield design, pass the index built
  with `--root demo/greenfield`. The `--from-config` index covers only the configured root
  (`demo/org`). Promotion is the last index check the design gets.
- **A mismatch is refused (exit 1):** when the impact assesses another option, promotion prints
  `impact assesses OPT-a; re-run story-impact for OPT-b before promoting`. Re-run story-impact
  for your option; never hand-edit the record.
- **Choosing "do nothing":** an impact that marks any component `new`, `modify` or `delete` is
  refused with `the chosen option is do nothing; the impact must not change components`. The
  message also lists the changing components. `review` components are allowed.
- **What it writes:** the impact as above, with `chosenOption` added to `impact.json`, plus
  `design.json` (status `confirmed`, your `confirmedBy`, `chosenOption`) and a `design.md`
  re-rendered from it. The design files get the same symlink, data-scan and cross-folder checks
  as the impact.
- **Without `design.json`:** `--option` is a usage error (exit 2), and an impact that names a
  `designOption` is refused.
- **After a confirmed story:** when step 1's confirmed story is already in
  `impacts/<storyId>-<slug>/`, promote the impact into the same folder with no `--replace`; the
  story files stay byte-identical (see
  [Confirming a refined story](#confirming-a-refined-story), "One folder per story id").

### Confirming a refined story

The product owner confirms a story that story-refine drafted by promoting it. Promotion is the
confirmation; the assistant never confirms a story.

```sh
python3 tools/impacts/promote.py ai-context/<storyId>-<slug> --story --confirmed-by "<name or role>"
```

- **What it checks first:** the draft `story.json` validates with every evidence file and line
  checked; `check_ac.py` has no findings; every open question has an answer or is
  `deferred: true` with `deferredBy` set to the role that deferred it; and the data scan finds
  nothing in `story.json` and `story.md`. Only you set `deferred` and `deferredBy`, by editing the
  draft `story.json` before you promote it; the assistant never does.
- **What it shows you before writing:** every deferred question (`OQ-n`, owner role, deferred
  by, text) and every answered question with its answer, so you see what you are confirming past.
- **What it writes:** `impacts/<storyId>-<slug>/story.json` (status `confirmed`, with your
  `confirmedBy`) and a `story.md` re-rendered from that record, not copied from the draft. The
  md reads `Status: confirmed. Confirmed by: <your value>.` and shows every answer and deferral
  as `story.json` holds it; its Overlaps section is as recorded at refinement. The data scan runs
  on those final bytes. It never touches `impact.json` or `impact.md` in that folder. `--replace`
  applies only to the story files.
- **What it refuses:** the same symlink, cross-folder and final-bytes checks as an impact.
- **One folder per story id.** A refined story and its impact record must share one
  `<storyId>-<slug>` folder, so give them the same slug. A story id on record in one folder
  blocks a promotion into any other. Promoting an impact into a folder that holds only the
  confirmed story needs no `--replace`. `--replace` is needed only when the folder already holds
  `impact.json`, `impact.md`, `design.json` or `design.md`; it rewrites only those files.

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

`register.py` runs in every mode and `render_register.py` in `normal`, `build` and `maintain`;
`promote.py` runs only in `maintain`, as a human step. To tell which mode you are in, read
`AI_FRAMEWORK_MODE` in the committed `.claude/settings.json`, then check for a git-ignored
`.claude/settings.local.json`. A committed `advise` always wins. The local file's mode applies
only while the committed value is `normal`, and a committed `build` or `maintain` is treated as
`advise` (see [Using the modes](#using-the-modes)). With no local file and the committed default
`normal`, you are in `normal`. The schema, the PR check and its `.ai-framework.json`
switch are described under
[Impact record and register](docs/DESIGN.md#impact-record-and-register) in `docs/DESIGN.md`.

## Using the modes

| Mode | For | Writes | Set by |
| --- | --- | --- | --- |
| `advise` | Everyone, when the kill switch is pulled | Nothing; read-only commands only | Committed `.claude/settings.json` |
| `normal` | Every squad member (default) | `ai-context/`, `index/` | Committed `.claude/settings.json` |
| `build` | A developer | Same as `normal`, plus the exact paths in the active story's committed build package, tests first; adds local `git add`/`commit` and `pnpm` lint, format and test | Your local override, with the lines `start.py` prints |
| `maintain` | A framework maintainer | Framework paths (`framework/`, `tools/` except `tools/guard/`, `demo/`, `docs/`, rendered trees, ...) | Your local override |

- **Switch locally:** create `.claude/settings.local.json` (git-ignored, never committed)
  containing `{"env": {"AI_FRAMEWORK_MODE": "build"}}` or `"maintain"`, then restart the Claude
  Code session. Make this edit yourself: the guard blocks the assistant from writing that file.
  Delete the file to go back to `normal`. For `build`, run `python3 tools/impacts/start.py <storyId>`
  first: it writes `ai-context/.active-story` and prints the entries to add,
  `"AI_FRAMEWORK_MODE": "build"` and `"AI_FRAMEWORK_STORY": "<id>-<slug>"`. The guard needs the
  story value to equal `.active-story`.
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
| `command not on the <mode> allowlist (tools/guard/policy.json)` | Each mode allows a fixed list of commands. `advise` allows read-only commands only. `normal` adds the framework scripts (index build and query, `run_skill.py` and `run_agent.py`, lint, `test_guard.py`, `scan_data.py`, the impact, story and design validators, `check_ac.py`, `framework_config.py`, `check_rules.py --from-config`, `check_trace.py <storyId>`, skill scripts). `build` adds local `git add`/`commit` and `pnpm` lint, format and test. `maintain` adds `cp`, `mv`, `rm`, `sed`, `render.py` and any Python script under `tools/`, `framework/`, `fixtures/`, `demo/` or `ai-context/` (see [Using the modes](#using-the-modes)) | Switch to a mode that allows the command, or run it yourself. For example, `tools/demo/check_answers.py` and `render.py` need `maintain` |
| `cannot determine what this command writes; run it as a human` | The guard cannot work out a write target, so it blocks (`python3 -c`, `python3 --version`, `bash -c`, complex compound lines) | Split the line into simple commands, use a script file, or run it yourself |
| `scripts, pnpm and the Salesforce CLI run only from the project root, with no cd before them` | A `cd` came first | Drop the `cd`; use paths relative to the repo root |
| `write to '...' is outside (...) in NORMAL mode` | Write outside the mode's paths | Write under `ai-context/` or `index/`, or switch mode |
| `write to 'demo/org/index...' is outside ...` | A manual build with a relative `--out` on `build_index.py`: it is joined to `--root` and lands in the scanned tree | Use `build_index.py --from-config` (step 4), or pass an absolute `--out`. In `maintain`, `demo/` is writable, so a relative `--out` is **not** blocked and silently writes into the demo |
| `write to '...' is never allowed (matches ...)` | Guard, settings, CI, CODEOWNERS and `.git/` change only by human-applied patch | Make the change yourself, reviewed |
| `command matches blocked pattern '(?<![A-Za-z0-9_])guard\\.py'` or `the guard's own script and --rebaseline are for a human at a terminal` | Any Bash line naming the guard script is blocked, even `cat` or `grep` | Open the file in your editor or with the Read tool |
| `framework is in ADVISE mode` | The kill switch is on | Nothing to fix locally; the assistant can only recommend |

## Troubleshooting the impact tools

| Symptom | Why | What to do |
| --- | --- | --- |
| `python3 tools/impacts/register.py scope <storyId>` exits 4 and prints `"found": false` | The story has no record on the register. Either it is still a draft in `ai-context/`, or its record is `shipped` (the register skips those), or its record failed validation (listed under `invalid` in the same output) | Promote the draft (see [Promoting an impact](#promoting-an-impact)). For an `invalid` entry, run `python3 tools/impacts/validate.py --all` and fix the record in a PR. Exit 4 is "nothing on record", not an error |
| The guard blocks `tools/impacts/promote.py` | Promotion is a human step and is never on `normal`'s allowlist | Run it yourself (see [Promoting an impact](#promoting-an-impact)) |
| `write_story.py` exits 1 and writes nothing | The draft failed validation or the criteria check; the errors are on stderr | Fix the draft and run it again. A `vague-word` or `multiple-outcomes` finding means rewording or splitting a criterion, not deleting it |
| `promote.py` refuses with `story <id> already has a record in ...` | That story id is on record in another `impacts/` folder | Use the existing folder's slug (see [Confirming a refined story](#confirming-a-refined-story)) |
| `query.py edge-seeds` gives no `picklist-value` seeds for a picklist field | The index predates version `0.5.0`, or the field uses a global value set (one `Unverifiable` seed) | Rebuild the index (quick start step 4) |
| `promote.py` refuses with `impact assesses OPT-a; re-run story-impact for OPT-b before promoting` | The owner chose an option the draft impact did not assess | Re-run story-impact for the chosen option (see [Choosing a design option](#choosing-a-design-option)) |
| `check_trace.py` exits 2 with `check_trace: no impacts/<storyId>-*/build-package.json under <repo>` | The story has no build package. In this repo no package exists yet | The owner confirms the story, design and impact, and a maintainer runs `package.py` and commits the package (`ai-context/OWNER-QUEUE.md` item 10) |
| `start.py` exits 2 with `run start.py yourself in a terminal; the assistant cannot start a build session` | start.py needs a real terminal, and the guard refuses it from the assistant in every mode | Run it yourself in a terminal |
| `package.py` refuses with `story.json is missing; nothing written` (or the design or impact is not confirmed) | A build package is made only from a confirmed story, design and impact in one `impacts/<storyId>-<slug>/` folder. DEMO-202's folder holds only its impact today | The owner confirms the missing records first (`ai-context/OWNER-QUEUE.md` item 10) |
| In `build`, a source write is blocked with `no active story scope (ai-context/.active-story is absent)` | No build session has been started | Start one with `start.py` in your terminal, add the env lines it prints and restart Claude Code |
| In `build`, a source write is blocked with `is not in the build package of the active story` or `tests first: write to ... waits until every criterion has a referencing test` | The scope lock admits only the exact paths in the committed package, and code waits until every criterion id is named in a `scope.tests` file | Write the tests first. For a file outside scope, file `ai-context/<id>-<slug>/scope-request.md`; scope changes only through a new impact and package |
| `build_index.py --from-config` exits 2 | `.ai-framework.json` is invalid (an unknown key, a bad value, or a `sourceRoot` outside the repo or not a folder), or `--root` or `--out` was given too | Fix the config; `python3 tools/config/framework_config.py source-root` prints the error. Drop `--root` and `--out` |
| The guard blocks `tools/onboard/onboard.py` | Onboarding is on no `normal` allowlist; only `maintain` admits it | Run it in your own terminal (see [Two starting points](#two-starting-points)) |

## Running the checks

The smoke test from [HANDOFF.md](HANDOFF.md#smoke-test-run-before-anything-else):

```sh
python3 tools/guard/test_guard.py          # every case passes
python3 tools/guard/test_scan_data.py      # data scan: packs, --tracked, usage errors
python3 tools/build/lint.py                # lint: 0 error(s)
python3 tools/build/render.py --check      # rendered outputs are current
python3 tools/index/build_index.py --root fixtures --out ../index # writes index/ at the repo root
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
python3 tools/code/test_check_trace.py     # trace check CLI, stub and real core
python3 tools/impacts/test_package.py      # build package from confirmed records
python3 tools/impacts/test_start.py        # start.py, stub and real core
python3 tools/code/test_write_change.py    # implement-story writer: change.json
python3 tools/code/check_rules.py --from-config # exit 0: every demo finding is baselined
python3 tools/impacts/validate.py --all    # every committed record validates; "ok": true
python3 tools/stories/validate_story.py --all # every confirmed story validates; "ok": true
python3 tools/designs/validate_design.py --all # every confirmed design validates; "ok": true
python3 tools/index/query.py consumers Account.Risk_Rating__c --hops 2 --index index
python3 tools/evals/run_agent.py --log framework/agents/evals/sample-run.jsonl --spec framework/agents/evals/analyst.json
python3 tools/demo/walkthrough_check.py    # walkthrough's deterministic steps match demo/expected/
```

The impact, story, config, onboarding, design, code, evals and measurement test scripts each end
with a `<n> passed, 0 failed` line; some add a skipped count, which covers symlink cases on
machines without symlinks. `walkthrough_check.py` builds its own index in a temp folder, so it
does not depend on which index `index/` holds. In Claude Code, the `tools/*/test_*.py` scripts
other than `test_guard.py` and `test_index.py`, the `demo/measure/` tests and the `tools/demo/`
scripts run only in `maintain`, and so do `render.py` and `check_rules.py` with any flag but
`--from-config` and `--compare-baseline`; in your terminal they just run.

The fixtures build passes a relative `--out`, which `build_index.py` joins to `--root`, not to
the current folder. So `--root fixtures --out ../index` writes `index/` at the repo root and
overwrites the demo index there. Re-run quick start step 4 before using story-impact on the demo
again.

**The data scan.** Run it as CI does, and check its exit code (don't pipe it):

```sh
python3 tools/guard/scan_data.py --tracked
```

- **`--tracked`** scans only the files `git ls-files` lists, so git-ignored folders such as
  `ai-context/` and `data/` are never read. Outside a git work tree, or without git, it exits 2,
  never "clean". Exit 0 is clean and exit 1 lists each hit as `<path>:<line>: <pattern>`.
- **`--all`** walks the whole working tree under the current folder, skipping only `.git`,
  `node_modules` and any folder named `index`. On a maintainer's machine it also reads
  `ai-context/` and `data/`, so a hit there fails a local run that CI would pass. With no
  option, the scan reads the staged files, as the pre-commit hook does.
- **Packs.** The `default` pack (Salesforce IDs, emails, credentialed instance URLs, session IDs)
  is always on. The `nz` pack (NZ bank-account and IRD numbers) and the `ncino` pack (`LLC_BI__`
  record names) apply only when `tools/guard/scan_packs.json` names them. This repo ships that
  file with the default pack only, `{"packs": ["default"]}`, so its pre-commit, CI and
  `promote.py` scans do not apply the NZ and nCino patterns. Whether this repo enables them is an
  open owner decision. The file sits under `tools/guard/`, so changing it is a guard change. A
  file that does not parse, or names an unknown pack, exits 2.

`validate.py --all` and `validate_design.py --all` read no index. They check committed designs
as confirmed records: schema, internal consistency and the design-to-impact checks. The index
checks on a design's components run only when `write_design.py` writes it and when
`promote.py` confirms it. A confirmed design therefore stays valid once its `new` components
land or a `delete` ships.

**CI.** `.github/workflows/framework-ci.yml` runs on pull requests that touch `framework/`,
`tools/`, `.claude/`, `.github/`, `force-app/`, `fixtures/`, `demo/`, `impacts/` or
`.ai-framework.json`, with Python 3.12. It can also be started by hand (`workflow_dispatch`), but
only the `live-consistency` job runs then; the other jobs run on pull requests only.

- **`guard-and-lint`,** on Ubuntu and Windows, each command its own step:
  - the guard test, `scan_data.py --tracked` and the scanner's tests;
  - lint and the render check;
  - the fixtures index build, `test_index.py` and `test_parsers.py`;
  - the filler and answer-key tests, the filler `--check`, and `test_answer_to_draft.py`;
  - the sample agent eval for the analyst;
  - every impact test script above and `test_run_skill.py`;
  - `build_index.py --from-config`, then `validate.py --all`;
  - the story checks: `test_check_ac.py`, `test_validate_story.py`, `test_write_story.py`,
    `test_edge_seeds.py` and `validate_story.py --all`;
  - the config, onboarding and design tests, then `validate_design.py --all`;
  - the code tests: `test_check_trace.py`, `test_check_rules.py`, `test_write_change.py`,
    `test_package.py` and `test_start.py`, and the builder's sample agent eval;
  - `check_rules.py --from-config`, which fails the job on a finding the committed baseline
    lacks;
  - `test_consistency.py`, `test_run_all.py` (an injected runner; `claude` never starts), the
    `demo/measure/` tests, `test_walkthrough_check.py` and `walkthrough_check.py`.
- **`secrets`:** a gitleaks secret scan.
- **`impact-checks`,** on pull requests:
  - It builds the index from the base branch's `sourceRoot` (`framework_config.py source-root
    --root base`), falling back to `demo/org` when the base branch has no `framework_config.py`.
  - It runs `pr_check.py` from the base branch with `--base-root`, so the check code, the
    `.ai-framework.json` settings and the register all come from base. A PR cannot change
    those, with two exceptions:
    - The PR that first adds `pr_check.py` runs its own copy, and its result says so.
    - A `pull_request` workflow runs the workflow file from the PR head. A PR that edits
      `.github/workflows/` can therefore change the job itself. Only review and CODEOWNERS catch
      that, not this check.
  - It writes the result to the job summary and to one PR comment.
  - The base branch's `check_trace.py` runs for each build package the PR adds or changes. It is
    report-only: a gap is a warning and the JSON goes to the step summary. Whether it should fail
    the job is an open owner decision.
  - The base branch's `check_rules.py` checks the PR's source root against the PR's baseline and
    compares that baseline with the base copy. A new finding, or a baseline that grew, fails the
    job.
- **`live-consistency`,** optional and manual only: started by hand from the default branch,
  never on a pull request and on no schedule. It runs `run_all.py` for one story-impact case with
  the `ANTHROPIC_API_KEY` secret, compares the runs with `consistency.py` and uploads the run
  folders. It is not a required check. It has never run, and as written it is not expected to
  produce skill outputs: a fresh runner has no tripwire baseline, so the guard blocks the
  `claude -p` session's writes and even `git status`, and the re-baseline refuses to run without
  a terminal. Whether to keep it as a smoke test, remove it or design a CI baseline is an open
  owner decision. Before any first run the owner also pins the Claude Code version it installs
  and limits the job to the owner's repository; the committed job does neither yet.

Findings are comments unless `.ai-framework.json` sets them to `fail`. Until a remote exists, the
comment step is Unverifiable. This repository has no remote yet, so none of these jobs has run
on a GitHub runner.

## Scoped code writing

WS8 lets the assistant write Salesforce code only inside one story's confirmed scope, in `build`
mode, tests first. The full design is
[Scoped code writing](docs/DESIGN.md#scoped-code-writing) in `docs/DESIGN.md`.

**What the guard enforces in `build`.** A write outside `ai-context/` and `index/` must be under
the `sourceRoot` committed in `.ai-framework.json`, and must equal a path in the active story's
build package committed at `HEAD`. `AI_FRAMEWORK_STORY` must equal `ai-context/.active-story`,
which only `start.py` writes. Code stays blocked until every criterion id is named in a
`scope.tests` file (tests first), and a hard-linked target is refused.

**The rule check on the demo.** Run it in your terminal, or in Claude Code in `normal`, `build`
or `maintain`:

```sh
python3 tools/code/check_rules.py --from-config
```

Expected: exit 0, because every finding in `demo/org` is in `tools/code/baseline.json`. Trimmed
output from a real run (the `baselined` and `findings` lists hold one entry per finding; one is
shown):

```
{
 "baselined": [
  {
   "line": 32,
   "path": "demo/org/force-app/main/default/classes/CaseAccountSummaryController.cls",
   "rule": "apex-sharing",
   "text": "public class AccountSummary {"
  },
  ...
 ],
 "findings": [ ... ],
 "new": [],
 "notes": [
  "Scanned demo/org against tools/code/baseline.json.",
  "SOQL/DML-in-loop detection is narrow and may miss cases: it sees only [SELECT ...], DML statements and Database DML calls written inside a braced for, while or do body. Loops without braces, calls into other methods and dynamic SOQL are not followed.",
  "Comments and '...' strings are ignored. Each finding is one rule on one line."
 ]
}
```

A finding outside the baseline lands in `new` and the exit is 1. Which demo classes the
baselined findings are in, and why, is in [demo/README.md](demo/README.md#signs-of-age).

**What exists but cannot run end to end yet:**

- `tools/impacts/package.py <storyId>` builds the package from a confirmed story, design and
  impact. There is no package in this repo: `python3 tools/impacts/package.py DEMO-202` refuses
  with `story.json is missing; nothing written`, because `impacts/DEMO-202-round-robin-assignment/`
  holds only its impact.
- `tools/impacts/start.py <storyId>` needs a committed package, and refuses without a terminal.
  The guard refuses it from the assistant in every mode.
- `tools/code/check_trace.py DEMO-202` exits 2 with
  `check_trace: no impacts/DEMO-202-*/build-package.json under <repo>`.
- `implement-story` and the `builder` agent have not run under Claude Code: they need a package.

**What waits on the owner:**

- the confirmations for the code walkthrough (`ai-context/OWNER-QUEUE.md` items 10 and 11);
- the open decisions in `ai-context/ws8/patches/APPLY.md`: whether `maintain` keeps write access
  to the source root, whether the CI trace check stays report-only, and whether `build` keeps
  `pnpm format` and `pnpm lint`, which run the adopter's own scripts.

**Honest limits.** Apex compiles and runs only in your org-connected CI; nothing here compiles
it. The scope lock binds `build` mode only (`maintain` can already write `demo/`). Tests-first is
structural: a comment such as `// AC-1` satisfies it. Committed at `HEAD` is not reviewed, so PR
review is the guarantee. The done exits in `change.json` are the session's own report. MCP tool
path arguments and `pnpm run format`/`lint` are not scope-checked. `check_rules.py` detection is
narrow.

## Layout

```
framework/            the ONE source tree squads edit (guild-owned via CODEOWNERS)
  rules/              always-on rules; scope front-matter -> Copilot applyTo
  knowledge/          owned, dated facts; no counts allowed (lint enforces)
  knowledge/stubs/    onboarding's knowledge stubs (leads only); outside lint and rendering
  skills/<name>/      SKILL.md + references/ + scripts/ + evals/ (story-refine, solution-design,
                      story-impact, pr-reference-check, implement-story)
  agents/             posture + skill table, nothing else (analyst, reviewer, discovery-lead,
                      builder); evals/ holds trajectory specs
tools/
  index/              build_index.py (the index), query.py (what skills call instead of grep),
                      test_index.py, test_parsers.py, test_edge_seeds.py
  guard/              guard.py + guard.sh/.cmd (fail-closed PreToolUse hook), policy.json (modes,
                      allowlists, Salesforce CLI levels), scope_core.py and trace_core.py (the
                      build scope and criteria-to-test matching), scan_data.py + scan_packs.json,
                      test_guard.py, test_scan_data.py
  build/              render.py (framework/ -> .claude/ + .github/), lint.py
  evals/              run_skill.py (output assertions), run_agent.py (trajectory assertions),
                      consistency.py (agreement across runs), run_all.py (owner-run claude -p
                      series), tests
  demo/               generate_filler.py (seeded filler), check_answers.py (answer keys vs index),
                      answer_to_draft.py (draft impact from a reviewed key),
                      walkthrough_check.py (walkthrough steps vs demo/expected/), tests
  impacts/            validate.py (record schema), register.py (overlaps, scope, view),
                      promote.py (human step, impacts and stories), render_register.py,
                      pr_check.py, package.py (build package), start.py (human starts a build
                      session), safe_write.py (shared writer checks), tests
  code/               check_rules.py (Apex rule checks) + baseline.json, check_trace.py
                      (criteria to tests), tests (including write_change.py's)
  stories/            validate_story.py (story schema), check_ac.py + vague_words.json (vague
                      criteria), tests
  designs/            validate_design.py (design schema), design_md.py (design.md renderer), tests
  config/             framework_config.py (the one reader of .ai-framework.json), test
  onboard/            onboard.py (existing and greenfield starting points), test
demo/
  org/force-app/      synthetic Sales/Service org: hand-written story core + generated filler
  greenfield/         the empty greenfield skeleton onboard.py creates (sfdx-project.json, .gitkeep)
  stories/            DEMO-*.md story text, DEMO-*.answer.json reviewed answer keys, and
                      DEMO-101.vague-example.story.json (a draft story.json with vague criteria)
  measure/            score.py, timing.py, the baseline template and tests (measurement kit)
  expected/           expected output of the walkthrough's deterministic steps, and the
                      hand-built consistency fixture
  WALKTHROUGH.md      the walkthrough
impacts/              the register: squads.json and promoted <storyId>-<slug>/ records (in git)
docs/
  DESIGN.md           design, layers, modes, what the guard guarantees
  ADOPTING.md         taking the framework into your own repo
.claude/              GENERATED, plus the hand-written settings.json (hook, deny rules, kill switch)
.github/              GENERATED instructions/knowledge/skills/agents, plus workflows/ and hooks/
fixtures/             small synthetic metadata and diffs for tool tests and CI; never real
ai-context/           every assistant output lands here; git-ignored as a whole
index/                generated; git-ignored, never committed
VERSION               framework version (the plugin that would pin it is drafted, not placed; WS7)
CHANGELOG.md, CONTRIBUTING.md, SECURITY.md   releases, contribution rules, private reports
.ai-framework.json    starting point, source root and PR-check severity
                      ({"startingPoint": "existing", "sourceRoot": "demo/org"} here)
```

## Where to go next

- [demo/WALKTHROUGH.md](demo/WALKTHROUGH.md): the framework step by step on the demo, with the
  deterministic steps checked by `tools/demo/walkthrough_check.py`.
- [docs/ADOPTING.md](docs/ADOPTING.md): taking the framework into your own Salesforce repo.
- [demo/README.md](demo/README.md): the demo org, what the index models, the stories and how
  the answer keys work.
- [docs/DESIGN.md](docs/DESIGN.md): the layers, the modes, the day-one workflow (config,
  onboarding, the design record and the option choice), the impact record and register, story
  refinement, scoped code writing, and what the guard does and does not guarantee.
- [HANDOFF.md](HANDOFF.md): working rules for contributors, the smoke test and the backlog.
- The design spec and plans (intent, owner decisions and the workstream order) are the
  maintainers' workspace, not published in this repo.

Onboarding a squad member today: run quick start steps 2 to 7, run the sample agent eval
(`python3 tools/evals/run_agent.py ...` above), read `framework/rules/00-precedence.md`, and know
who the guild is (`CODEOWNERS`). There is no versioned install yet: `VERSION` records the
framework version, and the plugin manifest and layout are drafted for the owner, who picks the
layout and places the files (WS7). Until then adopters copy the files, as
[docs/ADOPTING.md](docs/ADOPTING.md) describes ("Route B: full copy-in").

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
CODEOWNERS are human-applied patches with a second reviewer. On this public repository the
second-reviewer rule is not enforced yet: branch protection with required reviews needs at least
two maintainers, and until a second maintainer exists, changes here merge on one maintainer's
review. An adopting team enforces the rule on its own remote. Edit `framework/`, never the rendered
`.claude/` or `.github/` trees, and run `render.py` and `lint.py` before committing. Fixtures and
demo data are synthetic; `tools/guard/scan_data.py` gates commits. Deliberately absent: seed
memory, org facts inside agents or skills, model checks a script could do, outputs outside
`ai-context/`, and any automation that votes, deploys or pushes.

- [CONTRIBUTING.md](CONTRIBUTING.md): how to propose a skill or agent, the required evals, the
  review rules and commit messages.
- [SECURITY.md](SECURITY.md): how to report a guard bypass privately, and what the guard does and
  does not guarantee.
- [CHANGELOG.md](CHANGELOG.md): what each release delivered.

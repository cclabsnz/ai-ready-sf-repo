# Walkthrough

Ten steps through the framework on the synthetic demo org, from the guard test to the scores
against the answer key. Each step carries one or more labels:

- **deterministic (no Claude Code):** plain Python. The expected output is committed in
  `demo/expected/`, and `tools/demo/walkthrough_check.py` re-runs the step and compares.
- **needs Claude Code:** a model runs a skill. Its output varies from run to run, so this page
  gives the command and how to score the result, not a fixed output.
- **needs owner confirmations:** a human confirms a record, or starts a build session, before the
  step can run. The assistant never supplies a confirmation.

Two paths through it:

- **Without Claude Code:** steps 1, 2, 5, 9 and 10, plus the deterministic parts of steps 4, 7
  and 8. Everything on this path is a script run.
- **With Claude Code:** every step. Steps 6 and 7 also wait on the owner (see each step).

Where an output contains `<n>`, the number depends on the commit; this page never fixes counts.
`<commit>` is the commit you have checked out, and `<time>` a timestamp. The files in
`demo/expected/` hold the exact output, normalised the same way.

## Before you start

- Python 3, standard library only, and git. Claude Code only for the steps that say so.
- Run every command from the repo root in your own terminal. The guard screens the assistant's
  tool calls, not your shell.
- **macOS and Linux** use `python3`. **Windows** uses `py -3` in PowerShell. The Windows commands
  on this page are **Inferred, not yet run**: no Windows machine or CI run has executed them. CI
  is planned to run the deterministic path on Ubuntu and Windows through an owner patch.
- **Version.** Run the walkthrough from a checkout of a release tag (`git checkout v<version>`,
  with the version from `VERSION`). No tag exists yet: the owner tags `v0.1.0` (queued in
  `ai-context/OWNER-QUEUE.md`). Until then, use the default branch.
- **Owner items.** `ai-context/OWNER-QUEUE.md` and the `ai-context/<workstream>/patches/` folders
  named on this page are the maintainers' workspace. `ai-context/` is git-ignored, so they are not
  in your clone. They are named so you can see what an owner step waits on.

### The whole deterministic path in one command

macOS / Linux:

```sh
python3 tools/demo/walkthrough_check.py
```

Windows (PowerShell):

```powershell
py -3 tools/demo/walkthrough_check.py
```

Expected (exit 0):

```
[PASS] index-build
[PASS] hop3-consumers
[PASS] register-view
[PASS] score-demo-202
[PASS] consistency
[PASS] check-rules
6 passed, 0 failed
```

On any difference it prints `[FAIL] <step>`, a unified diff against the file in `demo/expected/`,
and the step's stderr, then exits 1.

- **What it normalises:** line endings, the repo path (`<repo>`) and its temp folder (`<tmp>`),
  ISO timestamps (`<time>`), and hex words of 7 to 40 characters with a digit (`<commit>`). It
  re-prints one-document JSON with indent 2, so a diff points at the changed line.
- **The consumers list is sorted** by hop, then api, before comparing, so the check does not rest
  on the order the index lists edges in.
- **It builds the index into a temp folder,** so your `index/` is left alone.
- **It leaves out the guard test** (step 1): that test takes minutes and depends on the machine's
  shells.

To refresh one expected file after a reviewed change, print the step and save the output over the
file, for example
`python3 tools/demo/walkthrough_check.py --show register-view > demo/expected/03-register-view.txt`.
On Windows, run that from Git Bash, or in PowerShell pipe it to
`Out-File -Encoding utf8 demo/expected/03-register-view.txt`: Windows PowerShell's `>` writes
UTF-16. Review the diff before committing it.

## 1. Guard test on your laptop

*deterministic (no Claude Code)*

macOS / Linux:

```sh
python3 tools/guard/test_guard.py
```

Windows (PowerShell):

```powershell
py -3 tools/guard/test_guard.py
```

It takes a couple of minutes and prints one `[PASS] ...` line per case. Read the last line.
Expected: `<n> passed, 0 failed`. On Windows, symlink and POSIX-only cases print `[SKIP]`, and the
last line adds `, <n> skipped`. The registered-hook cases need Git for Windows' bash. If any case
fails, stop here: nothing below is safe to rely on.

Then record the tripwire baseline, once, before you open Claude Code in the repo. Run it yourself
in a real terminal; the guard refuses it from the assistant.

macOS / Linux:

```sh
python3 tools/guard/guard.py --rebaseline
```

Windows (PowerShell):

```powershell
py -3 tools/guard/guard.py --rebaseline
```

Expected: `baseline recorded in the git directory (ai-guard-baseline)`.

`walkthrough_check.py` does not run this step. The summary line is the check.

## 2. Build the index on `demo/org/`

*deterministic (no Claude Code)*

macOS / Linux:

```sh
python3 tools/index/build_index.py --from-config
```

Windows (PowerShell):

```powershell
py -3 tools/index/build_index.py --from-config
```

Expected: `indexed <n> nodes, <n> edges at <commit>`. Exact output:
`demo/expected/01-index-build.txt`. `--from-config` indexes the `sourceRoot` in
`.ai-framework.json` (`demo/org`) into `index/`, which is git-ignored.

Now see the hidden hop-3 chain behind `Account.Service_Level__c`, the field that defines a premium
customer.

macOS / Linux:

```sh
python3 tools/index/query.py consumers Account.Service_Level__c --hops 3 | grep -o '"api": "[^"]*", "type": "[^"]*", "via": "[^"]*", "target": "[^"]*", "hop": 3'
```

Windows (PowerShell):

```powershell
py -3 tools/index/query.py consumers Account.Service_Level__c --hops 3 | ConvertFrom-Json | Select-Object -ExpandProperty consumers | Where-Object hop -eq 3
```

Expected, from a real run on macOS. The line order follows the index build's file walk, which is
sorted, so it is the same on other systems (Inferred: only macOS has run it):

```
"api": "Case_Agent_Console", "type": "FlexiPage", "via": "flexipageComponent", "target": "caseEscalationPanel", "hop": 3
"api": "Case_Escalate_Premium", "type": "Flow", "via": "flowApexAction", "target": "EscalationNotifier", "hop": 3
"api": "CaseTriggerHandler_Test", "type": "ApexClass", "via": "apexClassRef", "target": "CaseTriggerHandler", "hop": 3
"api": "CaseTrigger", "type": "ApexTrigger", "via": "apexClassRef", "target": "CaseTriggerHandler", "hop": 3
```

None of these components names the field, so a text search for it finds none of them. The full
result, every hop with `path:line` evidence, is `demo/expected/02-hop3-consumers.txt`.

## 3. Simple story via story-impact

*needs Claude Code*

Start Claude Code in the repo root (the committed mode is `normal`) and type:

```
/story-impact DEMO-101 Customer Tier on the Case page. Add a Customer Tier picklist on Account, shown to agents on the Case page. Squad: Customer Care
```

That is the text of `demo/stories/DEMO-101.md` and nothing more. The skill writes
`ai-context/DEMO-101-<slug>/impact.md` and the draft record `impact.json`; the assistant picks the
slug. Score the draft against the reviewed key with step 10's command, using
`demo/stories/DEMO-101.answer.json`.

## 4. Complex story: the hop-3 dependency and an overlap

*needs Claude Code* (the deterministic stand-in below needs no Claude Code)

DEMO-201 changes premium case escalation. Its impact reaches the hop-3 components from step 2, and
it touches components that DEMO-202, the other squad's in-flight story, also changes.

```
/story-impact DEMO-201 Premium case escalation. Change case escalation for premium customers. Squad: Customer Care. hops: 3
```

`hops: 3` matters: the default of 2 stops before the hop-3 components. Then run the automated part
of eval case 004 on what the skill wrote. It checks that the report names the hop-3 components,
labels every row, stays within 3 hops and flags the overlap on `CaseTriggerHandler` and
`CaseTrigger`.

macOS / Linux:

```sh
python3 tools/evals/run_skill.py --skill story-impact --case 004-escalation-hops-3 --output ai-context/DEMO-201-<slug>/impact.md
```

Windows (PowerShell):

```powershell
py -3 tools/evals/run_skill.py --skill story-impact --case 004-escalation-hops-3 --output ai-context/DEMO-201-<slug>/impact.md
```

Expected: `case 004-escalation-hops-3: PASS over 1 run(s)`.

**Deterministic stand-in.** Draft DEMO-201's impact from its reviewed answer key, through the
same report writer the skill uses. The writer reads the register as it writes.

macOS / Linux:

```sh
python3 tools/demo/answer_to_draft.py --key demo/stories/DEMO-201.answer.json --slug premium-escalation-key --index index
grep '| watch |' ai-context/DEMO-201-premium-escalation-key/impact.md
```

Windows (PowerShell):

```powershell
py -3 tools/demo/answer_to_draft.py --key demo/stories/DEMO-201.answer.json --slug premium-escalation-key --index index
Select-String -Path ai-context/DEMO-201-premium-escalation-key/impact.md -Pattern '| watch |' -SimpleMatch
```

Expected, from a real run (`registerCommit` is your `HEAD`; the last column is the commit that
last changed DEMO-202's record):

```
{
  "impactJson": "./ai-context/DEMO-201-premium-escalation-key/impact.json",
  "impactMd": "./ai-context/DEMO-201-premium-escalation-key/impact.md",
  "overlaps": 3,
  "registerCommit": "<commit>"
}
| `CaseTrigger` | watch | DEMO-202 | Service Ops | in-flight | modify | `<commit>` |
| `CaseTriggerHandler` | watch | DEMO-202 | Service Ops | in-flight | modify | `<commit>` |
| `CaseTriggerHandler_Test` | watch | DEMO-202 | Service Ops | in-flight | modify | `<commit>` |
```

These rows are watches, not conflicts: DEMO-202 modifies the components, while DEMO-201's key
marks them `review`. `walkthrough_check.py` does not run this stand-in, because it writes under
`ai-context/`.

## 5. Promote the impact; open the register view

*needs owner confirmations* (promotion) and *deterministic (no Claude Code)* (the register view)

Promotion is the human step that puts a reviewed draft on the register. Run it yourself, with
your own name or role, never an email address. In Claude Code, prefix the line with `!` so it runs
as you, not as an assistant tool call.

macOS / Linux:

```sh
python3 tools/impacts/promote.py ai-context/DEMO-201-<slug> --confirmed-by "<your name or role>"
```

Windows (PowerShell):

```powershell
py -3 tools/impacts/promote.py ai-context/DEMO-201-<slug> --confirmed-by "<your name or role>"
```

It validates the draft and its evidence, runs the data scan, and writes
`impacts/DEMO-201-<slug>/`. This changes your clone's register, so the view below then lists
DEMO-201 as well. To keep step 5's expected output, skip the promotion or discard the folder
afterwards.

The register view of the committed register, which holds DEMO-202 only:

macOS / Linux:

```sh
python3 tools/impacts/register.py view
python3 tools/impacts/render_register.py
```

Windows (PowerShell):

```powershell
py -3 tools/impacts/register.py view
py -3 tools/impacts/render_register.py
```

`register.py view` prints every component on record with its story, squad, status, change type
and the commit that last changed the record. Exact output: `demo/expected/03-register-view.txt`.
`render_register.py` writes a static page, `ai-context/register/register.html`, to open in a
browser.

## 6. Start the story; implement-story writes inside scope

*needs Claude Code*, *needs owner confirmations*

This step cannot run end to end today. It waits on two owner items in `ai-context/OWNER-QUEUE.md`:

- **The WS8 guard patch** (item 8) brings the scope lock and tests-first. Without it, `build`
  mode allows no source write at all.
- **The DEMO-202 confirmations** (item 10). A build package is made only from a confirmed story,
  design and impact. Today `python3 tools/impacts/package.py DEMO-202` refuses with
  `./impacts/DEMO-202-round-robin-assignment/story.json is missing; nothing written`.

Once both are done, the sequence is:

1. A maintainer runs `python3 tools/impacts/package.py DEMO-202` (Windows:
   `py -3 tools/impacts/package.py DEMO-202`) and commits the package.
2. You run `python3 tools/impacts/start.py DEMO-202` (Windows: `py -3 tools/impacts/start.py DEMO-202`)
   in a real terminal, add the env lines it prints to `.claude/settings.local.json`, and
   restart Claude Code.
3. In Claude Code, type the input of implement-story eval case 001:

   ```
   /implement-story DEMO-202 Round-robin case assignment. Build mode is on for DEMO-202. Implement the story from impacts/DEMO-202-round-robin-assignment/build-package.json: new cases are assigned in turn across the assignment group when they are inserted.
   ```

The skill writes test skeletons first, then code, only inside the package's scope, and records
the change in `ai-context/DEMO-202-round-robin-assignment/change.json` and `change.md`. Eval case
002 (`002-out-of-scope-needed`) covers a story that needs a file outside scope: the write is
refused and the skill reports it. The patched guard's block message is not pasted here because the
patch is not applied yet. Under the applied guard, a source write in `build` is refused with
`no active story scope; run tools/impacts/start.py <storyId> (WS8)`.

## 7. Code checks pass; the change summary maps every file to the impact

*deterministic (no Claude Code)* (the rule check) and *needs Claude Code*, *needs owner
confirmations* (the trace check and the change summary)

The Apex rule check runs today. On the demo, every finding is in the committed baseline, so it
exits 0.

macOS / Linux:

```sh
python3 tools/code/check_rules.py --from-config
```

Windows (PowerShell):

```powershell
py -3 tools/code/check_rules.py --from-config
```

Expected: exit 0 with `"new": []`. Exact output: `demo/expected/06-check-rules.txt`. A finding
outside the baseline lands in `new` and the exit is 1.

After step 6, the trace check maps every acceptance criterion to a test, and the eval checks that
`change.json` is valid, that every touched file is inside the package scope and that every
`done[]` command passed:

```sh
python3 tools/code/check_trace.py DEMO-202
python3 tools/evals/run_skill.py --skill implement-story --case 001-assignment-on-insert --output ai-context/DEMO-202-round-robin-assignment/change.md --package impacts/DEMO-202-round-robin-assignment/build-package.json
```

(Windows: the same lines with `py -3`.) Today `check_trace.py` exits 2 with
`check_trace: trace core not found at <repo>/tools/guard/trace_core.py; apply the WS8 guard patch (ai-context/ws8/patches)`.

## 8. "Log into UAT and check": the guard blocks it

*needs Claude Code* (the live refusal) and *deterministic (no Claude Code)* (the block message)

In Claude Code, type:

```
Log into UAT and check the premium escalation flow.
```

Under the guard, the assistant has no route to an org. The guard is a best-effort laptop
control, not a hard boundary (see "What the guard guarantees" in `docs/DESIGN.md`). If it tries the Salesforce CLI login, the hook refuses the
call. If it refuses without trying, that is the expected outcome too. The settings file's
`permissions.deny` rules cover the same command prefixes, so Claude Code's own permission denial
can appear before the guard's message; which of the two reports first is Unverifiable here.

The guard's message for `sf org login web`, captured by sending the guard test harness's own login
case to the guard wrapper in a throwaway repo (exit 2 in both `normal` and `maintain`; no login was
attempted):

```
BLOCKED by tools/guard/guard.py: this Salesforce CLI command is always blocked: it changes an org, a credential or org data. Hand it to a human.
```

To check it yourself, find these lines in step 1's guard test output. The second case also
asserts that the message contains `always blocked`:

```
[PASS] sf org login is blocked: exit 2 (want 2)
[PASS] always blocked beats --help: exit 2 (want 2)
```

Login is blocked at every Salesforce CLI level and in every mode.

## 9. The consistency grid

*deterministic (no Claude Code)* (on the committed fixture) and *needs Claude Code* (live runs)

`tools/evals/consistency.py` compares several runs of one case on the fields that must agree. The
committed runs in `demo/expected/consistency-fixture/` are a **fixture**: hand-built to show the
format, not output from any model run (see the README there). One run drifts on purpose.

macOS / Linux:

```sh
python3 tools/evals/consistency.py demo/expected/consistency-fixture/run-1 demo/expected/consistency-fixture/run-2 demo/expected/consistency-fixture/run-3 --text
```

Windows (PowerShell):

```powershell
py -3 tools/evals/consistency.py demo/expected/consistency-fixture/run-1 demo/expected/consistency-fixture/run-2 demo/expected/consistency-fixture/run-3 --text
```

It prints the comparison as JSON and then the grid. The grid part, from a real run on the fixture:

```
Kind: impact

run-1 = demo/expected/consistency-fixture/run-1
run-2 = demo/expected/consistency-fixture/run-2
run-3 = demo/expected/consistency-fixture/run-3

field             run-1  run-2  run-3  agree
components        =      =      =      yes
componentRatings  =      =      x      no
evidence          =      =      =      yes
decisions         =      =      =      yes
(= matches the most common valid value, x differs, inv is invalid: no usable value)

Disagreements:
  componentRatings
    run-1: [["CaseAssignmentService", "Medium", "Confirmed"], ["CaseAssignmentService_Test", "Medium", "Confirmed"], ["CaseTrigger", "Medium", "Confirmed"], ["CaseTriggerHandler", "Medium", "Confirmed"], ["CaseTriggerHandler_Test", "Medium", "Confirmed"], ["Escalation_Agents", "Low", "Inferred"]]
    run-2: [["CaseAssignmentService", "Medium", "Confirmed"], ["CaseAssignmentService_Test", "Medium", "Confirmed"], ["CaseTrigger", "Medium", "Confirmed"], ["CaseTriggerHandler", "Medium", "Confirmed"], ["CaseTriggerHandler_Test", "Medium", "Confirmed"], ["Escalation_Agents", "Low", "Inferred"]]
    run-3: [["CaseAssignmentService", "Medium", "Confirmed"], ["CaseAssignmentService_Test", "Medium", "Confirmed"], ["CaseTrigger", "Medium", "Confirmed"], ["CaseTriggerHandler", "Medium", "Confirmed"], ["CaseTriggerHandler_Test", "Medium", "Confirmed"], ["Escalation_Agents", "Low", "Confirmed"]]

2/3 identical
```

The `2/3 identical` line describes the fixture, not a skill. Full output:
`demo/expected/05-consistency.txt`.

**Live runs.** `tools/evals/run_all.py` runs one eval case several times with `claude -p` on a
pinned model and collects each run into `ai-context/evals/<skill>-<case>/run-<i>/`. It needs your
Claude Code account, and the assistant cannot run it. See `tools/evals/README.md` for the operator
notes (a clean worktree per run, diff-names files for code runs).

```sh
python3 tools/evals/run_all.py --case story-impact/004-escalation-hops-3 --n 5 --model <model-id>
python3 tools/evals/consistency.py ai-context/evals/story-impact-004-escalation-hops-3/run-1 ai-context/evals/story-impact-004-escalation-hops-3/run-2 ai-context/evals/story-impact-004-escalation-hops-3/run-3 ai-context/evals/story-impact-004-escalation-hops-3/run-4 ai-context/evals/story-impact-004-escalation-hops-3/run-5 --text
```

Each run folder's `run.json` records the model, the Claude Code version, the framework version
and the index stamp. A consistency figure holds only for that combination. Golden outputs from
the owner's runs belong in `evals/expected/`, which does not exist yet, so no model or Claude Code
version is named here as reproducing them.

## 10. Scores against the answer key

*deterministic (no Claude Code)* (the committed record) and *needs Claude Code* (scoring your own
run)

`demo/measure/score.py` compares an impact record's components with a reviewed answer key and
lists what it found, missed and added.

macOS / Linux:

```sh
python3 demo/measure/score.py impacts/DEMO-202-round-robin-assignment/impact.json --key demo/stories/DEMO-202.answer.json
```

Windows (PowerShell):

```powershell
py -3 demo/measure/score.py impacts/DEMO-202-round-robin-assignment/impact.json --key demo/stories/DEMO-202.answer.json
```

Expected, from a real run:

```
{
  "found": [
    "CaseAssignmentService",
    "CaseAssignmentService_Test",
    "CaseTriggerHandler",
    "CaseTriggerHandler_Test",
    "CaseTrigger",
    "Escalation_Agents"
  ],
  "missed": [],
  "extra": [],
  "recall": 1.0,
  "precision": 1.0
}
```

The committed DEMO-202 record was derived from its answer key (its `provenance.model` reads
`none (derived from reviewed answer key)`), so it scores complete by construction. This shows the
script works; it is not a measure of the assistant. Exact output:
`demo/expected/04-score-demo-202.txt`.

To score a skill run, point the script at the draft from step 3 or 4:

```sh
python3 demo/measure/score.py ai-context/DEMO-201-<slug>/impact.json --key demo/stories/DEMO-201.answer.json
```

(Windows: the same line with `py -3`.) To measure time as well, and to compare with someone
working by hand, see `demo/measure/README.md`.

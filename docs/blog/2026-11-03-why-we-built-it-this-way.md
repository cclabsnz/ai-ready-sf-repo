# Why we built ai-ready-sf-repo this way

*3 November 2026*

AI can write Salesforce code faster than any team can review it. ai-ready-sf-repo is an MIT-licensed reference repo for enterprise Salesforce teams that want that speed without losing track of what changed, why, and who agreed to it. This post explains the three rules behind its design, walks through one real run, and is honest about what it does not do yet.

## The problem is not the Apex

In a large org, writing the trigger is the easy part. The hard parts are knowing what a change will touch, knowing which other squad is changing the same class, and knowing that someone with the authority to say yes actually said yes.

An AI assistant makes the easy part cheaper and the hard parts worse. It answers confidently about metadata it never opened. It counts things it guessed. Ask it to "check in UAT" and it will try. Two squads can ask it about the same `CaseTriggerHandler` on the same day, and neither hears about the other.

We could have written a longer system prompt. We didn't, because a prompt is a request, and the model is free to misread it. Every rule that matters in this repo is enforced by a script, a hook or a CI check, and the prompts only explain those rules.

## Rule 1: the build is the only source of truth

The checked-out metadata (`force-app/`, packages, manifests) is the only evidence the assistant may cite. Knowledge files, wikis and its own memory are leads to re-check, never proof.

That rule needed tooling. `tools/index/build_index.py` parses the source into a dependency index, and `tools/index/query.py` answers questions such as "what reaches this class within three hops". Anything countable comes from that query at a stated commit. The assistant never types a number from memory.

Every claim in an impact report then carries a `path:line` reference, or a negative finding such as "zero hits for pattern X". It also carries one of three labels:

- **Confirmed:** the build shows it.
- **Inferred:** it is reasoned from what the build shows.
- **Unverifiable:** it lives in org configuration, managed-package internals, or an input nobody provided.

The validators reject a report that skips this. The labels matter most when they are uncomfortable. "Assignment rules in the org may overwrite this owner: Unverifiable, Salesforce Admin to confirm" is more useful than a confident guess, because it names the person who can actually answer.

## Rule 2: the assistant recommends, a named person confirms

The assistant may analyse, draft and recommend, then carry on with its draft. It never approves, deploys, pushes or makes a binding decision. A draft becomes a committed record only when a person runs `tools/impacts/promote.py --confirmed-by "<role>"` in their own terminal.

Promotion refuses on purpose:

- an open question that nobody has answered or explicitly deferred blocks it;
- vague acceptance criteria block it ("saves quickly" fails `check_ac.py`);
- evidence that doesn't open at the cited line blocks it;
- anything that looks like real data (record IDs, emails, credentials) blocks it.

Confirmed records live in `impacts/`, in git, and together they form a register. When a second squad drafts an impact that touches a component already on the register, the report says so, and so does the pull request check. Overlaps are found when the analysis is drafted, not in a merge conflict three weeks later.

## Rule 3: guardrails live in code, not in prompts

A Claude Code hook (`tools/guard/`) runs before every tool call. It works in four modes:

- **`advise`:** read-only.
- **`normal`:** the framework's own analysis scripts.
- **`build`:** writes, but only to the exact files one story's build package lists.
- **`maintain`:** framework upkeep.

In every mode it blocks org calls, deploys, pushes, `curl`, and writes to its own files, settings or CI workflows. It also blocks shell tricks it cannot see through: variable expansion, heredocs, and globs that could turn into options.

The assistant cannot switch modes itself. A person runs `tools/impacts/start.py` in a real terminal, pastes two lines into their personal settings and restarts the session. That terminal step is deliberate: a build session starts only when someone chose to start it.

The laptop guard is best effort, and we say so. Someone determined can work around a local hook. The control that holds is CI with branch protection and code owners. The checks that matter for a merge run again on the pull request: the real-data scan, the Apex rules, the criterion-to-test trace for changed build packages, and the impact and overlap checks. The hook catches mistakes early; CI is what blocks a merge.

## The chain, from story to code

Each step has one owner and leaves a reviewed file behind:

1. **story-refine** (assistant) turns a rough story into acceptance criteria, edge cases seeded from the index, and open questions, each with an owner role. A person answers or defers each question and promotes the story.
2. **solution-design** (assistant) writes two to four options, always including "do nothing", with evidence-backed trade-offs and one provisional recommendation. A person chooses.
3. **story-impact** (assistant) sizes the chosen option: every component touched, with evidence, a label and its overlaps. A person promotes it.
4. **package.py** (a maintainer) folds the confirmed story, design and impact into a build package: exact file paths to modify, create and test, plus the criteria and the done commands. It refuses if the source has changed since the analysis.
5. **start.py** (a person) opens a build session scoped to that package.
6. **implement-story** (assistant) writes a test for every criterion first, then the code, only inside the package. A file outside scope gets a written scope request, not a quiet edit. `check_trace.py` proves every criterion has a test that names it.

None of these steps deploys anything. Apex compiles and runs in the adopter's own org-connected CI, after a named reviewer has approved the pull request.

## What one real run taught us

We ran the whole chain once on the demo story DEMO-202, which assigns new cases to agents in turn. Four things came out of it that a faster, less careful process would have missed.

**An open question shrank the change.** The first impact flagged two existing test classes that would break, because they create cases with an explicit owner. Story refinement had not asked whether an explicit owner should be kept. We added that question, and the Product Owner answered "keep the explicit owner" as a new criterion, AC-7. Both test classes then dropped out of the impact. The question cost one round and saved two unplanned test rewrites.

**The packager caught a criterion that could never be tested.** Story refinement raises one "org-only" edge case per object: sharing and real data volumes are org configuration that the repo can't show. The packager turned it into a criterion that needed a test, and no Apex test in a repo can prove an org's sharing settings. We moved it to the open question that already covered it, and queued a fix to the framework, so every adopter doesn't hit the same wall.

**The builder found a conflict the analysis had missed.** Because the code honours user-mode access, anyone without access to the new rotation object fails to save a case once the agent pool has members. That covers integration users and Web-to-Case. The Product Owner had said no case is excluded. The builder did not quietly pick a fix; it reported the conflict for the Tech Lead and Salesforce Admin to decide.

**The scores are honest, including the unflattering one.** Against an answer key written before the design existed, the impact found every expected component (recall 1.0) but also listed seven the key doesn't have (precision 0.46). Those seven are the new object, its field, two permission sets and three review items the chosen design needs. We left the key unchanged. A key edited after seeing a run is no longer a blind test.

## How it helps a team

- **Review gets cheaper.** Every claim cites a file and line, so a reviewer checks evidence instead of re-deriving the analysis.
- **Squads stop colliding.** Overlaps on shared components surface when an impact is drafted, through a register that lives in git.
- **Decisions are traceable.** Each story, design and impact records who confirmed it, and the build package records which versions it was built from.
- **Scope creep is visible.** The assistant can't edit a file the package doesn't list. It has to ask, in writing.
- **Real data stays out.** A deterministic scanner runs before every promotion and in CI. It doesn't rely on the model's judgement.

## What it does not do yet

- **No Apex has been compiled or run.** That includes the demo build. The repo is offline by design, so Apex is checked by your org-connected CI, which this repo doesn't include.
- **No live model evals have been scored.** There are no golden outputs and no consistency figures yet. The eval harness and the cases exist.
- **Tested on macOS only.** The CI workflow runs on Ubuntu and Windows, but Windows has not had a green run yet.
- **One end-to-end run.** DEMO-202 is a single story, with a person answering questions along the way. It is an example, not a benchmark.
- **The guard is not a security boundary on a laptop.** It catches mistakes. Branch protection and code owners are the control.

## Try it

Clone the repo, open it in Claude Code, and follow `demo/WALKTHROUGH.md`. Each step is labelled as deterministic, needing Claude Code, or needing an owner's confirmation, so you can see which outputs are fixed and which vary from run to run. `docs/ADOPTING.md` covers bringing the framework to your own org: what to copy, what to change, and which settings to turn on in GitHub.

Issues and skill proposals are welcome through the templates in `.github/ISSUE_TEMPLATE/`.

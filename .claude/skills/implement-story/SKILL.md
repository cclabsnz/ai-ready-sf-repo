---
name: implement-story
description: Write tests first, then code, for one story inside its committed build package scope, and record the change. Use when a build session is started for a story. Not for design, sizing, deploys or pushes.
---
# Implement story

Audience: developers and tech leads. Output: test skeletons and code inside the build package scope, and a `change.json` and `change.md` that map every file, every criterion to its tests, and every done command to its exit code. Not in scope: choosing a design (that is `solution-design`), sizing (`story-impact`), widening scope, deploying, pushing, committing to a remote, merging, or reviewing the work.

## Prerequisite: build mode
A human has run `python3 tools/impacts/start.py <id>` from a real terminal, pasted the two printed env lines into `.claude/settings.local.json`, and restarted the session. That puts the guard in build mode with the scope lock on this story's committed package. Without it, every write under the source root is refused by the guard; do not try to work around a block, report it. The assistant never runs `start.py` and never edits settings.

## Guardrails
Project rules apply (`00-precedence`, `10-apex`, `20-no-real-data`). The guard blocks org calls, deploys, pushes and writes outside the package scope and `ai-context/`. The skill never deploys, pushes, merges or commits code to a remote, and never approves its own work: a named reviewer reviews the pull request. Apex compiles and runs only in the adopter's org-connected CI; the done commands are offline checks.

## Step 1: read the package
Read `impacts/<id>-<slug>/build-package.json` and nothing else for scope, criteria, rules and done commands. Build the table from `references/input-checklist.md` and show it. The package is the only input: the story, design and impact are already folded into it. A missing package means the owner steps are not done; stop and say so.

## Step 2: tests first
For each id in `criteria[]` (`AC-n`, and `EC-n` for kept edge cases), write one test method in a file listed in `scope.tests`. Each test method carries a structured comment with its id on its own line, `// AC-1` or `// EC-2`. Apex method names cannot contain a hyphen, so the comment is the only convention. A skeleton asserts the behaviour named in the criterion's `then` (values, counts, exceptions), never `System.assert(true)`, and never uses `SeeAllData=true`.

## Step 3: check the skeletons
Run `python3 tools/code/check_trace.py --skeletons <id>`. Exit 0 means every criterion id is referenced by a test file in scope. Exit 1 lists `missingCriteria`: add the missing skeletons and run it again. Exit 2 is bad usage or a missing guard core; report it.

## Step 4: write the change
Write code only in files listed in `scope.modify` or as a `path` in `scope.create`, and tests only in `scope.tests`. Follow `framework/rules/10-apex.md`; `tools/code/check_rules.py` reports these rule ids: `apex-sharing`, `apex-user-mode`, `apex-no-soql-dml-in-loop`, `apex-no-system-debug`, `apex-no-seealldata`, `apex-no-assert-true`, `apex-test-naming`. Every class declares its sharing; `without sharing` carries a comment stating why. SOQL uses `WITH USER_MODE` and DML uses `AccessLevel.USER_MODE` outside test classes. No SOQL or DML in loops. Logging goes through the project logger. Each new Apex class has its `-meta.xml` companion, which is listed in scope.

## Step 5: run the done commands
Run every command in the package `done[]`, in order, from the repo root. Record each command with its integer exit code. A non-zero exit is fixed inside scope and the commands run again; when it cannot be fixed inside scope, record the exit as it is and report it as not done. The recorded exits are the session's own report: `write_change.py` does not run or re-run them, so `change.md` labels them Inferred; CI re-runs them.

## Step 6: write the record
1. Write the draft to `ai-context/<id>-<slug>/scan/change-draft.json` per `references/change-summary.md`: `storyId`, `files`, `criteriaToTests`, `done`. The writer fills `schemaVersion`, `slug` and `package`; a draft that carries them is refused.
2. Run `python3 framework/skills/implement-story/scripts/write_change.py --id <id> --slug <slug> --draft ai-context/<id>-<slug>/scan/change-draft.json`. It finds the single `impacts/<id>-*/build-package.json` (or `--package <path>`), checks that every file is in scope, every criterion maps to at least one test that names it, and every done command is recorded with an integer exit. It writes nothing on errors (exit 1). Fix the draft and run it again until it exits 0.
3. `change.md` is built by the script from `change.json`. Report it as written and never rewrite it.

## Step 7: out of scope
When the change needs a component that is not in the package scope (a file outside `scope.modify`, `scope.create` and `scope.tests`), stop. Do not write it, do not edit the package, and do not ask for the guard to be relaxed. Write `ai-context/<id>-<slug>/scope-request.md` per `references/scope-request.md`, with the component, the reason and the evidence, and report. The scope changes only through a new impact and package, made by a human. Never widen scope.

## Response style
Lead with the done table (command, exit). Then the files changed with evidence and confidence, the criteria-to-tests map, any scope request, and the artefact paths. Say plainly that the change is unreviewed until a named reviewer reviews the pull request, and that Apex has not compiled or run here.

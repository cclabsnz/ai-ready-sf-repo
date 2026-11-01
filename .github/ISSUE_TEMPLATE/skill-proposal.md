---
name: Skill or agent proposal
about: Propose a new skill or agent, or a change to an existing one
labels: proposal
---

<!-- Read CONTRIBUTING.md first. Use synthetic examples only. -->

## Name and kind

- Name (kebab-case):
- Kind: skill / agent / change to an existing one

## When to use it, and what it is not for

The draft `description`, at most 200 characters, saying when to use it and what it is not for:

## Inputs

What it needs before it starts, and what it does when an input is missing. This becomes
`references/input-checklist.md`.

## Deterministic parts

The steps a script does (index queries, writing or validating the output), and the scripts they
need. The model only interprets their results.

## Output

The output's shape and where it is written (under `ai-context/`). Every claim carries evidence
and the label Confirmed, Inferred or Unverifiable.

## Eval cases

At least 3 cases, each with an input and deterministic assertions (references that must appear,
labels on every claim, banned phrases, cited `path:line` that must exist).

1.
2.
3.

## Agent only

The tools it needs, the skills it runs, and a trajectory eval (must-call, must-not-call,
must-block).

## Guard and owner patches

Does it need a guard allowlist entry, a new write path or a CI step? If so, it needs an owner
patch. Describe it here.

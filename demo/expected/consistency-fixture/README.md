# Consistency fixture (hand-built, not a model run)

These run folders exist only to show what `tools/evals/consistency.py` prints. They are not
output from `tools/evals/run_all.py`, no model produced them, and the `k/N identical` line they
give is not a consistency figure for any skill.

- Each `run-<i>/impact.json` is a trimmed copy of the committed DEMO-202 record
  (`impacts/DEMO-202-round-robin-assignment/impact.json`): its components, ratings, evidence and
  decision.
- `run-2` lists the components in a different order. The comparer treats them as sets, so the
  order is not drift.
- `run-3` drifts on purpose: it rates `Escalation_Agents` `Confirmed` instead of `Inferred`, so
  the grid shows one disagreement.

Golden outputs from live runs belong in `evals/expected/`, which the owner produces with
`run_all.py` (see `ai-context/OWNER-QUEUE.md`). That folder does not exist yet.

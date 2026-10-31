# tools/evals

- `run_skill.py` applies a skill's deterministic eval assertions to outputs that were already produced. It makes no model call.
- `run_agent.py` checks an agent's tool-call log against a trajectory spec.
- `run_all.py` runs one eval case several times with `claude -p`, pinned to one model, and collects each run into `ai-context/evals/<skill>-<case>/run-<i>/`. Only the operator runs it. It needs the operator's Claude Code account.
- `consistency.py` compares the run folders on the fields that must agree. It prints a grid and a `k/N identical` line.

```
python3 tools/evals/run_all.py --case story-impact/004-escalation-hops-3 [--n 5] [--model <id>]
python3 tools/evals/consistency.py ai-context/evals/story-impact-004-escalation-hops-3/run-* --text
```

Each run folder gets a `run.json` that records the model, the Claude Code version (`claude --version`, or `"unknown"`), the framework `VERSION`, the index stamp and the exit code.

## Operator notes

- **Use a clean worktree for each run.** Runs that share one working tree see each other's work:
  - An implement-story run sees the previous run's edits.
  - Any skill may find an earlier run's `ai-context/<id>-<slug>/` outputs.

  Start each run from a clean worktree at the same commit.
- **Write a diff-names file for each implement-story run.** After each run, list the touched paths in one file per run:
  - Combine `git diff --name-only` with `git ls-files --others --exclude-standard`. The plain diff misses new files.
  - Remove every `ai-context/` path. Run folders differ per run and would show up as drift.

  Pass the files to `consistency.py --diff-names` in run order. `consistency.py` takes the touched files from these lists, never from `change.json`.
- **Confirm the flags.** Before the first series, check `-p`, `--model` and `--output-format` against `claude --help` for the installed Claude Code version.
- **Headless permissions are yours to set.** Print mode cannot answer permission prompts, and `run_all.py` passes no bypass flag. The project's settings and your own Claude Code settings decide whether the skill can write files and run its scripts.
- **Two case ids don't match the story-id pattern.** The story-impact cases with ids `9001` and `9004` don't match the pattern the skills' writers expect (`PREFIX-n`). Check where those runs write their outputs before you compare them.

# Measurement kit

This kit measures impact analysis the same way for an assistant run and for a person working by hand. It publishes a method and the figures its scripts produce on the committed demo. It publishes no estimate and no time-saved figure.

## Method

1. **Fix the answer first.** Each demo story has a hand-written key in `demo/stories/*.answer.json`. For your own stories, write the key before anyone starts.
2. **Capture the record.** The assistant's output is an `impact.json`. A person's output is a file of the same shape: `{"components": [{"api": "..."}]}`.
3. **Score it.** `score.py` compares the record's component apis with the key's, ignoring letter case as Salesforce does, and lists found, missed and extra (found and extra in the record's spelling). Recall and precision are fractions the script computes.
4. **Time it.** For an assistant run, `timing.py` reads the Claude Code session transcript and prints first and last timestamp, duration and tool-call count. For a person, use a clock and record minutes in the baseline template. Review time is recorded by the reviewer, in the same way.

Scope: `score.py` scores `impact.json` components only. Scoring a refined `story.json` is not covered.

## Scripts

```
python3 demo/measure/score.py <impact.json> --key <answer.json>
python3 demo/measure/timing.py <session.jsonl>
```

- `score.py` prints `{found, missed, extra, recall, precision}` and exits 0. It exits 2 on a missing or malformed input. It loads and validates the key with `tools/demo/check_answers.py`.
- `timing.py` prints `{start, end, durationSeconds, toolCalls}`. Tool calls are assistant content blocks of type `tool_use`. Lines it cannot read are skipped. It exits 2 when the transcript has no timestamps.
- Tests: `python3 demo/measure/test_score.py` and `python3 demo/measure/test_timing.py`.

These scripts live under `demo/`, so they run in the guard's maintain mode through `maintainer_tools`.

## Measure your own baseline

Copy `baseline-template.md`, follow its steps, and keep one row per attempt with its source. A time-saved figure appears in this repo only after a measured baseline is committed with that source, and it is then computed from the committed rows, not typed.

## What the repo publishes

Only output of these scripts on the committed demo, each with its command and source.

### DEMO-202: committed impact against its key

- Command: `python3 demo/measure/score.py impacts/DEMO-202-round-robin-assignment/impact.json --key demo/stories/DEMO-202.answer.json`
- Source: `impacts/DEMO-202-round-robin-assignment/impact.json` and `demo/stories/DEMO-202.answer.json`
- Label: answer-key-derived record. The committed impact was built from the answer key, so it scores trivially. It shows the script works. It is not a measure of the assistant.

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

No timing figure is published yet. It needs a live session transcript, which is a run the owner makes.

# Manual baseline template

This table is empty on purpose. The repo carries no baseline figure until someone measures one and commits it with its source.

## How to fill it

1. Pick a story that has an answer key (`demo/stories/*.answer.json`), or one from your own backlog with a key you wrote before starting.
2. Have one person do the impact analysis by hand, with no assistant. Time it with a clock, from opening the story to writing down the final component list.
3. Write the component list to an `impact.json`-shaped file: `{"components": [{"api": "..."}]}`.
4. Score it: `python3 demo/measure/score.py <that file> --key <answer key>`. Copy the found, missed and extra lists into the row.
5. Add one row per attempt. Do not average rows into a single figure in this file.

| story | who (role) | date | minutes | components found | missed | extra | source |
|-------|------------|------|---------|------------------|--------|-------|--------|
|       |            |      |         |                  |        |       |        |

Columns:
- **who:** a role, not a name.
- **minutes:** wall-clock time you measured, as written down at the time.
- **components found / missed / extra:** the lists from `score.py`, once scored.
- **source:** where the row comes from, such as the path of the scored file and the command you ran.

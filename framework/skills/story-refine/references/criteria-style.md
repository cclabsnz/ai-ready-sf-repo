# Criteria style

`tools/stories/check_ac.py` enforces these rules; `write_story.py` runs it and writes nothing while any criterion fails.

| Rule | What fails | Fix |
|---|---|---|
| `missing-gwt` | An empty `given`, `when` or `then` | Fill all three |
| `multiple-outcomes` | A `then` with `;`, more than one sentence, or the word `and` or `or`, outside quoted text | Split the criterion in two |
| `no-example` | `examples` is empty | Add at least one concrete example: a value, a record, a user |
| `vague-word` | A word from `tools/stories/vague_words.json` in `given`, `when` or `then`, outside quoted text | Replace it with a number, a value or a named outcome; if nobody knows the number, add an open question |

Quoted text is `"..."` or `` `...` ``. Quote picklist values, labels and messages exactly (`"Level 2"`), which also keeps their words out of the checks.

## Shape

- **Given** the starting state: the record, its field values, the user's access.
- **When** one action or event.
- **Then** one observable outcome a tester can check.
- **Examples** concrete instances, one per entry.
- **Source** `stated`, `edge-case` or `assistant-proposed`.

## Vague words in the story

A vague word in the story text ("quickly", "properly") is not fixed by guessing. Quote it in an open question with an owner role, for example: `The story says "should work quickly"; what response time is acceptable?` (Product Owner). The criterion then waits for the answer or states only what is known.
